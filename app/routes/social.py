"""
app/routes/social.py — Social media routes.

POST   /posts                  — Create a post
GET    /posts/feed             — Paginated feed (following + global)
GET    /posts/<id>             — Single post with comments
POST   /posts/<id>/comment     — Add a comment
POST   /posts/<id>/react       — Add an emoji reaction
POST   /posts/<id>/like        — Toggle like
DELETE /posts/<id>             — Soft-delete own post
"""

import logging
from datetime import datetime, timezone

from bson import ObjectId
from flask import Blueprint, jsonify, request

from app.extensions import db
from app.middleware.auth_middleware import token_required, optional_token
from app.models.post import new_post, new_comment
from app.services.notification_service import notify
from app.services import xp_service, mission_service
from app.utils.serializers import serialize_post, serialize_doc
from app.utils.pagination import get_pagination_params, paginate_response
from app.utils.validators import validate_post_payload

logger = logging.getLogger(__name__)
bp = Blueprint("social", __name__, url_prefix="/posts")


# ── POST /posts ────────────────────────────────────────────────────────────────
@bp.post("")
@token_required
def create_post(current_user):
    """
    Create a new post.

    Request body (JSON):
      { content?, image_base64?, referenced_observations?: [id, ...] }
    """
    data = request.get_json(force=True, silent=True) or {}

    try:
        validated = validate_post_payload(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Resolve referenced observation IDs
    ref_obs = []
    for oid_str in validated.get("referenced_observations", []):
        try:
            ref_obs.append(ObjectId(oid_str))
        except Exception:
            pass

    doc = new_post(
        user_id=current_user["_id"],
        username=current_user.get("username", ""),
        content=validated["content"],
        image_base64=validated.get("image_base64", ""),
        referenced_observations=ref_obs,
        selected_species=validated.get("selected_species", ""),
        latitude=validated.get("latitude"),
        longitude=validated.get("longitude"),
    )

    result = db.posts.insert_one(doc)
    doc["_id"] = result.inserted_id

    # Update stats
    db.users.update_one({"_id": current_user["_id"]}, {"$inc": {"stats.posts_created": 1}})

    # Award XP
    xp_service.award_xp(current_user["_id"], "post")

    # Refresh mission progress
    mission_service.refresh_progress(current_user["_id"])

    return jsonify({
        "message": "Post created.",
        "post": serialize_post(doc),
    }), 201


# ── GET /posts/feed ────────────────────────────────────────────────────────────
@bp.get("/feed")
@optional_token
def get_feed(current_user):
    """
    Return a paginated post feed.
    - If authenticated: posts from followed users + own posts (chronological).
    - If anonymous: global feed (most recent posts).
    """
    page, limit, skip = get_pagination_params(default_limit=20)

    # Default to global feed; pass ?following_only=true for personalised feed
    following_only = request.args.get("following_only", "false").lower() == "true"
    if current_user and following_only:
        following_ids = list(current_user.get("following", []))
        following_ids.append(current_user["_id"])
        query = {"user_id": {"$in": following_ids}, "is_deleted": False}
    else:
        query = {"is_deleted": False}

    total = db.posts.count_documents(query)
    docs = list(
        db.posts.find(query)
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )

    return jsonify(paginate_response(docs, total, page, limit, serialize_post)), 200


# ── GET /posts/map ────────────────────────────────────────────────────────────
@bp.get("/map")
def get_map_posts():
    """Return posts that have a location, for map display. No images included."""
    limit = min(int(request.args.get("limit", 300)), 500)
    docs = list(db.posts.find(
        {"latitude": {"$exists": True, "$ne": None}, "is_deleted": False},
        {
            "_id": 1, "username": 1, "content": 1, "selected_species": 1,
            "latitude": 1, "longitude": 1, "has_image": 1,
            "created_at": 1, "like_count": 1,
        },
    ).sort("created_at", -1).limit(limit))
    return jsonify({"posts": [serialize_post(doc) for doc in docs]}), 200


# ── GET /posts/<id> ────────────────────────────────────────────────────────────
@bp.get("/<post_id>")
def get_post(post_id: str):
    """Get a single post with its top-level comments."""
    try:
        pid = ObjectId(post_id)
    except Exception:
        return jsonify({"error": "Invalid post ID."}), 400

    post = db.posts.find_one({"_id": pid, "is_deleted": False})
    if not post:
        return jsonify({"error": "Post not found."}), 404

    # Fetch top-level comments (no parent_id)
    comments = list(
        db.comments.find({"post_id": pid, "parent_id": None, "is_deleted": False})
        .sort("created_at", 1)
        .limit(50)
    )

    return jsonify({
        "post": serialize_post(post),
        "comments": [serialize_doc(c) for c in comments],
    }), 200


# ── POST /posts/<id>/comment ───────────────────────────────────────────────────
@bp.post("/<post_id>/comment")
@token_required
def add_comment(current_user, post_id: str):
    """
    Add a comment to a post.

    Request body (JSON):
      { "content": "...", "parent_id"?: "<comment ObjectId>" }
    """
    try:
        pid = ObjectId(post_id)
    except Exception:
        return jsonify({"error": "Invalid post ID."}), 400

    post = db.posts.find_one({"_id": pid, "is_deleted": False}, {"user_id": 1})
    if not post:
        return jsonify({"error": "Post not found."}), 404

    data = request.get_json(force=True, silent=True) or {}
    content = str(data.get("content", "")).strip()
    if not content:
        return jsonify({"error": "Comment content is required."}), 400
    if len(content) > 1000:
        return jsonify({"error": "Comment must be 1000 characters or fewer."}), 400

    parent_id = None
    if data.get("parent_id"):
        try:
            parent_id = ObjectId(data["parent_id"])
        except Exception:
            return jsonify({"error": "Invalid parent_id."}), 400

    doc = new_comment(
        post_id=pid,
        user_id=current_user["_id"],
        content=content,
        parent_id=parent_id,
    )
    result = db.comments.insert_one(doc)
    doc["_id"] = result.inserted_id

    # Increment comment count
    db.posts.update_one({"_id": pid}, {"$inc": {"comment_count": 1}})

    # Notify post author (if not the commenter)
    if post["user_id"] != current_user["_id"]:
        notify(
            recipient_id=post["user_id"],
            notif_type="comment",
            message=f"{current_user['username']} commented on your post.",
            actor_id=current_user["_id"],
            ref_id=pid,
            ref_type="post",
        )

    return jsonify({"message": "Comment added.", "comment": serialize_doc(doc)}), 201


# ── POST /posts/<id>/react ─────────────────────────────────────────────────────
@bp.post("/<post_id>/react")
@token_required
def react(current_user, post_id: str):
    """
    Add or toggle an emoji reaction.

    Request body (JSON):
      { "emoji": "🔥" }
    """
    try:
        pid = ObjectId(post_id)
    except Exception:
        return jsonify({"error": "Invalid post ID."}), 400

    data = request.get_json(force=True, silent=True) or {}
    emoji = str(data.get("emoji", "")).strip()
    if not emoji:
        return jsonify({"error": "emoji is required."}), 400

    post = db.posts.find_one({"_id": pid}, {"reactions": 1, "user_id": 1})
    if not post:
        return jsonify({"error": "Post not found."}), 404

    uid = current_user["_id"]
    reactions = post.get("reactions", {})
    current_reactors = reactions.get(emoji, [])

    if uid in current_reactors:
        # Remove reaction
        db.posts.update_one({"_id": pid}, {"$pull": {f"reactions.{emoji}": uid}})
        return jsonify({"reacted": False, "emoji": emoji}), 200
    else:
        # Add reaction
        db.posts.update_one({"_id": pid}, {"$addToSet": {f"reactions.{emoji}": uid}})
        return jsonify({"reacted": True, "emoji": emoji}), 200


# ── POST /posts/<id>/like ──────────────────────────────────────────────────────
@bp.post("/<post_id>/like")
@token_required
def like_post(current_user, post_id: str):
    """Toggle a like on a post."""
    try:
        pid = ObjectId(post_id)
    except Exception:
        return jsonify({"error": "Invalid post ID."}), 400

    post = db.posts.find_one({"_id": pid}, {"likes": 1, "user_id": 1})
    if not post:
        return jsonify({"error": "Post not found."}), 404

    uid = current_user["_id"]
    liked = uid in post.get("likes", [])

    if liked:
        db.posts.update_one({"_id": pid}, {"$pull": {"likes": uid}, "$inc": {"like_count": -1}})
        return jsonify({"liked": False}), 200
    else:
        db.posts.update_one({"_id": pid}, {"$addToSet": {"likes": uid}, "$inc": {"like_count": 1}})
        if post["user_id"] != uid:
            notify(
                recipient_id=post["user_id"],
                notif_type="like",
                message=f"{current_user['username']} liked your post.",
                actor_id=uid,
                ref_id=pid,
                ref_type="post",
            )
        return jsonify({"liked": True}), 200


# ── DELETE /posts/<id> ─────────────────────────────────────────────────────────
@bp.delete("/<post_id>")
@token_required
def delete_post(current_user, post_id: str):
    """Soft-delete the authenticated user's own post."""
    try:
        pid = ObjectId(post_id)
    except Exception:
        return jsonify({"error": "Invalid post ID."}), 400

    post = db.posts.find_one({"_id": pid}, {"user_id": 1})
    if not post:
        return jsonify({"error": "Post not found."}), 404
    if post["user_id"] != current_user["_id"]:
        return jsonify({"error": "You can only delete your own posts."}), 403

    db.posts.update_one(
        {"_id": pid},
        {"$set": {"is_deleted": True, "updated_at": datetime.now(timezone.utc)}},
    )
    return jsonify({"message": "Post deleted."}), 200
