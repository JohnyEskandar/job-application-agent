"""Stage 1: one hand-built tool round-trip, printed in full.

Run:  python scripts/manual_roundtrip.py

Read the output top to bottom. The goal is to be able to draw the four-message
conversation on a whiteboard afterwards.
"""

import json

import anthropic

from job_agent.config import MAX_TOKENS, MODEL, require_api_key
from job_agent.stage1.tools import TOOLS, get_profile

# No `thinking` parameter here: Haiku 4.5 does not support adaptive thinking,
# and proving the tool protocol does not need it. Stage 5 adds it with Opus 5.


def show_blocks(label: str, content) -> None:
    print(f"\n--- {label} ---")
    for block in content:
        if block.type == "text":
            print(f"  [text]     {block.text}")
        elif block.type == "tool_use":
            print(f"  [tool_use] id={block.id} name={block.name} input={block.input}")
        else:
            print(f"  [{block.type}]")


def main() -> None:
    require_api_key()
    client = anthropic.Anthropic()

    question = "What school does the candidate attend?"
    messages = [{"role": "user", "content": question}]

    # 1. Ask. Claude cannot answer without the tool.
    first = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        tools=TOOLS,
        messages=messages,
    )
    print(f"\nstop_reason = {first.stop_reason!r}   <- 'tool_use' means Claude is asking YOU to run something")
    show_blocks("assistant turn 1", first.content)

    # 2. Claude asked for a tool. Find the request and run it ourselves.
    tool_use = next(b for b in first.content if b.type == "tool_use")
    result = json.dumps(get_profile())
    print(f"\nran {tool_use.name}() locally -> {result}")

    # 3. Hand the result back. Two things matter here:
    #    - the assistant's ENTIRE content list goes back verbatim, tool_use
    #      block and all. Not a summary of it.
    #    - the result is a USER message containing a tool_result block whose
    #      tool_use_id matches the id above. A mismatch is a 400.
    messages.append({"role": "assistant", "content": first.content})
    messages.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                }
            ],
        }
    )

    # 4. Ask again with the result in hand. Now Claude can answer.
    second = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        tools=TOOLS,
        messages=messages,
    )
    print(f"\nstop_reason = {second.stop_reason!r}   <- 'end_turn' means Claude is done")
    show_blocks("assistant turn 2", second.content)

    messages.append({"role": "assistant", "content": second.content})

    print("\n=== the full conversation, as the API sees it ===")
    print(
        json.dumps(
            messages,
            indent=2,
            default=lambda o: o.model_dump() if hasattr(o, "model_dump") else str(o),
        )
    )
    print(f"\n{len(messages)} messages: user -> assistant(tool_use) -> user(tool_result) -> assistant(answer)")


if __name__ == "__main__":
    main()