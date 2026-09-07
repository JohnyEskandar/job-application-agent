"""Stage 2: the profile as cached context instead of a tool.

Run it TWICE:  python scripts/cached_profile_demo.py

Run 1 writes the cache. Run 2 should read it. Compare the usage numbers.
"""

import anthropic

from job_agent.config import require_api_key
from job_agent.profile import load_profile
from job_agent.prompt import cached_system, profile_system_prompt
from job_agent.stage1.loop import run_conversation

QUESTION = "What school does the candidate attend, and do they need sponsorship?"


def main() -> None:
    require_api_key()
    client = anthropic.Anthropic()

    profile = load_profile()
    text = profile_system_prompt(profile)
    system = cached_system(text)

    print(f"system prompt: {len(text)} chars (~{len(text) // 4} tokens)")
    if len(text) < 4000:
        print("  WARNING: under ~1024 tokens. Caching silently will not happen.")

    result = run_conversation(client, QUESTION, system=system, tools=None)

    u = result.usage
    print(f"\nturns:                 {result.turns}   (Stage 1 needed 2 — no tool round-trip now)")
    print(f"input_tokens:          {u.input_tokens}")
    print(f"cache_creation_input:  {u.cache_creation_input_tokens}")
    print(f"cache_read_input:      {u.cache_read_input_tokens}")
    print(f"\nanswer:\n{result.final_text}")


if __name__ == "__main__":
    main()
