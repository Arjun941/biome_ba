"""
app/services/rarity_service.py — Rarity scoring engine.

Calculates a 0–100 rarity score for a species based on:
  - Global observation count       (40 pts) — fewer observations = rarer
  - Local/regional rarity          (25 pts) — not seen in same country/district
  - Seasonal rarity                (15 pts) — not seen this month before
  - Conservation status            (10 pts) — placeholder (future IUCN integration)
  - Unique observer count          (10 pts) — fewer unique observers = rarer

Tiers:
  0–20   → Common
  21–40  → Uncommon
  41–60  → Rare
  61–80  → Epic
  81–100 → Legendary
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Tuple

from app.extensions import db

logger = logging.getLogger(__name__)


# ── Tier thresholds ────────────────────────────────────────────────────────────
TIERS = [
    (81, "Legendary"),
    (61, "Epic"),
    (41, "Rare"),
    (21, "Uncommon"),
    (0,  "Common"),
]


def score_to_tier(score: float) -> str:
    """Map a numeric score (0–100) to a human-readable rarity tier."""
    for threshold, tier in TIERS:
        if score >= threshold:
            return tier
    return "Common"


# ── Global rarity component (40 pts) ──────────────────────────────────────────

def _global_rarity_pts(species: str, global_count: int) -> float:
    """
    Fewer global observations → higher score.
    Sigmoid-like curve capped at 40 pts.
    Breakpoints: >1000 obs ≈ 0 pts; 1 obs ≈ 40 pts.
    """
    if global_count <= 0:
        return 40.0
    # log-scaled: score = 40 * (1 - log10(count) / log10(max_expected))
    import math
    max_expected = 5000.0   # observations above this are considered "very common"
    ratio = math.log10(max(global_count, 1)) / math.log10(max_expected)
    return max(0.0, 40.0 * (1.0 - ratio))


# ── Local rarity component (25 pts) ───────────────────────────────────────────

def _local_rarity_pts(species: str, country: str, district: str) -> float:
    """
    Check whether the species has been seen in the same country/district.
    Full 25 pts if never seen locally; partial if only seen in other districts.
    """
    if not country:
        return 12.5   # no location data → half score

    local_count = db.observations.count_documents(
        {"selected_species": species, "country": country}
    )
    if local_count == 0:
        return 25.0

    district_count = db.observations.count_documents(
        {"selected_species": species, "country": country, "district": district}
    ) if district else local_count

    if district_count == 0:
        return 15.0   # seen in country but not district
    return 0.0


# ── Seasonal rarity component (15 pts) ────────────────────────────────────────

def _seasonal_rarity_pts(species: str) -> float:
    """
    Check whether the species has been observed in the current calendar month
    across any previous year.
    """
    current_month = datetime.now(timezone.utc).month

    # Build a month-match pipeline using $month aggregation operator
    pipeline = [
        {"$match": {"selected_species": species}},
        {"$project": {"month": {"$month": "$timestamp"}}},
        {"$match": {"month": current_month}},
        {"$count": "total"},
    ]
    result = list(db.observations.aggregate(pipeline))
    count = result[0]["total"] if result else 0
    return 15.0 if count == 0 else 0.0


# ── Conservation status component (10 pts) ────────────────────────────────────

def _conservation_pts(species: str) -> float:
    """
    Placeholder — returns 5 pts by default.
    Future: integrate IUCN Red List API or store conservation status
    in the `species_meta` collection.
    """
    meta = db.species_meta.find_one({"species": species}, {"conservation_status": 1})
    if not meta:
        return 5.0   # unknown → neutral score
    status = meta.get("conservation_status", "LC")
    status_scores = {
        "EX": 10.0,   # Extinct
        "EW": 10.0,   # Extinct in the Wild
        "CR": 9.0,    # Critically Endangered
        "EN": 8.0,    # Endangered
        "VU": 6.0,    # Vulnerable
        "NT": 4.0,    # Near Threatened
        "LC": 0.0,    # Least Concern
        "DD": 3.0,    # Data Deficient
    }
    return status_scores.get(status, 5.0)


# ── Unique observers component (10 pts) ───────────────────────────────────────

def _unique_observers_pts(species: str) -> float:
    """
    Fewer unique users who've seen this species → higher rarity.
    0 pts if >100 unique observers; 10 pts if only 1.
    """
    result = list(db.observations.aggregate([
        {"$match": {"selected_species": species}},
        {"$group": {"_id": "$user_id"}},
        {"$count": "unique"},
    ]))
    unique = result[0]["unique"] if result else 0
    if unique <= 1:
        return 10.0
    if unique >= 100:
        return 0.0
    import math
    return max(0.0, 10.0 * (1.0 - math.log10(unique) / 2.0))


# ── Public API ─────────────────────────────────────────────────────────────────

def calculate_rarity(
    species: str,
    country: str = "",
    district: str = "",
) -> Dict[str, Any]:
    """
    Calculate a full rarity result for the given species and optional location.

    Returns:
        {
            "rarity_score": float (0–100),
            "rarity_tier":  str,
            "breakdown": {
                "global_pts": float,
                "local_pts":  float,
                "seasonal_pts": float,
                "conservation_pts": float,
                "unique_observer_pts": float,
            }
        }
    """
    global_count = db.observations.count_documents({"selected_species": species})

    global_pts       = _global_rarity_pts(species, global_count)
    local_pts        = _local_rarity_pts(species, country, district)
    seasonal_pts     = _seasonal_rarity_pts(species)
    conservation_pts = _conservation_pts(species)
    unique_pts       = _unique_observers_pts(species)

    score = global_pts + local_pts + seasonal_pts + conservation_pts + unique_pts
    score = round(min(100.0, max(0.0, score)), 2)
    tier  = score_to_tier(score)

    logger.debug(
        "Rarity for %s: %.1f (%s) | g=%.1f l=%.1f s=%.1f c=%.1f u=%.1f",
        species, score, tier, global_pts, local_pts, seasonal_pts, conservation_pts, unique_pts,
    )

    return {
        "rarity_score": score,
        "rarity_tier": tier,
        "breakdown": {
            "global_pts": round(global_pts, 2),
            "local_pts": round(local_pts, 2),
            "seasonal_pts": round(seasonal_pts, 2),
            "conservation_pts": round(conservation_pts, 2),
            "unique_observer_pts": round(unique_pts, 2),
        },
    }
