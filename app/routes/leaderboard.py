"""
app/routes/leaderboard.py — Leaderboard routes.

GET /leaderboard/global                — Top users globally by XP
GET /leaderboard/country/<country>     — Top users in a country
GET /leaderboard/local/<district>      — Top users in a district
"""

import logging
from flask import Blueprint, jsonify, request

from app.extensions import db
from app.utils.serializers import serialize_user
from app.utils.pagination import get_pagination_params, paginate_response

logger = logging.getLogger(__name__)
bp = Blueprint("leaderboard", __name__, url_prefix="/leaderboard")


def _build_leaderboard(query: dict, page: int, limit: int, skip: int):
    """
    Shared leaderboard query helper.
    Ranks users by XP descending, adds rank field.
    """
    total = db.users.count_documents(query)
    docs = list(
        db.users.find(
            query,
            # Project only essential fields — never send password_hash or full arrays
            {
                "username": 1, "profile_picture_base64": 1, "country": 1,
                "level": 1, "xp": 1, "badges": 1, "stats": 1,
            },
        )
        .sort("xp", -1)
        .skip(skip)
        .limit(limit)
    )

    # Inject display rank
    for i, doc in enumerate(docs):
        doc["rank"] = skip + i + 1

    return paginate_response(docs, total, page, limit, serialize_user)


# ── GET /leaderboard/global ────────────────────────────────────────────────────
@bp.get("/global")
def global_leaderboard():
    """Global leaderboard — top users by XP across all countries."""
    page, limit, skip = get_pagination_params(default_limit=50)
    result = _build_leaderboard({}, page, limit, skip)
    return jsonify(result), 200


# ── GET /leaderboard/country/<country> ────────────────────────────────────────
@bp.get("/country/<country>")
def country_leaderboard(country: str):
    """Country-filtered leaderboard."""
    page, limit, skip = get_pagination_params(default_limit=50)
    result = _build_leaderboard({"country": country}, page, limit, skip)
    return jsonify(result), 200


# ── GET /leaderboard/local/<district> ─────────────────────────────────────────
@bp.get("/local/<district>")
def local_leaderboard(district: str):
    """
    District-level leaderboard.
    Queries users who have made observations in the given district.
    """
    page, limit, skip = get_pagination_params(default_limit=50)

    # Find users who have observed in this district
    pipeline = [
        {"$match": {"district": district}},
        {"$group": {"_id": "$user_id", "obs_count": {"$sum": 1}}},
        {"$sort": {"obs_count": -1}},
    ]
    local_users = list(db.observations.aggregate(pipeline))
    user_ids = [u["_id"] for u in local_users]

    if not user_ids:
        return jsonify({"data": [], "pagination": {"total": 0}}), 200

    result = _build_leaderboard({"_id": {"$in": user_ids}}, page, limit, skip)
    return jsonify(result), 200
