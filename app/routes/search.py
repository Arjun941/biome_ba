"""
app/routes/search.py — Search routes.

GET /search/users?q=    — Search users by username
GET /search/species?q=  — Search species names
GET /search/posts?q=    — Search post content
"""

import logging
from flask import Blueprint, jsonify, request

from app.extensions import db
from app.utils.serializers import serialize_user, serialize_observation, serialize_post
from app.utils.pagination import get_pagination_params, paginate_response

logger = logging.getLogger(__name__)
bp = Blueprint("search", __name__, url_prefix="/search")


def _regex_query(field: str, term: str) -> dict:
    """Build a case-insensitive partial-match regex query."""
    return {field: {"$regex": term, "$options": "i"}}


# ── GET /search/users ──────────────────────────────────────────────────────────
@bp.get("/users")
def search_users():
    """
    Search users by username.

    Query params: q (required), page, limit
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Query parameter 'q' is required."}), 400
    if len(q) < 2:
        return jsonify({"error": "Query must be at least 2 characters."}), 400

    page, limit, skip = get_pagination_params()
    query = _regex_query("username", q)

    total = db.users.count_documents(query)
    docs = list(
        db.users.find(
            query,
            {"username": 1, "profile_picture_base64": 1, "bio": 1, "country": 1,
             "level": 1, "xp": 1, "badges": 1, "stats": 1},
        )
        .sort("xp", -1)
        .skip(skip)
        .limit(limit)
    )

    return jsonify(paginate_response(docs, total, page, limit, serialize_user)), 200


# ── GET /search/species ────────────────────────────────────────────────────────
@bp.get("/species")
def search_species():
    """
    Search observed species names across all observations.

    Returns distinct species matching the query with observation counts.
    Query params: q (required), page, limit
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Query parameter 'q' is required."}), 400

    page, limit, skip = get_pagination_params()

    # Aggregate distinct species matching the query
    pipeline = [
        {"$match": {"selected_species": {"$regex": q, "$options": "i"}}},
        {
            "$group": {
                "_id": "$selected_species",
                "observation_count": {"$sum": 1},
                "avg_rarity": {"$avg": "$rarity_score"},
                "countries": {"$addToSet": "$country"},
            }
        },
        {"$sort": {"observation_count": -1}},
        {"$skip": skip},
        {"$limit": limit},
    ]

    count_pipeline = [
        {"$match": {"selected_species": {"$regex": q, "$options": "i"}}},
        {"$group": {"_id": "$selected_species"}},
        {"$count": "total"},
    ]

    docs = list(db.observations.aggregate(pipeline))
    count_result = list(db.observations.aggregate(count_pipeline))
    total = count_result[0]["total"] if count_result else 0

    # Reshape for cleaner response
    items = [
        {
            "species": d["_id"],
            "observation_count": d["observation_count"],
            "avg_rarity_score": round(d.get("avg_rarity") or 0.0, 2),
            "countries": list(set(c for c in d.get("countries", []) if c)),
        }
        for d in docs
    ]

    return jsonify(paginate_response(items, total, page, limit)), 200


# ── GET /search/posts ──────────────────────────────────────────────────────────
@bp.get("/posts")
def search_posts():
    """
    Search post content.

    Query params: q (required), page, limit
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Query parameter 'q' is required."}), 400

    page, limit, skip = get_pagination_params()
    query = {**_regex_query("content", q), "is_deleted": False}

    total = db.posts.count_documents(query)
    docs = list(
        db.posts.find(query, {"image_base64": 0})
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )

    return jsonify(paginate_response(docs, total, page, limit, serialize_post)), 200
