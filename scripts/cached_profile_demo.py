"""Stage 2: the profile as cached context instead of a tool.

Run it TWICE:  python scripts/cached_profile_demo.py [--planner]

Run 1 writes the cache. Run 2 should read it. Compare the usage numbers.

--planner uses PLANNER_MODEL (Opus 5) instead of MODEL (Haiku 4.5). That
matters more than it looks: the minimum cacheable prefix is model-dependent
and NOT monotonic across generations.
"""

import sys

import anthropic

from job_agent.config import MODEL, PLANNER_MODEL, require_api_key
from job_agent.profile import load_profile
from job_agent.prompt import cached_system, profile_system_prompt
from job_agent.stage1.loop import run_conversation

QUESTION = "What school does the candidate attend, and do they need sponsorship?"

# Minimum cacheable prefix, in tokens. Below this a cache_control marker is
# silently ignored — no error, just zeros in the usage numbers.
CACHE_MINIMUMS = {
    "claude-opus-5": 512,
    "claude-opus-4-8": 1024,
    "claude-sonnet-5": 1024,
    "claude-haiku-4-5": 4096,
}


def main() -> None:
    require_api_key()
    client = anthropic.Anthropic()

    model = PLANNER_MODEL if "--planner" in sys.argv else MODEL
    minimum = CACHE_MINIMUMS.get(model)

    profile = load_profile()
    text = profile_system_prompt(profile)
    system = cached_system(text)
    approx_tokens = len(text) // 4

    print(f"model:         {model}")
    print(f"system prompt: {len(text)} chars (~{approx_tokens} tokens)")
    if minimum:
        verdict = "SHOULD cache" if approx_tokens >= minimum else "TOO SHORT — will not cache"
        print(f"cache minimum: {minimum} tokens  ->  {verdict}")

    result = run_conversation(client, QUESTION, system=system, tools=None, model=model)

    u = result.usage
    print(f"\nturns:                 {result.turns}   (Stage 1 needed 2 — no tool round-trip now)")
    print(f"input_tokens:          {u.input_tokens}")
    print(f"cache_creation_input:  {u.cache_creation_input_tokens}")
    print(f"cache_read_input:      {u.cache_read_input_tokens}")


if __name__ == "__main__":
    main()
