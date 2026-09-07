"""Apply to a job posting. Stops for your approval before submitting.

Run:  python scripts/apply.py <application-url>
      python scripts/apply.py <url> --headless
      python scripts/apply.py <url> --dry-run    # print the review, always abandon

There is no --yes flag and no timeout. Nothing is submitted unless you type s.
"""

import sys
from datetime import datetime

import anthropic

from job_agent.browser import browser_context
from job_agent.config import PROJECT_ROOT, require_api_key
from job_agent.flow import run_application
from job_agent.plan import build_plan
from job_agent.profile import load_profile
from job_agent.review import ask, render_review


def main() -> None:
    require_api_key()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("usage: python scripts/apply.py <url> [--headless]")
    url = args[0]

    profile = load_profile()
    client = anthropic.Anthropic()
    run_dir = PROJECT_ROOT / "runs" / datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    with browser_context(headless="--headless" in sys.argv) as ctx:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        dry_run = "--dry-run" in sys.argv

        def decide(snapshot, plan, report):
            shot = run_dir / f"page{len(list(run_dir.glob('*.png'))) + 1}.png"
            page.screenshot(path=str(shot))
            if dry_run:
                # Show what would happen, then refuse. No keypress, no submit.
                print(render_review(snapshot, plan, report, str(shot)))
                print("  > [dry run — abandoning]")
                return "abandon"
            return ask(snapshot, plan, report, str(shot))

        result = run_application(
            page,
            planner=lambda snapshot: build_plan(client, snapshot, profile),
            decide=decide,
            submit=lambda p: p.get_by_role("button", name="Submit").first.click(),
        )

    print(f"\noutcome: {result.outcome}  ({result.pages_visited} pages)")
    if result.detail:
        print(f"detail:  {result.detail}")
    print(f"run dir: {run_dir}")


if __name__ == "__main__":
    main()
