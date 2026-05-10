"""
app/__init__.py — Flask application factory.

Creates and configures the Flask application. This pattern (factory function)
lets us create multiple app instances for testing without global state issues.
"""

import logging
import os
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flasgger import Swagger
from pymongo import MongoClient, ASCENDING, DESCENDING, TEXT, GEOSPHERE

from app.config import config_map, DevelopmentConfig

logger = logging.getLogger(__name__)


def create_app(config_name: str = None) -> Flask:
    """
    Application factory.

    Args:
        config_name: One of 'development', 'production', 'testing'.
                     Defaults to the FLASK_ENV environment variable or 'development'.
    """
    # Resolve config
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")
    config_class = config_map.get(config_name, DevelopmentConfig)

    app = Flask(__name__)
    app.config.from_object(config_class)

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level = logging.DEBUG if app.config.get("DEBUG") else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # ── Extensions ────────────────────────────────────────────────────────────
    _init_extensions(app)

    # ── MongoDB indexes ───────────────────────────────────────────────────────
    _create_indexes(app)

    # ── Blueprints ────────────────────────────────────────────────────────────
    _register_blueprints(app)

    # ── Error handlers ────────────────────────────────────────────────────────
    _register_error_handlers(app)

    # ── ML model (eager load unless ML_LAZY_LOAD=true) ────────────────────────
    if not app.config.get("ML_LAZY_LOAD", False):
        with app.app_context():
            _load_ml_model()

    # ── Swagger docs ──────────────────────────────────────────────────────────
    _init_swagger(app)

    logger.info("BiomeBa app created (env=%s)", config_name)
    return app


# ── Extension initialisation ───────────────────────────────────────────────────

def _init_extensions(app: Flask) -> None:
    """Initialise all Flask extensions with the app instance."""
    from app.extensions import db as _db_placeholder, jwt, limiter

    # ── CORS ──────────────────────────────────────────────────────────────────
    origins = app.config.get("CORS_ORIGINS", ["*"])
    CORS(app, origins=origins, supports_credentials=True)

    # ── JWT ───────────────────────────────────────────────────────────────────
    jwt.init_app(app)

    # Custom JWT error responses (return JSON, not HTML)
    @jwt.unauthorized_loader
    def missing_token_callback(reason):
        return jsonify({"error": "Authorization token is missing.", "detail": reason}), 401

    @jwt.invalid_token_loader
    def invalid_token_callback(reason):
        return jsonify({"error": "Invalid authorization token.", "detail": reason}), 401

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({"error": "Token has expired. Please log in again."}), 401

    # ── Rate limiter ──────────────────────────────────────────────────────────
    limiter.storage_uri = app.config.get("RATELIMIT_STORAGE_URI", "memory://")
    limiter.default_limits = [app.config.get("RATELIMIT_DEFAULT", "100 per minute")]
    limiter.init_app(app)

    # ── PyMongo ───────────────────────────────────────────────────────────────
    import app.extensions as ext
    ext.mongo_client = MongoClient(app.config["MONGO_URI"])
    ext.db = ext.mongo_client[app.config["MONGO_DBNAME"]]

    # Ping to verify connection at startup
    try:
        ext.mongo_client.admin.command("ping")
        logger.info("MongoDB connected: %s", app.config["MONGO_DBNAME"])
    except Exception as exc:
        logger.warning("MongoDB ping failed: %s", exc)


def _create_indexes(app: Flask) -> None:
    """Create all MongoDB indexes. Idempotent — safe to run multiple times."""
    import app.extensions as ext

    if ext.db is None:
        return

    db = ext.db

    try:
        # ── Users ──────────────────────────────────────────────────────────────
        db.users.create_index([("email", ASCENDING)], unique=True, name="idx_email_unique")
        db.users.create_index([("username", ASCENDING)], unique=True, name="idx_username_unique")
        db.users.create_index([("xp", DESCENDING)], name="idx_xp_desc")
        db.users.create_index([("country", ASCENDING), ("xp", DESCENDING)], name="idx_country_xp")

        # ── Observations ───────────────────────────────────────────────────────
        db.observations.create_index([("location", GEOSPHERE)], name="idx_location_2dsphere")
        db.observations.create_index([("selected_species", ASCENDING)], name="idx_species")
        db.observations.create_index([("user_id", ASCENDING), ("timestamp", DESCENDING)], name="idx_user_timestamp")
        db.observations.create_index([("rarity_score", DESCENDING)], name="idx_rarity_score")
        db.observations.create_index(
            [("country", ASCENDING), ("state", ASCENDING), ("district", ASCENDING)],
            name="idx_region",
        )

        # ── Posts ──────────────────────────────────────────────────────────────
        db.posts.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)], name="idx_post_user_time")
        db.posts.create_index([("created_at", DESCENDING)], name="idx_post_time")

        # ── Comments ──────────────────────────────────────────────────────────
        db.comments.create_index([("post_id", ASCENDING), ("created_at", ASCENDING)], name="idx_comment_post_time")

        # ── Missions ──────────────────────────────────────────────────────────
        db.missions.create_index([("type", ASCENDING), ("is_active", ASCENDING)], name="idx_mission_type_active")
        db.user_mission_progress.create_index(
            [("user_id", ASCENDING), ("mission_id", ASCENDING)],
            unique=True,
            name="idx_ump_user_mission",
        )

        # ── Notifications ──────────────────────────────────────────────────────
        db.notifications.create_index(
            [("recipient_id", ASCENDING), ("read", ASCENDING), ("created_at", DESCENDING)],
            name="idx_notif_recipient",
        )

        # ── Species metadata ───────────────────────────────────────────────────
        db.species_meta.create_index([("species", ASCENDING)], unique=True, name="idx_species_meta")

        logger.info("MongoDB indexes ensured.")
    except Exception as exc:
        logger.warning("Index creation warning: %s", exc)


# ── Blueprint registration ─────────────────────────────────────────────────────

def _register_blueprints(app: Flask) -> None:
    from app.routes.auth import bp as auth_bp
    from app.routes.profile import bp as profile_bp
    from app.routes.species import bp as species_bp
    from app.routes.missions import bp as missions_bp
    from app.routes.leaderboard import bp as leaderboard_bp
    from app.routes.social import bp as social_bp
    from app.routes.search import bp as search_bp
    from app.routes.test_ui import test_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(species_bp)
    app.register_blueprint(missions_bp)
    app.register_blueprint(leaderboard_bp)
    app.register_blueprint(social_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(test_bp)

    # Health check at root
    @app.get("/health")
    def health():
        import app.extensions as ext
        return jsonify({
            "status": "ok",
            "db": app.config["MONGO_DBNAME"],
            "ml_model_loaded": ext.db is not None,
        }), 200

    logger.info("Blueprints registered.")


# ── Error handlers ─────────────────────────────────────────────────────────────

def _register_error_handlers(app: Flask) -> None:
    """Return JSON for common HTTP errors instead of HTML pages."""

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": "Bad request.", "detail": str(e)}), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({"error": "Unauthorized."}), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({"error": "Forbidden."}), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Resource not found."}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"error": "Method not allowed."}), 405

    @app.errorhandler(429)
    def rate_limited(e):
        return jsonify({"error": "Too many requests. Please slow down.", "retry_after": str(e.retry_after)}), 429

    @app.errorhandler(500)
    def internal_error(e):
        logger.error("Internal server error: %s", e, exc_info=True)
        return jsonify({"error": "Internal server error."}), 500


# ── ML model loading ───────────────────────────────────────────────────────────

def _load_ml_model() -> None:
    """Load the ONNX inference session at startup."""
    try:
        from app.ml import inference
        inference.load_model()
    except Exception as exc:
        logger.error("Failed to load ML model: %s", exc)


# ── Swagger ───────────────────────────────────────────────────────────────────

def _init_swagger(app: Flask) -> None:
    swagger_config = {
        "headers": [],
        "specs": [
            {
                "endpoint": "apispec",
                "route": "/apispec.json",
                "rule_filter": lambda rule: True,
                "model_filter": lambda tag: True,
            }
        ],
        "static_url_path": "/flasgger_static",
        "swagger_ui": True,
        "specs_route": "/apidocs",
    }

    template = {
        "swagger": "2.0",
        "info": {
            "title": "BiomeBa API",
            "description": (
                "Gamified Biodiversity Social Platform — REST API\n\n"
                "All protected routes require: `Authorization: Bearer <token>`"
            ),
            "version": "1.0.0",
            "contact": {"name": "BiomeBa Team"},
        },
        "basePath": "/",
        "schemes": ["http", "https"],
        "securityDefinitions": {
            "Bearer": {
                "type": "apiKey",
                "name": "Authorization",
                "in": "header",
                "description": "Enter: **Bearer &lt;your_token&gt;**",
            }
        },
        "consumes": ["application/json"],
        "produces": ["application/json"],
    }

    Swagger(app, config=swagger_config, template=template)
    logger.info("Swagger UI available at /apidocs")
    logger.info("Swagger UI available at /apidocs")
