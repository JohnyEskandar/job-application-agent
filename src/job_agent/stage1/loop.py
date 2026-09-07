"""The agent loop, written by hand.

Everything here could be replaced by client.beta.messages.tool_runner() or by
LangGraph. It is written out longhand because the shape of this loop is the
thing being learned. Stage 8.5 ports it to LangGraph and compares.
"""

from dataclasses import dataclass

from job_agent.config import MAX_TOKENS, MODEL
from job_agent.stage1.tools import TOOLS, dispatch_tool

# No `thinking` here — MODEL is Haiku 4.5, which rejects adaptive thinking.
# Stage 5 switches the planner to PLANNER_MODEL and turns it on there.


@dataclass
class ConversationResult:
    messages: list[dict]
    final_text: str
    turns: int


def run_conversation(
    client,
    user_message: str,
    *,
    tools: list[dict] = TOOLS,
    dispatch=dispatch_tool,
    model: str = MODEL,
    max_turns: int = 10,
) -> ConversationResult:
    """Talk to Claude until it stops asking for tools.

    `client` is injected rather than constructed here so tests can pass a fake
    and never touch the network.
    """
    messages: list[dict] = [{"role": "user", "content": user_message}]

    for turn in range(1, max_turns + 1):
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            tools=tools,
            messages=messages,
        )

        # The assistant's content goes back verbatim — tool_use blocks and
        # thinking blocks included. Summarizing it here breaks the next turn.
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            final_text = "".join(
                block.text for block in response.content if block.type == "text"
            )
            return ConversationResult(messages, final_text, turn)

        # Claude may ask for several tools at once. Every result goes back in
        # ONE user message; splitting them teaches the model to stop
        # parallelizing.
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result_block = {"type": "tool_result", "tool_use_id": block.id}
            try:
                result_block["content"] = dispatch(block.name, block.input)
            except Exception as exc:
                # A failed tool still needs a result. Dropping it leaves an
                # unanswered tool_use and the next request 400s.
                result_block["content"] = f"Error: {exc}"
                result_block["is_error"] = True
            tool_results.append(result_block)

        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError(
        f"Conversation did not finish within {max_turns} turns. "
        "Claude is likely calling the same tool repeatedly."
    )
