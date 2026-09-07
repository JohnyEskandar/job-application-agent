"""Open a site in the persistent profile and wait while you log in by hand.

Run:  python scripts/login_once.py https://www.linkedin.com/login

Log in in the window that opens, then press Enter here. The session is saved
into browser-profile/ and survives process restarts.
"""

import sys

from job_agent.browser import DEFAULT_PROFILE_DIR, browser_context


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python scripts/login_once.py <url>")
    url = sys.argv[1]

    with browser_context(headless=False) as ctx:
        page = ctx.new_page()
        page.goto(url)
        print(f"\nOpened {url}")
        print("Log in in the browser window, then press Enter here.")
        input()
        print(f"Saved into {DEFAULT_PROFILE_DIR}")


if __name__ == "__main__":
    main()
