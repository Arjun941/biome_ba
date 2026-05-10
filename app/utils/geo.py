"""
app/utils/geo.py — Geospatial helper utilities.
"""

from typing import Dict, Any


def make_point(longitude: float, latitude: float) -> Dict[str, Any]:
    """
    Create a GeoJSON Point document for MongoDB 2dsphere indexing.
    MongoDB expects [longitude, latitude] order.
    """
    return {
        "type": "Point",
        "coordinates": [longitude, latitude],
    }


def km_to_meters(km: float) -> float:
    """Convert kilometres to metres (used by $geoWithin / $nearSphere)."""
    return km * 1000.0


def build_near_query(
    longitude: float,
    latitude: float,
    radius_km: float,
    min_km: float = 0.0,
) -> Dict[str, Any]:
    """
    Build a MongoDB $nearSphere query for nearby observations.

    Example usage:
        filter_doc = {"location": build_near_query(77.5, 12.9, 50)}
        cursor = db.observations.find(filter_doc)

    Notes:
        - Requires a 2dsphere index on the `location` field.
        - $nearSphere returns results sorted by distance (nearest first).
    """
    return {
        "$nearSphere": {
            "$geometry": make_point(longitude, latitude),
            "$maxDistance": km_to_meters(radius_km),
            "$minDistance": km_to_meters(min_km),
        }
    }
