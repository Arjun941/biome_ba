"""
app/services/mission_service.py — Mission evaluation and claim logic.

Requirements format (stored on mission document):
  {
    "type": "observation_count",   # handler key
    "species_group": "bird",       # optional filter
    "count": 3,                    # target value
  }

Supported requirement types:
  observation_count   — Total observations (optionally filtered by species/tag)
  unique_species      — Unique species observed
  rare_discovery      — Rare+ observations made
  new_district        — Observation in a district not previously visited
  upload_count        — Same as observation_count (alias)
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from bson import ObjectId
from app.extensions import db
from app.services import xp_service
from app.services.notification_service import notify

logger = logging.getLogger(__name__)


def _eval_requirement(user_id: ObjectId, req: Dict) -> tuple[int, int]:
    """
    Evaluate a single mission requirement for a user.
    Returns (current_progress, target).
    """
    req_type = req.get("type", "")
    target = int(req.get("count", 1))

    if req_type in ("observation_count", "upload_count"):
        query = {"user_id": user_id}
        if req.get("species_group"):
            query["habitat_tags"] = req["species_group"]
        current = db.observations.count_documents(query)

    elif req_type == "unique_species":
        result = list(db.observations.aggregate([
            {"$match": {"user_id": user_id}},
            {"$group": {"_id": "$selected_species"}},
            {"$count": "total"},
        ]))
        current = result[0]["total"] if result else 0

    elif req_type == "rare_discovery":
        current = db.observations.count_documents(
            {"user_id": user_id, "rarity_score": {"$gte": 41}}
        )

    elif req_type == "new_district":
        # Count distinct districts this user has observed in
        result = list(db.observations.aggregate([
            {"$match": {"user_id": user_id, "district": {"$ne": ""}}},
            {"$group": {"_id": "$district"}},
            {"$count": "total"},
        ]))
        current = result[0]["total"] if result else 0

    else:
        logger.warning("Unknown mission requirement type: %s", req_type)
        current = 0

    return current, target


def get_user_progress(user_id: ObjectId, mission_id: ObjectId) -> Dict:
    """
    Return the current progress dict for a user/mission pair.
    Creates a fresh record if none exists.
    """
    from app.models.mission import new_user_mission_progress

    prog = db.user_mission_progress.find_one(
        {"user_id": user_id, "mission_id": mission_id}
    )
    if not prog:
        doc = new_user_mission_progress(user_id, mission_id)
        db.user_mission_progress.insert_one(doc)
        prog = db.user_mission_progress.find_one(
            {"user_id": user_id, "mission_id": mission_id}
        )
    return prog


def refresh_progress(user_id: ObjectId) -> None:
    """
    Re-evaluate all active, unclaimed missions for a user and update their progress.
    Called after each observation or post creation.
    """
    missions = list(db.missions.find({"is_active": True}))
    for mission in missions:
        req = mission.get("requirements", {})
        current, target = _eval_requirement(user_id, req)
        completed = current >= target

        db.user_mission_progress.update_one(
            {"user_id": user_id, "mission_id": mission["_id"]},
            {
                "$set": {
                    "progress": current,
                    "completed": completed,
                    "completed_at": datetime.now(timezone.utc) if completed else None,
                }
            },
            upsert=True,
        )


def claim_mission(user_id: ObjectId, mission_id: ObjectId) -> Dict[str, Any]:
    """
    Claim the XP reward for a completed mission.

    Returns:
        {"success": bool, "message": str, "xp_awarded": int, "badge": str|None}
    """
    prog = db.user_mission_progress.find_one(
        {"user_id": user_id, "mission_id": mission_id}
    )
    if not prog:
        # Re-evaluate first
        mission = db.missions.find_one({"_id": mission_id})
        if not mission:
            return {"success": False, "message": "Mission not found."}
        current, target = _eval_requirement(user_id, mission.get("requirements", {}))
        if current < target:
            return {"success": False, "message": "Mission not yet completed.", "progress": current, "target": target}
        # Mark as completed
        db.user_mission_progress.update_one(
            {"user_id": user_id, "mission_id": mission_id},
            {"$set": {"completed": True, "completed_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        prog = db.user_mission_progress.find_one({"user_id": user_id, "mission_id": mission_id})

    if not prog.get("completed"):
        return {"success": False, "message": "Mission not yet completed."}
    if prog.get("claimed"):
        return {"success": False, "message": "Mission reward already claimed."}

    # Fetch mission details
    mission = db.missions.find_one({"_id": mission_id})
    if not mission:
        return {"success": False, "message": "Mission not found."}

    xp_reward = mission.get("xp_reward", 0)
    badge_reward = mission.get("badge_reward")

    # Award XP
    xp_result = xp_service.award_xp(user_id, "observation", custom_xp=xp_reward)

    # Award badge if applicable
    if badge_reward:
        db.users.update_one(
            {"_id": user_id},
            {"$addToSet": {"badges": badge_reward}},
        )

    # Increment missions_completed stat
    db.users.update_one(
        {"_id": user_id},
        {"$inc": {"stats.missions_completed": 1}},
    )

    # Mark as claimed
    db.user_mission_progress.update_one(
        {"user_id": user_id, "mission_id": mission_id},
        {"$set": {"claimed": True, "claimed_at": datetime.now(timezone.utc)}},
    )

    # Send notification
    notify(
        recipient_id=user_id,
        notif_type="mission_complete",
        message=f"Mission '{mission['title']}' completed! +{xp_reward} XP",
        ref_id=mission_id,
        ref_type="mission",
    )

    logger.info("User %s claimed mission %s (+%d XP)", user_id, mission_id, xp_reward)

    return {
        "success": True,
        "message": f"Reward claimed: +{xp_reward} XP",
        "xp_awarded": xp_reward,
        "badge": badge_reward,
        "level_up": xp_result.get("level_up", False),
        "new_level": xp_result.get("new_level"),
    }
