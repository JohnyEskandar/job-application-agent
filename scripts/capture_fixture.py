"""Save a live application form as a test fixture.

Run:  python scripts/capture_fixture.py <url> tests/fixtures/name.html

Navigates, waits for the form to render, strips scripts, writes the file.
Fills nothing and submits nothing.
"""

import sys
from pathlib import Path

from job_agent.browser import browser_context
from job_agent.fixtures import capture


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: python scripts/capture_fixture.py <url> <out.html>")
    url, out = sys.argv[1], Path(sys.argv[2])

    with browser_context(headless=True) as ctx:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        capture(page, out)

    size = out.stat().st_size
    print(f"wrote {out} ({size // 1024} KB)")
    if "<script" in out.read_text().lower():
        raise SystemExit("ERROR: scripts survived — fixture will wipe itself on reload")


if __name__ == "__main__":
    main()
