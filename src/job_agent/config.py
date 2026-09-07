"""Project-wide configuration. Loads .env once, at import."""

import os
from pathlib import Path

from dotenv import load_dotenv

# config.py -> job_agent/ -> src/ -> repo root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")

# Stages 1-6 prove mechanics, not judgment — the cheap model is the right one.
MODEL = "claude-haiku-4-5"

# Reserved for the Stage 5 field planner, where judgment quality matters.
# Note: Opus 5 supports thinking={"type": "adaptive"}; Haiku 4.5 does not.
PLANNER_MODEL = "claude-opus-5"

MAX_TOKENS = 16000


def require_api_key() -> str:
    """Return the API key, or explain exactly how to fix its absence."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and paste "
            "your key from https://console.anthropic.com/settings/keys"
        )
    return key
