"""
scripts/seed_missions.py — Seed the database with sample missions.

Run from the project root:
    python scripts/seed_missions.py

Inserts 12 missions if the missions collection is empty.
"""

import os
import sys

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.models.mission import new_mission

SAMPLE_MISSIONS = [
    # ── Daily missions ──────────────────────────────────────────────────────
    new_mission(
        title="Daily Explorer",
        description="Upload 1 wildlife observation today.",
        mission_type="daily",
        difficulty="easy",
        xp_reward=15,
        requirements={"type": "observation_count", "count": 1},
    ),
    new_mission(
        title="Avid Observer",
        description="Upload 3 observations in a single day.",
        mission_type="daily",
        difficulty="medium",
        xp_reward=40,
        requirements={"type": "observation_count", "count": 3},
        badge_reward=None,
    ),
    new_mission(
        title="Nature Journalist",
        description="Create a post sharing your wildlife experience.",
        mission_type="daily",
        difficulty="easy",
        xp_reward=10,
        requirements={"type": "observation_count", "count": 1},
    ),
    new_mission(
        title="Five-a-Day",
        description="Upload 5 observations today.",
        mission_type="daily",
        difficulty="hard",
        xp_reward=75,
        requirements={"type": "observation_count", "count": 5},
        badge_reward="daily_champion",
    ),

    # ── Weekly missions ─────────────────────────────────────────────────────
    new_mission(
        title="Week in the Wild",
        description="Observe 10 different species this week.",
        mission_type="weekly",
        difficulty="medium",
        xp_reward=120,
        requirements={"type": "unique_species", "count": 10},
        badge_reward="week_explorer",
    ),
    new_mission(
        title="Rarity Hunter",
        description="Discover 3 Rare or above species this week.",
        mission_type="weekly",
        difficulty="hard",
        xp_reward=200,
        requirements={"type": "rare_discovery", "count": 3},
        badge_reward="rarity_hunter",
    ),
    new_mission(
        title="Community Builder",
        description="Create 5 posts and engage with the community.",
        mission_type="weekly",
        difficulty="easy",
        xp_reward=60,
        requirements={"type": "observation_count", "count": 5},
    ),
    new_mission(
        title="Mega Uploader",
        description="Upload 20 observations in a single week.",
        mission_type="weekly",
        difficulty="hard",
        xp_reward=300,
        requirements={"type": "observation_count", "count": 20},
        badge_reward="mega_uploader",
    ),

    # ── Exploration missions ─────────────────────────────────────────────────
    new_mission(
        title="District Hopper",
        description="Make observations in 3 different districts.",
        mission_type="exploration",
        difficulty="medium",
        xp_reward=150,
        requirements={"type": "new_district", "count": 3},
        badge_reward="explorer",
    ),
    new_mission(
        title="Biodiversity Mapper",
        description="Make observations in 5 different districts.",
        mission_type="exploration",
        difficulty="hard",
        xp_reward=300,
        requirements={"type": "new_district", "count": 5},
        badge_reward="cartographer",
    ),

    # ── Rarity missions ──────────────────────────────────────────────────────
    new_mission(
        title="Rare Encounter",
        description="Discover your first Rare species.",
        mission_type="rarity",
        difficulty="medium",
        xp_reward=100,
        requirements={"type": "rare_discovery", "count": 1},
        badge_reward="first_rare",
    ),
    new_mission(
        title="Legendary Scout",
        description="Discover a Legendary rarity species.",
        mission_type="rarity",
        difficulty="legendary",
        xp_reward=500,
        requirements={"type": "rare_discovery", "count": 1},
        badge_reward="first_legendary",
    ),
]


def seed():
    from app.extensions import db
    existing = db.missions.count_documents({})
    if existing > 0:
        print(f"[seed_missions] {existing} missions already exist. Skipping.")
        return

    result = db.missions.insert_many(SAMPLE_MISSIONS)
    print(f"[seed_missions] Inserted {len(result.inserted_ids)} missions.")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        seed()
