"""
app/routes/species.py — Species identification and observation routes.

POST /identify                         — Upload base64 image → top-5 predictions
POST /observations                     — Save a confirmed observation
GET  /observations/<id>                — Get a single observation
GET  /observations/nearby              — Geospatial nearby query
GET  /observations/species/<name>      — All observations of a species
GET  /observations/user/<user_id>      — All observations by a user
DELETE /observations/<id>              — Delete own observation
POST /observations/<id>/like           — Toggle like
"""

import logging
from datetime import datetime, timezone

from bson import ObjectId
from flask import Blueprint, jsonify, request

from app.extensions import db, limiter
from app.middleware.auth_middleware import token_required, optional_token
from app.ml import inference
from app.models.observation import new_observation
from app.services import rarity_service, xp_service, mission_service
from app.services.notification_service import notify
from app.utils.serializers import serialize_observation
from app.utils.pagination import get_pagination_params, paginate_response
from app.utils.validators import validate_observation_payload
from app.utils.geo import build_near_query

logger = logging.getLogger(__name__)
bp = Blueprint("species", __name__)


# ── POST /identify ─────────────────────────────────────────────────────────────
@bp.post("/identify")
@limiter.limit("10 per minute")
@token_required
def identify(current_user):
    """
    Run species identification on a base64-encoded image.

    Request body (JSON):
      { "image_base64": "...", "top_k": 5 }

    Response 200:
      { "predictions": [{species, common_name, confidence, rank}], "model_info": {...} }
    """
    data = request.get_json(force=True, silent=True) or {}
    b64 = data.get("image_base64", "")
    top_k = int(data.get("top_k", 5))

    if not b64:
        return jsonify({"error": "image_base64 is required."}), 400

    try:
        predictions = inference.predict_from_b64(b64, top_k=top_k)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error("Inference error: %s", exc)
        return jsonify({"error": "Inference failed. Please try again."}), 500

    if not predictions:
        return jsonify({"error": "Model not loaded. Please contact the administrator."}), 503

    # Optionally preview rarity for the top prediction
    top_species = predictions[0]["species"]
    rarity_preview = rarity_service.calculate_rarity(top_species)

    return jsonify({
        "predictions": predictions,
        "top_prediction_rarity": {
            "score": rarity_preview["rarity_score"],
            "tier": rarity_preview["rarity_tier"],
        },
        "model_info": {
            "architecture": inference.ARCH,
            "num_classes": inference.NUM_CLASSES,
        },
    }), 200


# ── POST /observations ─────────────────────────────────────────────────────────
@bp.post("/observations")
@token_required
def create_observation(current_user):
    """
    Save a confirmed wildlife observation.

    Request body (JSON):
      { selected_species, image_base64, latitude, longitude,
        ai_predictions?, habitat_tags?, country?, state?, district?,
        weather_data? }
    """
    data = request.get_json(force=True, silent=True) or {}

    try:
        validated = validate_observation_payload(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    species = validated["selected_species"]

    # Calculate rarity score before saving
    rarity = rarity_service.calculate_rarity(
        species=species,
        country=validated["country"],
        district=validated["district"],
    )

    doc = new_observation(
        user_id=current_user["_id"],
        username=current_user.get("username", ""),
        selected_species=species,
        image_base64=validated["image_base64"],
        latitude=validated["latitude"],
        longitude=validated["longitude"],
        ai_predictions=validated["ai_predictions"],
        rarity_score=rarity["rarity_score"],
        rarity_tier=rarity["rarity_tier"],
        habitat_tags=validated["habitat_tags"],
        country=validated["country"],
        state=validated["state"],
        district=validated["district"],
        weather_data=validated.get("weather_data", {}),
    )

    result = db.observations.insert_one(doc)
    obs_id = result.inserted_id

    # ── Update user stats ────────────────────────────────────────────────────
    # Check if this is a new species for the user
    existing_species = db.observations.count_documents({
        "user_id": current_user["_id"],
        "selected_species": species,
        "_id": {"$ne": obs_id},
    })
    is_new_species = existing_species == 0
    is_rare = rarity["rarity_score"] >= 41  # Rare tier and above

    stat_inc = {"stats.total_observations": 1}
    if is_new_species:
        stat_inc["stats.unique_species_found"] = 1
    if is_rare:
        stat_inc["stats.rare_species_found"] = 1

    db.users.update_one({"_id": current_user["_id"]}, {"$inc": stat_inc})

    # ── Award XP ─────────────────────────────────────────────────────────────
    tier = rarity["rarity_tier"].lower()
    xp_action_map = {
        "legendary": "observation_legendary",
        "epic":      "observation_epic",
        "rare":      "observation_rare",
        "uncommon":  "observation_uncommon",
    }
    xp_action = xp_action_map.get(tier, "observation")
    xp_result = xp_service.award_xp(current_user["_id"], xp_action)

    # ── Refresh mission progress ───────────────────────────────────────────
    mission_service.refresh_progress(current_user["_id"])

    # ── Upsert species metadata ────────────────────────────────────────────
    db.species_meta.update_one(
        {"species": species},
        {
            "$inc": {"observation_count": 1},
            "$setOnInsert": {
                "species": species,
                "conservation_status": "LC",  # default; override via seed
                "created_at": datetime.now(timezone.utc),
            },
        },
        upsert=True,
    )

    doc["_id"] = obs_id
    return jsonify({
        "message": "Observation saved.",
        "observation": serialize_observation(doc),
        "rarity": rarity,
        "xp": xp_result,
    }), 201


# ── GET /observations/<id> ─────────────────────────────────────────────────────
@bp.get("/observations/<obs_id>")
def get_observation(obs_id: str):
    """Get a single observation by ID."""
    try:
        oid = ObjectId(obs_id)
    except Exception:
        return jsonify({"error": "Invalid observation ID."}), 400

    obs = db.observations.find_one({"_id": oid})
    if not obs:
        return jsonify({"error": "Observation not found."}), 404

    return jsonify({"observation": serialize_observation(obs)}), 200


# ── GET /observations/nearby ───────────────────────────────────────────────────
@bp.get("/observations/nearby")
def get_nearby():
    """
    Find observations near a coordinate.

    Query params: lat, lng, radius_km (default 25), page, limit
    """
    try:
        lat = float(request.args.get("lat", 0))
        lng = float(request.args.get("lng", 0))
        radius_km = float(request.args.get("radius_km", 25))
    except (TypeError, ValueError):
        return jsonify({"error": "lat, lng must be numeric."}), 400

    if radius_km > 500:
        return jsonify({"error": "radius_km must be ≤ 500."}), 400

    page, limit, skip = get_pagination_params()

    query = {"location": build_near_query(lng, lat, radius_km)}

    # $nearSphere doesn't support count_documents, so we estimate
    total_cursor = list(db.observations.find(query, {"_id": 1}).skip(0).limit(10000))
    total = len(total_cursor)

    docs = list(
        db.observations.find(query, {"image_base64": 0})
        .skip(skip)
        .limit(limit)
    )

    return jsonify(paginate_response(docs, total, page, limit, serialize_observation)), 200


# ── GET /observations/species/<name> ──────────────────────────────────────────
@bp.get("/observations/species/<path:species_name>")
def get_by_species(species_name: str):
    """Get all observations for a specific species."""
    page, limit, skip = get_pagination_params()

    query = {"selected_species": {"$regex": f"^{species_name}$", "$options": "i"}}
    total = db.observations.count_documents(query)
    docs = list(
        db.observations.find(query, {"image_base64": 0})
        .sort("timestamp", -1)
        .skip(skip)
        .limit(limit)
    )

    return jsonify(paginate_response(docs, total, page, limit, serialize_observation)), 200


# ── GET /observations/user/<user_id> ──────────────────────────────────────────
@bp.get("/observations/user/<user_id>")
def get_user_observations(user_id: str):
    """Get paginated observations for a specific user."""
    try:
        uid = ObjectId(user_id)
    except Exception:
        return jsonify({"error": "Invalid user ID."}), 400

    page, limit, skip = get_pagination_params()
    query = {"user_id": uid}
    total = db.observations.count_documents(query)
    docs = list(
        db.observations.find(query, {"image_base64": 0})
        .sort("timestamp", -1)
        .skip(skip)
        .limit(limit)
    )

    return jsonify(paginate_response(docs, total, page, limit, serialize_observation)), 200


# ── DELETE /observations/<id> ──────────────────────────────────────────────────
@bp.delete("/observations/<obs_id>")
@token_required
def delete_observation(current_user, obs_id: str):
    """Delete the authenticated user's own observation."""
    try:
        oid = ObjectId(obs_id)
    except Exception:
        return jsonify({"error": "Invalid observation ID."}), 400

    obs = db.observations.find_one({"_id": oid})
    if not obs:
        return jsonify({"error": "Observation not found."}), 404
    if obs["user_id"] != current_user["_id"]:
        return jsonify({"error": "You can only delete your own observations."}), 403

    db.observations.delete_one({"_id": oid})
    db.users.update_one({"_id": current_user["_id"]}, {"$inc": {"stats.total_observations": -1}})
    return jsonify({"message": "Observation deleted."}), 200


# ── POST /observations/<id>/like ───────────────────────────────────────────────
@bp.post("/observations/<obs_id>/like")
@token_required
def like_observation(current_user, obs_id: str):
    """Toggle a like on an observation."""
    try:
        oid = ObjectId(obs_id)
    except Exception:
        return jsonify({"error": "Invalid observation ID."}), 400

    obs = db.observations.find_one({"_id": oid}, {"likes": 1, "user_id": 1})
    if not obs:
        return jsonify({"error": "Observation not found."}), 404

    uid = current_user["_id"]
    liked = uid in obs.get("likes", [])

    if liked:
        db.observations.update_one({"_id": oid}, {"$pull": {"likes": uid}})
        return jsonify({"liked": False}), 200
    else:
        db.observations.update_one({"_id": oid}, {"$addToSet": {"likes": uid}})
        if obs["user_id"] != uid:
            notify(
                recipient_id=obs["user_id"],
                notif_type="like",
                message=f"{current_user['username']} liked your observation.",
                actor_id=uid,
                ref_id=oid,
                ref_type="observation",
            )
        return jsonify({"liked": True}), 200


# ── GET /observations/map ──────────────────────────────────────────────────────
@bp.get("/observations/map")
def get_map_observations():
    """
    Return recent observations for map display.
    Excludes image_base64 for fast transfer.
    Query params: limit (default 300, max 500)
    """
    try:
        limit = min(int(request.args.get("limit", 300)), 500)
    except (TypeError, ValueError):
        limit = 300

    docs = list(
        db.observations.find(
            {},
            {
                "_id": 1,
                "selected_species": 1,
                "geolocation": 1,
                "username": 1,
                "user_id": 1,
                "rarity_tier": 1,
                "rarity_score": 1,
                "timestamp": 1,
                "country": 1,
                "state": 1,
                "habitat_tags": 1,
            },
        )
        .sort("timestamp", -1)
        .limit(limit)
    )

    return jsonify({"observations": [serialize_observation(doc) for doc in docs]}), 200
