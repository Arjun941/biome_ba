"""
app/models/user.py — User document schema helpers.

MongoDB collection: `users`

This module provides factory functions to create new user documents
and constants for the schema structure. PyMongo is used directly
(no ODM) so these are plain dicts that conform to the schema.
"""

from datetime import datetime, timezone
from typing import Dict, Any


def default_stats() -> Dict[str, int]:
    """Return a zeroed-out stats sub-document."""
    return {
        "total_observations": 0,
        "unique_species_found": 0,
        "rare_species_found": 0,
        "missions_completed": 0,
        "posts_created": 0,
        "followers_count": 0,
        "following_count": 0,
    }


def new_user(
    username: str,
    email: str,
    password_hash: str,
    bio: str = "",
    country: str = "",
    profile_picture_base64: str = "",
) -> Dict[str, Any]:
    """
    Factory function — returns a new user document ready for insertion.
    `_id` is omitted so MongoDB generates it automatically.
    """
    return {
        "username": username,
        "email": email,
        "password_hash": password_hash,
        "profile_picture_base64": profile_picture_base64,
        "bio": bio,
        "country": country,
        "created_at": datetime.now(timezone.utc),
        "level": 1,
        "xp": 0,
        "reputation": 0,
        "badges": [],
        "stats": default_stats(),
        # Social graph stored as arrays of ObjectIds for simplicity;
        # consider a separate `follows` collection for very large graphs.
        "following": [],
        "followers": [],
    }


# ── Index definitions (applied in create_app) ─────────────────────────────────
USER_INDEXES = [
    # Unique constraint on email and username
    {"keys": [("email", 1)], "unique": True, "name": "idx_email_unique"},
    {"keys": [("username", 1)], "unique": True, "name": "idx_username_unique"},
    # For leaderboard queries
    {"keys": [("xp", -1)], "name": "idx_xp_desc"},
    {"keys": [("country", 1), ("xp", -1)], "name": "idx_country_xp"},
    # Text search on username / bio
    {
        "keys": [("username", "text"), ("bio", "text")],
        "name": "idx_user_text",
        "weights": {"username": 10, "bio": 1},
    },
]
