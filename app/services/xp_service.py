"""
app/services/xp_service.py — XP, levelling, and badge award logic.

XP awarded per action:
  - New observation:        +10 XP
  - Rare observation:       +25 XP  (score > 60)
  - Epic observation:       +50 XP  (score > 80)
  - Post created:           +5  XP
  - Mission completed:      variable (defined on mission)
  - Observation verified:   +15 XP

Level thresholds use a simple quadratic formula:
  XP needed for level N = 100 * N^1.5
"""

import logging
import math
from typing import Dict, Any, List, Optional

from bson import ObjectId
from app.extensions import db

logger = logging.getLogger(__name__)


# ── XP award amounts ───────────────────────────────────────────────────────────
XP_AWARDS = {
    "observation":          10,
    "observation_uncommon": 15,
    "observation_rare":     25,
    "observation_epic":     40,
    "observation_legendary":60,
    "post":                  5,
    "observation_verified":  15,
    "daily_login":           3,
}

# ── Badge definitions ──────────────────────────────────────────────────────────
BADGES = {
    "first_observation":   {"name": "First Steps",     "icon": "🌱"},
    "10_observations":     {"name": "Field Naturalist", "icon": "🔭"},
    "50_observations":     {"name": "Species Hunter",   "icon": "🦁"},
    "first_rare":          {"name": "Rarity Seeker",    "icon": "💎"},
    "first_legendary":     {"name": "Legendary Scout",  "icon": "⭐"},
    "mission_master":      {"name": "Mission Master",   "icon": "🏆"},
    "social_butterfly":    {"name": "Social Butterfly", "icon": "🦋"},
}


def xp_for_level(level: int) -> int:
    """Total XP required to reach `level` from level 1."""
    return int(100 * (level ** 1.5))


def level_for_xp(xp: int) -> int:
    """Return the level a user should be at given total `xp`."""
    level = 1
    while xp_for_level(level + 1) <= xp:
        level += 1
    return level


def award_xp(
    user_id: ObjectId,
    action: str,
    custom_xp: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Award XP to a user, recalculate their level, and check for new badges.

    Args:
        user_id:   ObjectId of the user receiving XP.
        action:    Key into XP_AWARDS (e.g. "observation_rare").
        custom_xp: Override the XP amount (used for mission rewards).

    Returns:
        {
            "xp_awarded": int,
            "new_xp": int,
            "old_level": int,
            "new_level": int,
            "level_up": bool,
            "new_badges": [str],
        }
    """
    xp_amount = custom_xp if custom_xp is not None else XP_AWARDS.get(action, 0)
    if xp_amount == 0:
        logger.warning("Unknown XP action: %s", action)

    user = db.users.find_one({"_id": user_id}, {"xp": 1, "level": 1, "stats": 1, "badges": 1})
    if not user:
        return {}

    old_xp = user.get("xp", 0)
    old_level = user.get("level", 1)
    new_xp = old_xp + xp_amount
    new_level = level_for_xp(new_xp)
    level_up = new_level > old_level

    # Check which badges should be awarded
    stats = user.get("stats", {})
    existing_badges = set(user.get("badges", []))
    new_badges = _check_badges(stats, existing_badges)

    update = {
        "$inc": {"xp": xp_amount},
        "$set": {"level": new_level},
    }
    if new_badges:
        update["$addToSet"] = {"badges": {"$each": new_badges}}

    db.users.update_one({"_id": user_id}, update)

    logger.info("User %s awarded %d XP (%s). Level: %d→%d", user_id, xp_amount, action, old_level, new_level)

    return {
        "xp_awarded": xp_amount,
        "new_xp": new_xp,
        "old_level": old_level,
        "new_level": new_level,
        "level_up": level_up,
        "new_badges": list(new_badges),
    }


def _check_badges(stats: Dict, existing: set) -> List[str]:
    """Return list of badge slugs the user has earned but not yet received."""
    earned = []
    obs = stats.get("total_observations", 0)

    if obs >= 1 and "first_observation" not in existing:
        earned.append("first_observation")
    if obs >= 10 and "10_observations" not in existing:
        earned.append("10_observations")
    if obs >= 50 and "50_observations" not in existing:
        earned.append("50_observations")
    if stats.get("rare_species_found", 0) >= 1 and "first_rare" not in existing:
        earned.append("first_rare")
    if stats.get("missions_completed", 0) >= 5 and "mission_master" not in existing:
        earned.append("mission_master")
    if stats.get("posts_created", 0) >= 10 and "social_butterfly" not in existing:
        earned.append("social_butterfly")
    return earned
