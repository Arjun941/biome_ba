"""
app/middleware/auth_middleware.py — JWT authentication decorator.

Usage:
    from app.middleware.auth_middleware import token_required

    @bp.route("/protected")
    @token_required
    def protected_route(current_user):
        return jsonify({"user": current_user["username"]})

The `current_user` dict is the full MongoDB user document (minus password_hash).
"""

import logging
from functools import wraps

from bson import ObjectId
from flask import jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.extensions import db

logger = logging.getLogger(__name__)


def token_required(f):
    """
    Decorator that validates a JWT Bearer token and injects the `current_user`
    document into the wrapped function's first positional argument.

    Returns 401 if:
      - No / invalid token is provided
      - The token's user_id no longer exists in the database
    """
    @wraps(f)
    @jwt_required()  # flask_jwt_extended handles token parsing & signature verification
    def decorated(*args, **kwargs):
        user_id = get_jwt_identity()

        try:
            user = db.users.find_one(
                {"_id": ObjectId(user_id)},
                {"password_hash": 0},  # never return the hash
            )
        except Exception:
            return jsonify({"error": "Invalid token identity."}), 401

        if not user:
            return jsonify({"error": "User not found. Token may be stale."}), 401

        # Store on Flask's request-scoped g as well (useful for service functions)
        g.current_user = user

        return f(current_user=user, *args, **kwargs)

    return decorated


def optional_token(f):
    """
    Decorator for routes that work with or without authentication.
    Injects `current_user=None` when no token is present, otherwise injects
    the full user document.
    """
    @wraps(f)
    @jwt_required(optional=True)
    def decorated(*args, **kwargs):
        user_id = get_jwt_identity()
        current_user = None

        if user_id:
            try:
                current_user = db.users.find_one(
                    {"_id": ObjectId(user_id)},
                    {"password_hash": 0},
                )
            except Exception:
                pass

        g.current_user = current_user
        return f(current_user=current_user, *args, **kwargs)

    return decorated
