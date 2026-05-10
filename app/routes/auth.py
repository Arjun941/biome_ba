"""
app/routes/auth.py — Authentication routes.

POST /auth/register  — Create a new user account
POST /auth/login     — Verify credentials and return JWT
GET  /auth/me        — Return current authenticated user (protected)
POST /auth/refresh   — Refresh an access token
"""

import logging
from datetime import datetime, timezone

import bcrypt
from bson import ObjectId
from flask import Blueprint, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
)

from app.extensions import db, limiter
from app.middleware.auth_middleware import token_required
from app.models.user import new_user
from app.utils.validators import validate_register_payload
from app.utils.serializers import serialize_user

logger = logging.getLogger(__name__)
bp = Blueprint("auth", __name__, url_prefix="/auth")


# ── POST /auth/register ────────────────────────────────────────────────────────
@bp.post("/register")
@limiter.limit("20 per hour")
def register():
    """
    Register a new user.

    Request body (JSON):
      username, email, password, bio?, country?, profile_picture_base64?

    Response 201:
      { user: {...}, access_token: "...", refresh_token: "..." }
    """
    data = request.get_json(force=True, silent=True) or {}

    try:
        validated = validate_register_payload(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Check uniqueness
    if db.users.find_one({"email": validated["email"]}):
        return jsonify({"error": "An account with this email already exists."}), 409
    if db.users.find_one({"username": validated["username"]}):
        return jsonify({"error": "Username is already taken."}), 409

    # Hash password with bcrypt (work factor 12)
    pw_hash = bcrypt.hashpw(
        validated["password"].encode("utf-8"), bcrypt.gensalt(rounds=12)
    ).decode("utf-8")

    doc = new_user(
        username=validated["username"],
        email=validated["email"],
        password_hash=pw_hash,
        bio=validated.get("bio", ""),
        country=validated.get("country", ""),
        profile_picture_base64=data.get("profile_picture_base64", ""),
    )

    result = db.users.insert_one(doc)
    doc["_id"] = result.inserted_id

    user_id_str = str(result.inserted_id)
    access_token = create_access_token(identity=user_id_str)
    refresh_token = create_refresh_token(identity=user_id_str)

    logger.info("New user registered: %s (%s)", validated["username"], validated["email"])

    return jsonify({
        "message": "Account created successfully.",
        "user": serialize_user(doc),
        "access_token": access_token,
        "refresh_token": refresh_token,
    }), 201


# ── POST /auth/login ───────────────────────────────────────────────────────────
@bp.post("/login")
@limiter.limit("30 per hour")
def login():
    """
    Authenticate and return JWT tokens.

    Request body (JSON):
      email, password

    Response 200:
      { user: {...}, access_token: "...", refresh_token: "..." }
    """
    data = request.get_json(force=True, silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not email or not password:
        return jsonify({"error": "email and password are required."}), 400

    user = db.users.find_one({"email": email})
    if not user:
        return jsonify({"error": "Invalid credentials."}), 401

    if not bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        return jsonify({"error": "Invalid credentials."}), 401

    user_id_str = str(user["_id"])
    access_token = create_access_token(identity=user_id_str)
    refresh_token = create_refresh_token(identity=user_id_str)

    logger.info("User logged in: %s", email)

    return jsonify({
        "message": "Login successful.",
        "user": serialize_user(user),
        "access_token": access_token,
        "refresh_token": refresh_token,
    }), 200


# ── GET /auth/me ───────────────────────────────────────────────────────────────
@bp.get("/me")
@token_required
def me(current_user):
    """Return the authenticated user's profile."""
    return jsonify({"user": serialize_user(current_user)}), 200


# ── POST /auth/refresh ─────────────────────────────────────────────────────────
@bp.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    """Issue a new access token using a valid refresh token."""
    user_id = get_jwt_identity()
    access_token = create_access_token(identity=user_id)
    return jsonify({"access_token": access_token}), 200
