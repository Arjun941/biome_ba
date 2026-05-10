"""
app/extensions.py — Flask extension singletons.
These are instantiated here without an app, then initialized
inside create_app() via init_app(app). This avoids circular imports.
"""

from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pymongo import MongoClient

# JWT authentication manager
jwt = JWTManager()

# Rate limiter — keys on the client IP by default
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],          # Default set dynamically in create_app
    storage_uri="memory://",    # Overridden in create_app from config
)

# PyMongo client & db references (set in create_app)
mongo_client: MongoClient | None = None
db = None  # Will be set to the actual database object in create_app
