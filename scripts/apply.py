"""Fill in a job application. You submit it yourself.

Run:  python scripts/apply.py <application-url>
      python scripts/apply.py <url> --headless    # no window; nothing to finish

This agent CANNOT submit an application. It fills what it can from your
profile, tells you what it refused to answer and why, and leaves the browser
open for you to finish and submit.
"""

import sys
from datetime import datetime

import anthropic

from job_agent.browser import browser_context
from job_agent.config import PROJECT_ROOT, require_api_key
from job_agent.flow import run_application
from job_agent.plan import build_plan
from job_agent.profile import load_profile
from job_agent.review import show


def main() -> None:
    require_api_key()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("usage: python scripts/apply.py <url> [--headless]")
    url = args[0]
    headless = "--headless" in sys.argv

    profile = load_profile()
    client = anthropic.Anthropic()
    run_dir = PROJECT_ROOT / "runs" / datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    with browser_context(headless=headless) as ctx:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        def on_page(snapshot, plan, report):
            shot = run_dir / f"page{len(list(run_dir.glob('*.png'))) + 1}.png"
            page.screenshot(path=str(shot))
            show(snapshot, plan, report, str(shot))

        result = run_application(page, planner=lambda s: build_plan(client, s, profile),
                                 on_page=on_page)

        print(f"\n  {result.pages_visited} page(s) filled — {result.detail or result.outcome}")

        if not headless:
            # Hold the window open. Anything typed by hand is still there, and
            # closing it silently would discard that work.
            input("\n  Take it from here. Press Enter when you are done to close the browser. > ")

    print(f"  screenshots: {run_dir}")


if __name__ == "__main__":
    main()
