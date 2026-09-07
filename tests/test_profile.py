from pathlib import Path

import pytest
from pydantic import ValidationError

from job_agent.profile import load_profile


def test_example_profile_loads_and_validates():
    profile = load_profile(Path("profile.example.yaml"))
    assert profile.identity.first_name
    assert profile.identity.email
    assert profile.education, "at least one school"


def test_missing_required_field_fails_loudly(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("identity:\n  first_name: Alex\n")
    with pytest.raises(ValidationError):
        load_profile(bad)


def test_unknown_field_is_rejected_not_silently_ignored(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "identity:\n"
        "  first_name: Alex\n"
        "  last_name: Kim\n"
        "  email: a@b.com\n"
        "  phone: '555'\n"
        "  favourite_colour: blue\n"
    )
    with pytest.raises(ValidationError):
        load_profile(bad)


def test_missing_file_says_which_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="nope.yaml"):
        load_profile(tmp_path / "nope.yaml")
