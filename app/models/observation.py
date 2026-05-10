"""
app/models/observation.py — Observation document schema helpers.

MongoDB collection: `observations`
Key feature: GeoJSON `location` field for 2dsphere geospatial queries.
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from bson import ObjectId
from app.utils.geo import make_point


def new_observation(
    user_id: ObjectId,
    selected_species: str,
    image_base64: str,
    latitude: float,
    longitude: float,
    ai_predictions: List[Dict],
    rarity_score: float = 0.0,
    rarity_tier: str = "Common",
    habitat_tags: Optional[List[str]] = None,
    country: str = "",
    state: str = "",
    district: str = "",
    weather_data: Optional[Dict] = None,
    verification_status: str = "pending",
) -> Dict[str, Any]:
    """Factory — returns a new observation document ready for insertion."""
    return {
        "user_id": user_id,
        "selected_species": selected_species,
        # Store top-5 AI predictions alongside the user's selection
        "ai_predictions": ai_predictions,
        "image_base64": image_base64,
        # GeoJSON Point — required for $nearSphere / $geoWithin queries
        "location": make_point(longitude, latitude),
        # Also store flat lat/lng for simple range queries without geospatial index
        "geolocation": {"latitude": latitude, "longitude": longitude},
        "timestamp": datetime.now(timezone.utc),
        "rarity_score": rarity_score,
        "rarity_tier": rarity_tier,
        "comments": [],       # list of Comment ObjectIds
        "likes": [],          # list of User ObjectIds
        "verification_status": verification_status,   # pending | verified | rejected
        "habitat_tags": habitat_tags or [],
        "weather_data": weather_data or {},
        "country": country,
        "state": state,
        "district": district,
    }


# ── Index definitions ──────────────────────────────────────────────────────────
OBSERVATION_INDEXES = [
    # 2dsphere index — REQUIRED for $nearSphere geospatial queries
    {"keys": [("location", "2dsphere")], "name": "idx_location_2dsphere"},
    # Species lookup
    {"keys": [("selected_species", 1)], "name": "idx_species"},
    # User's own observations
    {"keys": [("user_id", 1), ("timestamp", -1)], "name": "idx_user_timestamp"},
    # Rarity leaderboard
    {"keys": [("rarity_score", -1)], "name": "idx_rarity_score"},
    # Regional queries
    {"keys": [("country", 1), ("state", 1), ("district", 1)], "name": "idx_region"},
    # Text search
    {
        "keys": [("selected_species", "text")],
        "name": "idx_obs_text",
    },
]
