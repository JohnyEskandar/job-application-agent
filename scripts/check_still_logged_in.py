"""Reopen a site in a NEW process and screenshot what we land on.

Run:  python scripts/check_still_logged_in.py https://www.linkedin.com/feed
      python scripts/check_still_logged_in.py <url> --headless

If the persistent profile works, this shows a logged-in page without any
credentials being entered.
"""

import sys
from datetime import datetime
from pathlib import Path

from job_agent.browser import browser_context
from job_agent.config import PROJECT_ROOT


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("usage: python scripts/check_still_logged_in.py <url> [--headless]")
    url = args[0]
    headless = "--headless" in sys.argv

    out_dir = PROJECT_ROOT / "runs" / datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    shot = out_dir / "logged_in_check.png"

    with browser_context(headless=headless) as ctx:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        page.screenshot(path=str(shot), full_page=False)
        print(f"landed on: {page.url}")
        print(f"title:     {page.title()}")
        print(f"screenshot: {shot}")


if __name__ == "__main__":
    main()
