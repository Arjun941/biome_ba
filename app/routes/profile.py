"""
app/routes/profile.py — User profile routes.

GET /profile/<user_id>   — Public profile (stats, recent obs, recent posts)
PUT /profile/edit        — Edit own profile (protected)
GET /profile/me/follow/<target_id> — Follow/unfollow a user (protected)
GET /profile/notifications — User notifications (protected)
"""

import logging
from bson import ObjectId
from flask import Blueprint, jsonify, request

from app.extensions import db
from app.middleware.auth_middleware import token_required
from app.utils.serializers import serialize_user, serialize_observation, serialize_post
from app.utils.pagination import get_pagination_params, paginate_response
from app.services.notification_service import notify

logger = logging.getLogger(__name__)
bp = Blueprint("profile", __name__, url_prefix="/profile")


def _user_rank(user_id: ObjectId) -> int:
    """Return global rank of user by XP (1-indexed)."""
    user = db.users.find_one({"_id": user_id}, {"xp": 1})
    if not user:
        return 0
    rank = db.users.count_documents({"xp": {"$gt": user.get("xp", 0)}}) + 1
    return rank


# ── GET /profile/<user_id> ─────────────────────────────────────────────────────
@bp.get("/<user_id>")
def get_profile(user_id: str):
    """
    Public profile endpoint.
    Returns user fields, stats, rarity_score, global rank,
    5 most recent observations, 5 most recent posts.
    """
    try:
        uid = ObjectId(user_id)
    except Exception:
        return jsonify({"error": "Invalid user ID."}), 400

    user = db.users.find_one({"_id": uid}, {"password_hash": 0})
    if not user:
        return jsonify({"error": "User not found."}), 404

    # Recent observations
    recent_obs = list(
        db.observations.find({"user_id": uid}, {"image_base64": 0})
        .sort("timestamp", -1)
        .limit(5)
    )

    # Recent posts
    recent_posts = list(
        db.posts.find({"user_id": uid, "is_deleted": False}, {"image_base64": 0})
        .sort("created_at", -1)
        .limit(5)
    )

    # Rarity score = average rarity of all observations
    pipeline = [
        {"$match": {"user_id": uid}},
        {"$group": {"_id": None, "avg_rarity": {"$avg": "$rarity_score"}}},
    ]
    rarity_result = list(db.observations.aggregate(pipeline))
    avg_rarity = round(rarity_result[0]["avg_rarity"], 2) if rarity_result else 0.0

    return jsonify({
        "user": serialize_user(user),
        "rank": _user_rank(uid),
        "rarity_score": avg_rarity,
        "recent_observations": [serialize_observation(o) for o in recent_obs],
        "recent_posts": [serialize_post(p) for p in recent_posts],
    }), 200


# ── PUT /profile/edit ──────────────────────────────────────────────────────────
@bp.put("/edit")
@token_required
def edit_profile(current_user):
    """
    Edit the authenticated user's profile.
    Allowed fields: bio, country, profile_picture_base64.
    """
    data = request.get_json(force=True, silent=True) or {}
    allowed = ("bio", "country", "profile_picture_base64")
    update_fields = {}

    for field in allowed:
        if field in data:
            val = str(data[field])
            if field == "bio" and len(val) > 300:
                return jsonify({"error": "Bio must be 300 characters or fewer."}), 400
            update_fields[field] = val

    if not update_fields:
        return jsonify({"error": "No updatable fields provided."}), 400

    db.users.update_one({"_id": current_user["_id"]}, {"$set": update_fields})
    updated = db.users.find_one({"_id": current_user["_id"]}, {"password_hash": 0})
    return jsonify({"message": "Profile updated.", "user": serialize_user(updated)}), 200


# ── POST /profile/follow/<target_id> ──────────────────────────────────────────
@bp.post("/follow/<target_id>")
@token_required
def follow_user(current_user, target_id: str):
    """Toggle follow/unfollow. Returns new follow state."""
    try:
        tid = ObjectId(target_id)
    except Exception:
        return jsonify({"error": "Invalid user ID."}), 400

    if tid == current_user["_id"]:
        return jsonify({"error": "You cannot follow yourself."}), 400

    target = db.users.find_one({"_id": tid})
    if not target:
        return jsonify({"error": "User not found."}), 404

    already_following = tid in current_user.get("following", [])

    if already_following:
        # Unfollow
        db.users.update_one({"_id": current_user["_id"]}, {"$pull": {"following": tid}, "$inc": {"stats.following_count": -1}})
        db.users.update_one({"_id": tid}, {"$pull": {"followers": current_user["_id"]}, "$inc": {"stats.followers_count": -1}})
        return jsonify({"following": False, "message": f"Unfollowed {target['username']}."}), 200
    else:
        # Follow
        db.users.update_one({"_id": current_user["_id"]}, {"$addToSet": {"following": tid}, "$inc": {"stats.following_count": 1}})
        db.users.update_one({"_id": tid}, {"$addToSet": {"followers": current_user["_id"]}, "$inc": {"stats.followers_count": 1}})
        notify(
            recipient_id=tid,
            notif_type="follow",
            message=f"{current_user['username']} started following you.",
            actor_id=current_user["_id"],
        )
        return jsonify({"following": True, "message": f"Now following {target['username']}."}), 200


# ── GET /profile/notifications ─────────────────────────────────────────────────
@bp.get("/notifications")
@token_required
def get_notifications(current_user):
    """Return paginated notifications for the authenticated user."""
    page, limit, skip = get_pagination_params()
    uid = current_user["_id"]

    total = db.notifications.count_documents({"recipient_id": uid})
    docs = list(
        db.notifications.find({"recipient_id": uid})
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )

    # Mark fetched notifications as read
    ids = [d["_id"] for d in docs]
    if ids:
        db.notifications.update_many({"_id": {"$in": ids}}, {"$set": {"read": True}})

    from app.utils.serializers import serialize_doc
    return jsonify(paginate_response(docs, total, page, limit, serialize_doc)), 200
