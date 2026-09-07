"""Load and validate profile.yaml."""

from pathlib import Path

import yaml

from job_agent.config import PROJECT_ROOT
from job_agent.models import Profile

DEFAULT_PROFILE_PATH = PROJECT_ROOT / "profile.yaml"


def load_profile(path: Path | None = None) -> Profile:
    """Read a profile YAML file and validate it into a Profile.

    Validation is strict: unknown keys raise rather than being ignored, so a
    typo surfaces here instead of as a blank field on a job application.
    """
    path = Path(path) if path is not None else DEFAULT_PROFILE_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"No profile at {path}. Copy profile.example.yaml to profile.yaml "
            "and fill it in with your real details."
        )
    data = yaml.safe_load(path.read_text()) or {}
    return Profile.model_validate(data)
