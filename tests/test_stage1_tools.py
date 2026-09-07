import json

import pytest

from job_agent.stage1.tools import (
    TOOLS,
    UnknownToolError,
    dispatch_tool,
    get_profile,
    get_resume_text,
)


def test_get_profile_returns_the_expected_fields():
    profile = get_profile()
    assert profile["name"] == "Johny Eskandar"
    assert profile["school"] == "Washington University in St. Louis"
    assert profile["major"] == "Business and Computer Science"


def test_get_resume_text_returns_non_empty_text():
    assert len(get_resume_text()) > 50


def test_tools_declares_both_tools():
    assert {tool["name"] for tool in TOOLS} == {"get_profile", "get_resume_text"}


def test_every_tool_has_a_description_and_an_object_schema():
    for tool in TOOLS:
        assert tool["description"].strip(), f"{tool['name']} needs a description"
        assert tool["input_schema"]["type"] == "object"


def test_dispatch_returns_a_string_because_tool_result_content_is_text():
    result = dispatch_tool("get_profile", {})
    assert isinstance(result, str)
    # The point is the serialization round-trip, not any particular value —
    # asserting a literal here would duplicate a fact already covered above,
    # and break every time the profile data changes.
    assert json.loads(result) == get_profile()


def test_dispatch_raises_on_an_unknown_tool_name():
    with pytest.raises(UnknownToolError, match="nonexistent_tool"):
        dispatch_tool("nonexistent_tool", {})
