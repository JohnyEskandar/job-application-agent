import pytest

from job_agent.config import MODEL, MAX_TOKENS, PLANNER_MODEL, PROJECT_ROOT, require_api_key


def test_default_model_is_the_cheap_one_for_learning_stages():
    assert MODEL == "claude-haiku-4-5"


def test_planner_model_is_reserved_for_judgment():
    assert PLANNER_MODEL == "claude-opus-5"


def test_max_tokens_is_generous_enough_for_non_streaming():
    assert MAX_TOKENS >= 8000


def test_project_root_points_at_the_repo():
    assert (PROJECT_ROOT / "pyproject.toml").exists()


def test_require_api_key_returns_the_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert require_api_key() == "sk-ant-test"


def test_require_api_key_raises_a_useful_error_when_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        require_api_key()
