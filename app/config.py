"""
app/config.py — Environment-aware configuration classes.
Settings are read from environment variables (populated by .env via python-dotenv).
"""

import os
from datetime import timedelta


class Config:
    """Base configuration shared across all environments."""

    # ── Flask ─────────────────────────────────────────────────────────────────
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    JSON_SORT_KEYS: bool = False

    # ── MongoDB ───────────────────────────────────────────────────────────────
    MONGO_URI: str = os.environ.get("MONGO_URI", "mongodb://localhost:27017/biome_ba")
    MONGO_DBNAME: str = os.environ.get("MONGO_DBNAME", "biome_ba")

    # ── JWT ───────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = os.environ.get("JWT_SECRET_KEY", "jwt-secret-change-me")
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(
        hours=int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRES_HOURS", 24))
    )
    JWT_REFRESH_TOKEN_EXPIRES: timedelta = timedelta(
        days=int(os.environ.get("JWT_REFRESH_TOKEN_EXPIRES_DAYS", 30))
    )

    # ── ML Model ──────────────────────────────────────────────────────────────
    # These paths are resolved relative to the project root (parent of /app)
    _BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ML_MODEL_PATH: str = os.path.join(
        _BASE_DIR, os.environ.get("ML_MODEL_PATH", "model_fp16.onnx")
    )
    ML_CONFIG_PATH: str = os.path.join(
        _BASE_DIR, os.environ.get("ML_CONFIG_PATH", "config.json")
    )
    ML_LAZY_LOAD: bool = os.environ.get("ML_LAZY_LOAD", "false").lower() == "true"

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    RATELIMIT_DEFAULT: str = os.environ.get("RATE_LIMIT_DEFAULT", "100 per minute")
    RATELIMIT_STORAGE_URI: str = "memory://"  # swap to Redis in prod
    RATELIMIT_IDENTIFY: str = os.environ.get("RATE_LIMIT_IDENTIFY", "10 per minute")

    # ── CORS ─────────────────────────────────────────────────────────────────
    CORS_ORIGINS: list = os.environ.get("CORS_ORIGINS", "*").split(",")

    # ── Pagination ────────────────────────────────────────────────────────────
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100


class DevelopmentConfig(Config):
    DEBUG: bool = True
    TESTING: bool = False


class ProductionConfig(Config):
    DEBUG: bool = False
    TESTING: bool = False
    # In production, use Redis for rate limiting
    RATELIMIT_STORAGE_URI: str = os.environ.get("REDIS_URL", "memory://")


class TestingConfig(Config):
    TESTING: bool = True
    MONGO_URI: str = "mongodb://localhost:27017/biome_ba_test"
    MONGO_DBNAME: str = "biome_ba_test"


# Map string names → config classes (used in create_app)
config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
