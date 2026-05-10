"""
app/utils/serializers.py — MongoDB document serialisers.
Converts ObjectId and datetime fields to JSON-serialisable types.
"""

from bson import ObjectId
from datetime import datetime
from typing import Any, Dict


def _str(val: Any) -> Any:
    """Convert ObjectId → str, datetime → ISO string, pass everything else."""
    if isinstance(val, ObjectId):
        return str(val)
    if isinstance(val, datetime):
        return val.isoformat()
    return val


def serialize_doc(doc: Dict) -> Dict:
    """Recursively serialise a MongoDB document dict."""
    if doc is None:
        return {}
    out = {}
    for k, v in doc.items():
        if isinstance(v, dict):
            out[k] = serialize_doc(v)
        elif isinstance(v, list):
            out[k] = [serialize_doc(i) if isinstance(i, dict) else _str(i) for i in v]
        else:
            out[k] = _str(v)
    return out


def serialize_user(user: Dict) -> Dict:
    """Public user profile serialiser — strips sensitive fields."""
    user = serialize_doc(user)
    user.pop("password_hash", None)
    return user


def serialize_observation(obs: Dict) -> Dict:
    return serialize_doc(obs)


def serialize_post(post: Dict) -> Dict:
    return serialize_doc(post)
