"""
app/models/notification.py — Notification schema helpers.

MongoDB collection: `notifications`
Notification types: like | comment | follow | badge | mission_complete | observation_verified
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
from bson import ObjectId


NOTIFICATION_TYPES = {
    "like",
    "comment",
    "follow",
    "badge",
    "mission_complete",
    "observation_verified",
    "level_up",
}


def new_notification(
    recipient_id: ObjectId,
    notif_type: str,
    message: str,
    actor_id: Optional[ObjectId] = None,
    ref_id: Optional[ObjectId] = None,   # reference to post / observation / mission
    ref_type: Optional[str] = None,      # "post" | "observation" | "mission"
) -> Dict[str, Any]:
    """Factory — returns a notification document ready for insertion."""
    return {
        "recipient_id": recipient_id,
        "actor_id": actor_id,
        "type": notif_type,
        "message": message,
        "ref_id": ref_id,
        "ref_type": ref_type,
        "read": False,
        "created_at": datetime.now(timezone.utc),
    }


NOTIFICATION_INDEXES = [
    {
        "keys": [("recipient_id", 1), ("read", 1), ("created_at", -1)],
        "name": "idx_notif_recipient",
    },
]
