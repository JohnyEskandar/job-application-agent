"""Find out exactly what a site's resume parser gets wrong.

Run:  python scripts/resume_parse_check.py <apply-url> [--headless]

Uploads docs/resume.pdf, waits for the site to parse it, re-extracts the form,
and compares every prefilled value against the profile.

It uploads and reads. It NEVER clicks submit — there is no submit call in this
file, deliberately.
"""

import sys
import time

from job_agent.browser import browser_context
from job_agent.extract import extract_snapshot
from job_agent.profile import load_profile

# What we expect the parser to produce, keyed by the label it should land under.
def expectations(profile) -> dict[str, str]:
    p = profile
    return {
        "First name": p.identity.first_name,
        "Last name": p.identity.last_name,
        "Email": p.identity.email,
        "Phone number": p.identity.phone,
        "LinkedIn Link": p.links.linkedin or "",
        "Website link": p.links.portfolio or "",
        "Location": f"{p.location.city}, {p.location.state}",
    }


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python scripts/resume_parse_check.py <url> [--headless]")
    url = sys.argv[1]
    headless = "--headless" in sys.argv

    profile = load_profile()
    resume = profile.documents.resume if profile.documents else "docs/resume.pdf"
    expected = expectations(profile)

    with browser_context(headless=headless) as ctx:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

        before = extract_snapshot(page)
        print(f"before upload: {len(before.fields)} fields, "
              f"{sum(1 for f in before.fields if f.current_value)} prefilled\n")

        uploads = page.locator("input[type=file]")
        print(f"uploading {resume} to the first of {uploads.count()} file inputs...")
        uploads.first.set_input_files(resume)

        # give the site time to parse and repaint
        for _ in range(12):
            time.sleep(1)
            if any(f.current_value for f in extract_snapshot(page).fields):
                break

        page.wait_for_timeout(3000)
        after = extract_snapshot(page)

        print(f"\nafter upload: {len(after.fields)} fields, "
              f"{sum(1 for f in after.fields if f.current_value)} prefilled\n")

        print(f"{'FIELD':28} {'PARSER PRODUCED':34} {'PROFILE SAYS':30} VERDICT")
        print("-" * 108)
        for field in after.fields:
            got = (field.current_value or "").strip()
            if not got:
                continue
            want = expected.get(field.accessible_name)
            if want is None:
                verdict = "no profile fact — needs a human"
            elif got == want:
                verdict = "match"
            else:
                verdict = "WRONG — must overwrite"
            print(f"{field.accessible_name[:26]:28} {got[:32]:34} {str(want)[:28]:30} {verdict}")

        if headless:
            return
        print("\nBrowser left open so you can look. Press Enter to close.")
        input()


if __name__ == "__main__":
    main()
