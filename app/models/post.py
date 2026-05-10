"""
app/models/post.py — Post and Comment schema helpers.

MongoDB collections:
  - `posts`    — Social posts (text + optional image + observation refs)
  - `comments` — Flat collection; parent_id supports one level of nesting
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from bson import ObjectId


def new_post(
    user_id: ObjectId,
    content: str,
    username: str = "",
    image_base64: str = "",
    referenced_observations: Optional[List[ObjectId]] = None,
    selected_species: str = "",
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> Dict[str, Any]:
    """Factory — returns a new post document."""
    return {
        "user_id": user_id,
        "username": username,
        "content": content,
        "image_base64": image_base64,
        "has_image": bool(image_base64),
        "selected_species": selected_species,
        "latitude": latitude,
        "longitude": longitude,
        "referenced_observations": referenced_observations or [],
        # Reactions stored as {emoji: [user_id, ...]}
        "reactions": {},
        # Simple likes stored as list of user ObjectIds
        "likes": [],
        "like_count": 0,
        "comment_count": 0,
        "created_at": datetime.now(timezone.utc),
        "updated_at": None,
        "is_deleted": False,
    }


def new_comment(
    post_id: ObjectId,
    user_id: ObjectId,
    content: str,
    parent_id: Optional[ObjectId] = None,
) -> Dict[str, Any]:
    """
    Factory — returns a new comment document.
    parent_id enables one level of reply threading.
    """
    return {
        "post_id": post_id,
        "user_id": user_id,
        "parent_id": parent_id,   # None = top-level comment
        "content": content[:1000],
        "likes": [],
        "created_at": datetime.now(timezone.utc),
        "is_deleted": False,
    }


# ── Index definitions ──────────────────────────────────────────────────────────
POST_INDEXES = [
    {"keys": [("user_id", 1), ("created_at", -1)], "name": "idx_post_user_time"},
    {"keys": [("created_at", -1)], "name": "idx_post_time"},
    {
        "keys": [("content", "text")],
        "name": "idx_post_text",
    },
]

COMMENT_INDEXES = [
    {"keys": [("post_id", 1), ("created_at", 1)], "name": "idx_comment_post_time"},
    {"keys": [("parent_id", 1)], "name": "idx_comment_parent"},
]
