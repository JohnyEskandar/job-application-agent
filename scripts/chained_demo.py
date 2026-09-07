"""Stage 1: a question that needs BOTH tools, answered by the loop.

Run:  python scripts/chained_demo.py

Task 3 hand-built one round-trip. This asks something no single tool can
answer, and lets run_conversation() drive as many turns as it takes.
"""

import anthropic

from job_agent.config import require_api_key
from job_agent.stage1.loop import run_conversation

QUESTION = (
    "Look at the candidate's major and their resume. Name one specific project "
    "from the resume that best demonstrates their major, and say why in one sentence."
)


def main() -> None:
    require_api_key()
    client = anthropic.Anthropic()

    result = run_conversation(client, QUESTION)

    print(f"\nfinished in {result.turns} turns, {len(result.messages)} messages\n")

    for i, message in enumerate(result.messages):
        content = message["content"]
        if isinstance(content, str):
            print(f"[{i}] {message['role']:9} {content[:100]}")
            continue
        for block in content:
            if isinstance(block, dict):
                kind = block["type"]
                detail = block.get("content", "")
                print(f"[{i}] {message['role']:9} {kind:12} {str(detail)[:80]}")
            else:
                detail = getattr(block, "name", None) or getattr(block, "text", "")
                print(f"[{i}] {message['role']:9} {block.type:12} {str(detail)[:80]}")

    print(f"\nanswer:\n{result.final_text}")


if __name__ == "__main__":
    main()
