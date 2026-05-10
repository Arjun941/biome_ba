"""
app/services/notification_service.py — Notification helpers.
"""

import logging
from typing import Optional
from bson import ObjectId
from app.extensions import db
from app.models.notification import new_notification

logger = logging.getLogger(__name__)


def notify(
    recipient_id: ObjectId,
    notif_type: str,
    message: str,
    actor_id: Optional[ObjectId] = None,
    ref_id: Optional[ObjectId] = None,
    ref_type: Optional[str] = None,
) -> None:
    """
    Insert a notification document for the recipient.
    Fire-and-forget; exceptions are logged but not re-raised.
    """
    try:
        doc = new_notification(
            recipient_id=recipient_id,
            notif_type=notif_type,
            message=message,
            actor_id=actor_id,
            ref_id=ref_id,
            ref_type=ref_type,
        )
        db.notifications.insert_one(doc)
    except Exception as exc:
        logger.error("Failed to create notification: %s", exc)


"""app/services/__init__.py"""
