"""
BiomeBa — Entry point.
Run with:  python run.py
"""

import os
from dotenv import load_dotenv

# Load .env before anything else so config.py picks up the vars
load_dotenv()

from app import create_app  # noqa: E402  (import after dotenv)

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
