from dataclasses import dataclass, field

import pytest

from job_agent.stage1.loop import ConversationResult, run_conversation
from job_agent.stage1.tools import UnknownToolError


# --- fakes: stand-ins for the shapes the SDK returns -----------------------

@dataclass
class FakeBlock:
    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict = field(default_factory=dict)


@dataclass
class FakeUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class FakeResponse:
    stop_reason: str
    content: list
    usage: FakeUsage = field(default_factory=FakeUsage)


class FakeClient:
    """Returns canned responses in order and records every request."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        # Snapshot `messages`. run_conversation mutates one list in place, so
        # storing the reference would make every recorded call point at the
        # same list — and the test would see its final state, not what was
        # actually sent on this call.
        recorded = dict(kwargs)
        recorded["messages"] = list(kwargs["messages"])
        self.calls.append(recorded)
        if not self._responses:
            raise AssertionError("loop made more API calls than the test provided")
        return self._responses.pop(0)


def text_response(text):
    return FakeResponse("end_turn", [FakeBlock(type="text", text=text)])


def tool_response(*names):
    return FakeResponse(
        "tool_use",
        [FakeBlock(type="tool_use", id=f"toolu_{n}", name=n, input={}) for n in names],
    )


# --- tests ----------------------------------------------------------------

def test_returns_final_text_when_claude_stops_calling_tools():
    client = FakeClient([text_response("WashU")])
    result = run_conversation(client, "What school?")
    assert isinstance(result, ConversationResult)
    assert result.final_text == "WashU"
    assert result.turns == 1


def test_tool_result_carries_the_matching_tool_use_id():
    client = FakeClient([tool_response("get_profile"), text_response("WashU")])
    result = run_conversation(client, "What school?")

    tool_result_message = result.messages[2]
    assert tool_result_message["role"] == "user"
    block = tool_result_message["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "toolu_get_profile"


def test_assistant_content_is_appended_verbatim_not_summarized():
    response = tool_response("get_profile")
    client = FakeClient([response, text_response("WashU")])
    result = run_conversation(client, "What school?")

    # The exact object, not a string rendering of it.
    assert result.messages[1] == {"role": "assistant", "content": response.content}


def test_parallel_tool_calls_return_in_a_single_user_message():
    client = FakeClient(
        [tool_response("get_profile", "get_resume_text"), text_response("done")]
    )
    result = run_conversation(client, "Compare my major to my resume")

    user_messages = [m for m in result.messages if m["role"] == "user"]
    # the original question, plus exactly one message holding BOTH results
    assert len(user_messages) == 2
    assert len(user_messages[1]["content"]) == 2


def test_the_loop_keeps_going_across_chained_tool_calls():
    client = FakeClient(
        [
            tool_response("get_profile"),
            tool_response("get_resume_text"),
            text_response("a matching project"),
        ]
    )
    result = run_conversation(client, "Which project should I mention?")
    assert result.turns == 3
    assert len(client.calls) == 3


def test_a_failing_tool_comes_back_as_an_error_result_not_an_exception():
    def exploding_dispatch(name, tool_input):
        raise UnknownToolError(f"no such tool: {name}")

    client = FakeClient([tool_response("bogus"), text_response("recovered")])
    result = run_conversation(client, "go", dispatch=exploding_dispatch)

    block = result.messages[2]["content"][0]
    assert block["is_error"] is True
    assert "no such tool" in block["content"]
    assert result.final_text == "recovered"


def test_max_turns_guard_stops_a_runaway_loop():
    client = FakeClient([tool_response("get_profile") for _ in range(10)])
    with pytest.raises(RuntimeError, match="did not finish"):
        run_conversation(client, "go", max_turns=3)


def test_every_request_carries_the_tools_and_the_full_history():
    client = FakeClient([tool_response("get_profile"), text_response("WashU")])
    run_conversation(client, "What school?", tools=[{"name": "get_profile"}])

    first, second = client.calls
    assert first["tools"]
    assert len(first["messages"]) == 1
    # the second call resends the whole conversation — the API is stateless
    assert len(second["messages"]) == 3


def test_system_prompt_is_forwarded_on_every_request():
    client = FakeClient([tool_response("get_profile"), text_response("ok")])
    system = [{"type": "text", "text": "facts"}]
    run_conversation(client, "q", system=system, tools=[{"name": "get_profile"}])

    for call in client.calls:
        assert call["system"] == system


def test_tools_are_omitted_entirely_when_there_are_none():
    client = FakeClient([text_response("ok")])
    result = run_conversation(client, "q", tools=None)

    assert "tools" not in client.calls[0]
    assert result.turns == 1
