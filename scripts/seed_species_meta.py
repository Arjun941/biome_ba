"""
scripts/seed_species_meta.py — Seed basic species metadata.

Seeds the first 200 species from config.json with default conservation status
and zero observation counts. Run after seeding missions.

Run from the project root:
    python scripts/seed_species_meta.py
"""

import os
import sys
import json
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app import create_app

# Load label names from config.json
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(_BASE, "config.json"), encoding="utf-8") as f:
    _cfg = json.load(f)

LABEL_NAMES = _cfg["label_names"]
LABEL_MAP = _cfg.get("label_map", {})

# Sample conservation status overrides (a few well-known species)
CONSERVATION_OVERRIDES = {
    "Magicicada septendecim": "NT",
    "Apis mellifera":         "LC",
    "Lucanus cervus":         "NT",
    "Dynastes tityus":        "LC",
}


def seed(limit: int = 200):
    from app.extensions import db
    existing = db.species_meta.count_documents({})
    if existing >= limit:
        print(f"[seed_species_meta] {existing} species already exist. Skipping.")
        return

    docs = []
    for species in LABEL_NAMES[:limit]:
        docs.append({
            "species": species,
            "common_name": LABEL_MAP.get(species, ""),
            "conservation_status": CONSERVATION_OVERRIDES.get(species, "LC"),
            "observation_count": 0,
            "created_at": datetime.now(timezone.utc),
        })

    # Bulk upsert
    from pymongo import UpdateOne
    ops = [
        UpdateOne(
            {"species": d["species"]},
            {"$setOnInsert": d},
            upsert=True,
        )
        for d in docs
    ]
    result = db.species_meta.bulk_write(ops)
    print(f"[seed_species_meta] Upserted {result.upserted_count} species metadata records.")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        seed(limit=200)
