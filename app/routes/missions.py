"""
app/routes/missions.py — Mission routes.

GET  /missions              — List all active missions with user progress
GET  /missions/progress     — Authenticated user's mission progress
POST /missions/claim        — Claim reward for a completed mission
"""

import logging
from bson import ObjectId
from flask import Blueprint, jsonify, request

from app.extensions import db
from app.middleware.auth_middleware import token_required
from app.services import mission_service
from app.utils.serializers import serialize_doc
from app.utils.pagination import get_pagination_params, paginate_response

logger = logging.getLogger(__name__)
bp = Blueprint("missions", __name__, url_prefix="/missions")


# ── GET /missions ──────────────────────────────────────────────────────────────
@bp.get("")
@token_required
def list_missions(current_user):
    """
    Return all active missions enriched with the user's current progress.

    Optional query param: type=daily|weekly|exploration|rarity
    """
    mission_type = request.args.get("type", "")
    query = {"is_active": True}
    if mission_type:
        query["type"] = mission_type

    missions = list(db.missions.find(query).sort("xp_reward", -1))

    # Batch-fetch progress for this user
    mission_ids = [m["_id"] for m in missions]
    progress_docs = {
        p["mission_id"]: p
        for p in db.user_mission_progress.find(
            {"user_id": current_user["_id"], "mission_id": {"$in": mission_ids}}
        )
    }

    result = []
    for m in missions:
        prog = progress_docs.get(m["_id"], {})
        entry = serialize_doc(m)
        entry["user_progress"] = {
            "progress": prog.get("progress", 0),
            "completed": prog.get("completed", False),
            "claimed": prog.get("claimed", False),
        }
        result.append(entry)

    return jsonify({"missions": result}), 200


# ── GET /missions/progress ─────────────────────────────────────────────────────
@bp.get("/progress")
@token_required
def my_progress(current_user):
    """Return the user's full mission progress records."""
    page, limit, skip = get_pagination_params()
    uid = current_user["_id"]

    total = db.user_mission_progress.count_documents({"user_id": uid})
    docs = list(
        db.user_mission_progress.find({"user_id": uid})
        .sort("completed", -1)
        .skip(skip)
        .limit(limit)
    )

    return jsonify(paginate_response(docs, total, page, limit, serialize_doc)), 200


# ── POST /missions/claim ───────────────────────────────────────────────────────
@bp.post("/claim")
@token_required
def claim_mission(current_user):
    """
    Claim the XP/badge reward for a completed mission.

    Request body (JSON):
      { "mission_id": "<ObjectId>" }
    """
    data = request.get_json(force=True, silent=True) or {}
    mission_id_str = data.get("mission_id", "")

    try:
        mission_id = ObjectId(mission_id_str)
    except Exception:
        return jsonify({"error": "Invalid mission_id."}), 400

    result = mission_service.claim_mission(current_user["_id"], mission_id)

    if not result.get("success"):
        return jsonify(result), 400

    return jsonify(result), 200
