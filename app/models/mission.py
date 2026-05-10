"""
app/models/mission.py — Mission and UserMissionProgress schema helpers.

MongoDB collections:
  - `missions`             — Mission definitions (seeded once)
  - `user_mission_progress` — Per-user progress tracking

Mission types: daily | weekly | exploration | rarity
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from bson import ObjectId


# ── Mission types & difficulty ─────────────────────────────────────────────────
MISSION_TYPES = {"daily", "weekly", "exploration", "rarity"}
DIFFICULTY_LEVELS = {"easy", "medium", "hard", "legendary"}


def new_mission(
    title: str,
    description: str,
    mission_type: str,
    difficulty: str,
    xp_reward: int,
    requirements: Dict[str, Any],
    badge_reward: Optional[str] = None,
    is_active: bool = True,
) -> Dict[str, Any]:
    """Factory — returns a mission definition document."""
    return {
        "title": title,
        "description": description,
        "type": mission_type,       # daily | weekly | exploration | rarity
        "difficulty": difficulty,   # easy | medium | hard | legendary
        "xp_reward": xp_reward,
        "badge_reward": badge_reward,   # badge slug or None
        "requirements": requirements,   # flexible dict, evaluated by mission_service
        "is_active": is_active,
        "created_at": datetime.now(timezone.utc),
    }


def new_user_mission_progress(
    user_id: ObjectId,
    mission_id: ObjectId,
) -> Dict[str, Any]:
    """Factory — returns a fresh progress tracking document."""
    return {
        "user_id": user_id,
        "mission_id": mission_id,
        "progress": 0,          # generic numeric progress counter
        "completed": False,
        "claimed": False,
        "started_at": datetime.now(timezone.utc),
        "completed_at": None,
        "claimed_at": None,
    }


# ── Index definitions ──────────────────────────────────────────────────────────
MISSION_INDEXES = [
    {"keys": [("type", 1), ("is_active", 1)], "name": "idx_mission_type_active"},
]

USER_MISSION_PROGRESS_INDEXES = [
    {
        "keys": [("user_id", 1), ("mission_id", 1)],
        "unique": True,
        "name": "idx_ump_user_mission",
    },
    {"keys": [("user_id", 1), ("completed", 1)], "name": "idx_ump_user_completed"},
]
