"""Fill whatever application form you have navigated to.

Run:  python scripts/fill_here.py [starting-url]
      python scripts/fill_here.py [url] --auto   # fill and advance without asking

For sites the agent cannot reach on its own — anything behind a login, an
account creation step, or a different flow shape like Eightfold's
upload-a-resume-and-we-generate-the-application.

You drive the browser. Press Enter when a form is on screen. It reads
whichever tab you are actually looking at, fills what it can, and hands the
browser straight back. It still cannot submit.

The persistent profile means a login done here survives into later runs.
"""

import sys
from datetime import datetime

import anthropic

from job_agent.browser import browser_context
from job_agent.config import PROJECT_ROOT, require_api_key
from job_agent.extract import extract_snapshot, probe_combobox_options
from job_agent.flow import advance
from job_agent.fill import execute_plan
from job_agent.plan import build_plan
from job_agent.profile import load_profile
from job_agent.review import show


def live_pages(ctx):
    return [p for p in ctx.pages if not p.is_closed()]


def choose_page(ctx, remembered=None):
    """Return the tab the human is looking at, asking only when it is unclear.

    Sites routinely open the real application in a new tab, so holding the page
    object we created reads a stale page and looks like nothing is happening.
    But re-asking on every single page of a six-page form is its own kind of
    misery, so the choice is remembered until that tab closes.
    """
    pages = [p for p in live_pages(ctx) if p.url not in ("about:blank", "")]
    if not pages:
        return None
    if remembered is not None and remembered in pages:
        return remembered
    if len(pages) == 1:
        return pages[0]

    print("\n  Several tabs are open:")
    for i, p in enumerate(pages, 1):
        try:
            print(f"    [{i}] {p.title()[:50]:52} {p.url[:56]}")
        except Exception:
            print(f"    [{i}] (unreadable) {p.url[:56]}")
    choice = input(f"  Which one has the form? [1-{len(pages)}, Enter = last] > ").strip()
    picked = pages[int(choice) - 1] if choice.isdigit() and 1 <= int(choice) <= len(pages) else pages[-1]
    print("  (remembering this tab — it will not ask again unless it closes)")
    return picked


def main() -> None:
    require_api_key()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    start = args[0] if args else None
    auto = "--auto" in sys.argv

    profile = load_profile()
    client = anthropic.Anthropic()
    run_dir = PROJECT_ROOT / "runs" / datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    with browser_context(headless=False) as ctx:
        page = ctx.new_page()
        if start:
            page.goto(start, wait_until="domcontentloaded")

        print("\n  A browser window is open and it is yours.")
        print("  Log in, click through, get to the application form.")
        print("  New tabs are fine — it reads whichever tab you point it at.")
        if auto:
            print("  --auto: it will fill and advance on its own once you press Enter once.")
        print()

        chosen = None
        filled_any = False

        while True:
            # --auto only takes over AFTER a page has been filled. Before that
            # you are still navigating, and giving up on the first empty page
            # would end the run before it started.
            if not (auto and filled_any):
                try:
                    input("  Press Enter when a form is on screen (Ctrl-C to quit). > ")
                except (KeyboardInterrupt, EOFError):
                    break

            if not live_pages(ctx):
                print("  Every tab is closed. Nothing left to read.\n")
                break

            target = choose_page(ctx, chosen)
            chosen = target
            if target is None:
                print("  No loaded page found. Navigate somewhere and try again.\n")
                continue

            try:
                print(f"\n  Reading: {target.title()[:64]}")
                print(f"           {target.url[:78]}")
                snapshot = extract_snapshot(target)
                if snapshot.fields:
                    # Only steal focus once there is actually work to do here.
                    target.bring_to_front()
                    snapshot = probe_combobox_options(target, snapshot)
            except Exception as exc:
                print(f"  Could not read that tab ({type(exc).__name__}). Try again.\n")
                continue

            if not snapshot.fields:
                if auto and filled_any:
                    print("  No form fields here — looks like the end. Stopping.\n")
                    break
                print("  No form fields on that page. Navigate to the form and try again.")
                print("  (forgetting the tab choice, so it will ask again)\n")
                chosen = None
                continue

            filled_any = True
            print(f"  {len(snapshot.fields)} fields found. Planning...\n")
            plan = build_plan(client, snapshot, profile)
            report = execute_plan(target, snapshot, plan)

            shot = run_dir / f"page{len(list(run_dir.glob('*.png'))) + 1}.png"
            try:
                target.screenshot(path=str(shot))
            except Exception:
                pass
            show(snapshot, plan, report, str(shot))

            if auto:
                if advance(target):
                    target.wait_for_timeout(2000)
                    print(f"\n  advanced to page {len(list(run_dir.glob('*.png'))) + 1}\n")
                    continue
                print("\n  No Continue button found — this is probably the last page.")
                break

            print("\n  [c] click Continue / Save and continue, then fill the next page")
            print("  [m] I will navigate myself — fill again when I press Enter")
            print("  [Enter] finished")
            again = input("  > ").strip().lower()

            if again == "c":
                if advance(target):
                    target.wait_for_timeout(1500)
                    print(f"  advanced to: {target.url[:74]}")
                    continue
                print("  Could not find a Continue button. Click it yourself, then press m.")
                continue
            if again == "m":
                continue
            break

        if live_pages(ctx):
            try:
                input("\n  Done. Finish and submit it yourself. Press Enter to close. > ")
            except (KeyboardInterrupt, EOFError):
                pass

    print(f"  screenshots: {run_dir}")


if __name__ == "__main__":
    main()
