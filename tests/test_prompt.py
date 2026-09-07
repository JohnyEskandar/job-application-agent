from pathlib import Path

from job_agent.profile import load_profile
from job_agent.prompt import cached_system, profile_system_prompt


def test_prompt_contains_the_facts_a_form_would_ask_for():
    profile = load_profile(Path("profile.example.yaml"))
    text = profile_system_prompt(profile)
    assert profile.identity.first_name in text
    assert profile.identity.email in text
    assert profile.education[0].school in text
    assert "sponsorship" in text.lower()


def test_prompt_is_deterministic_because_caching_needs_a_stable_prefix():
    profile = load_profile(Path("profile.example.yaml"))
    assert profile_system_prompt(profile) == profile_system_prompt(profile)


def test_cached_system_marks_a_breakpoint():
    blocks = cached_system("hello")
    assert blocks == [
        {"type": "text", "text": "hello", "cache_control": {"type": "ephemeral"}}
    ]
