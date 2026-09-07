"""Fill whatever application form you have navigated to.

Run:  python scripts/fill_here.py [starting-url]

For sites the agent cannot reach on its own — anything behind a login,
an account creation step, or a multi-step flow like Eightfold's
upload-resume-then-generate-a-profile.

You drive the browser to the form. Press Enter. It fills what it can and
hands the browser straight back. It still cannot submit.

The browser uses the persistent profile, so a login done here survives into
later runs.
"""

import sys
from datetime import datetime

import anthropic

from job_agent.browser import browser_context
from job_agent.config import PROJECT_ROOT, require_api_key
from job_agent.extract import extract_snapshot, probe_combobox_options
from job_agent.fill import execute_plan
from job_agent.plan import build_plan
from job_agent.profile import load_profile
from job_agent.review import show


def main() -> None:
    require_api_key()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    start = args[0] if args else "about:blank"

    profile = load_profile()
    client = anthropic.Anthropic()
    run_dir = PROJECT_ROOT / "runs" / datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    with browser_context(headless=False) as ctx:
        page = ctx.new_page()
        if start != "about:blank":
            page.goto(start, wait_until="domcontentloaded")

        print("\n  A browser window is open and it is yours.")
        print("  Log in, click through, get to the application form.")
        print("  Anything you type is kept — this profile persists between runs.\n")

        while True:
            input("  Press Enter when the form is on screen (or Ctrl-C to quit). > ")

            snapshot = probe_combobox_options(page, extract_snapshot(page))
            if not snapshot.fields:
                print("  No form fields found on this page. Navigate further and try again.\n")
                continue

            print(f"  Found {len(snapshot.fields)} fields on {page.url[:70]}")
            plan = build_plan(client, snapshot, profile)
            report = execute_plan(page, snapshot, plan)

            shot = run_dir / f"page{len(list(run_dir.glob('*.png'))) + 1}.png"
            page.screenshot(path=str(shot))
            show(snapshot, plan, report, str(shot))

            again = input("\n  Fill another page? [y to continue, Enter to finish] > ").strip().lower()
            if again != "y":
                break

        input("\n  Done. Finish and submit it yourself. Press Enter to close the browser. > ")

    print(f"  screenshots: {run_dir}")


if __name__ == "__main__":
    main()
