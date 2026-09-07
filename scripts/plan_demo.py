"""Extract a real application form and plan how to fill it. Fills nothing.

Run:  python scripts/plan_demo.py <url>
      python scripts/plan_demo.py            # uses the committed Rippling fixture
"""

import sys
from pathlib import Path

import anthropic

from job_agent.browser import browser_context
from job_agent.config import require_api_key
from job_agent.extract import extract_snapshot
from job_agent.plan import build_plan
from job_agent.profile import load_profile

FIXTURE = Path("tests/fixtures/rippling_apply.html").resolve().as_uri()


def main() -> None:
    require_api_key()
    url = sys.argv[1] if len(sys.argv) > 1 else FIXTURE

    with browser_context(headless=True) as ctx:
        page = ctx.new_page()
        page.goto(url)
        page.wait_for_timeout(2500)
        snapshot = extract_snapshot(page)

    print(f"{len(snapshot.fields)} fields, ats={snapshot.ats}")
    print(f"snapshot payload: {len(snapshot.model_dump_json())} chars\n")

    plan = build_plan(anthropic.Anthropic(), snapshot, load_profile())

    by_id = {f.field_id: f for f in snapshot.fields}

    print("PLANNED")
    for p in plan.fields:
        flag = "   <-- REVIEW" if p.source == "generated" else ""
        name = by_id[p.field_id].accessible_name[:32]
        print(f"  {p.source:11} {name:34} {str(p.value)[:34]}{flag}")

    print("\nNEEDS A HUMAN")
    for u in plan.unresolved:
        name = by_id[u.field_id].accessible_name[:32] if u.field_id in by_id else u.field_id
        print(f"  {name:34} {u.reason[:76]}")


if __name__ == "__main__":
    main()
