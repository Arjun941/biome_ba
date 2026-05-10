"""
app/utils/validators.py — Input validation helpers.
All validators raise ValueError on failure so routes can handle them uniformly.
"""

import re
from typing import Any, Dict, List, Optional


# ── Field validators ──────────────────────────────────────────────────────────

def validate_email(email: str) -> str:
    """Return normalised email or raise ValueError."""
    email = email.strip().lower()
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    if not re.match(pattern, email):
        raise ValueError(f"Invalid email address: {email}")
    return email


def validate_username(username: str) -> str:
    """
    Username rules:
      - 3–30 characters
      - Only letters, numbers, underscores, hyphens
    """
    username = username.strip()
    if not 3 <= len(username) <= 30:
        raise ValueError("Username must be between 3 and 30 characters.")
    if not re.match(r"^[a-zA-Z0-9_\-]+$", username):
        raise ValueError("Username may only contain letters, numbers, underscores, and hyphens.")
    return username


def validate_password(password: str) -> str:
    """Minimum 8 characters."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    return password


def validate_base64_image(b64: str, max_mb: float = 10.0) -> str:
    """
    Check that a base64 string is non-empty and within the size limit.
    Does NOT decode the full image (done in the ML module).
    """
    if not b64:
        raise ValueError("Image (base64) is required.")

    # Strip data-URL prefix if present
    data = b64.split(",", 1)[-1]

    # Estimate decoded byte size: base64 encodes 3 bytes as 4 chars
    estimated_bytes = len(data) * 3 / 4
    if estimated_bytes > max_mb * 1024 * 1024:
        raise ValueError(f"Image exceeds maximum size of {max_mb} MB.")
    return b64


def validate_geolocation(lat: Any, lng: Any) -> tuple:
    """Validate and return (latitude, longitude) as floats."""
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        raise ValueError("latitude and longitude must be numeric.")
    if not (-90 <= lat <= 90):
        raise ValueError("latitude must be between -90 and 90.")
    if not (-180 <= lng <= 180):
        raise ValueError("longitude must be between -180 and 180.")
    return lat, lng


def validate_pagination(page: Any, limit: Any, max_limit: int = 100) -> tuple:
    """Return (page, limit) as ints with sensible defaults."""
    try:
        page = max(1, int(page or 1))
        limit = min(max(1, int(limit or 20)), max_limit)
    except (TypeError, ValueError):
        raise ValueError("page and limit must be positive integers.")
    return page, limit


# ── Request body validators ───────────────────────────────────────────────────

def validate_register_payload(data: Dict) -> Dict:
    required = ("username", "email", "password")
    for field in required:
        if not data.get(field):
            raise ValueError(f"'{field}' is required.")
    return {
        "username": validate_username(data["username"]),
        "email": validate_email(data["email"]),
        "password": validate_password(data["password"]),
        "bio": str(data.get("bio", ""))[:300],
        "country": str(data.get("country", ""))[:100],
    }


def validate_observation_payload(data: Dict) -> Dict:
    if not data.get("selected_species"):
        raise ValueError("'selected_species' is required.")
    if not data.get("image_base64"):
        raise ValueError("'image_base64' is required.")

    lat = data.get("latitude") or data.get("geolocation", {}).get("latitude")
    lng = data.get("longitude") or data.get("geolocation", {}).get("longitude")

    lat, lng = validate_geolocation(lat, lng)
    validate_base64_image(data["image_base64"])

    return {
        "selected_species": str(data["selected_species"])[:200],
        "image_base64": data["image_base64"],
        "latitude": lat,
        "longitude": lng,
        "habitat_tags": [str(t)[:50] for t in data.get("habitat_tags", [])[:10]],
        "country": str(data.get("country", ""))[:100],
        "state": str(data.get("state", ""))[:100],
        "district": str(data.get("district", ""))[:100],
        "weather_data": data.get("weather_data", {}),
        "ai_predictions": data.get("ai_predictions", []),
        "verification_status": "pending",
    }


def validate_post_payload(data: Dict) -> Dict:
    content = str(data.get("content", "")).strip()
    image_b64 = data.get("image_base64", "")
    if not content and not image_b64:
        raise ValueError("A post must have content or an image.")
    if len(content) > 2000:
        raise ValueError("Post content must be 2000 characters or fewer.")
    if image_b64:
        validate_base64_image(image_b64)
    return {
        "content": content[:2000],
        "image_base64": image_b64,
        "referenced_observations": data.get("referenced_observations", []),
    }
