"""Browser lifecycle. No LLM in this module, deliberately.

Uses a PERSISTENT context: Chromium keeps cookies, localStorage, and session
state in a directory on disk, so a login survives process restarts. That is
what makes unattended runs possible on sites that require an account.
"""

from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import sync_playwright

from job_agent.config import PROJECT_ROOT

DEFAULT_PROFILE_DIR = PROJECT_ROOT / "browser-profile"


@contextmanager
def browser_context(headless: bool = False, profile_dir: Path | None = None):
    """Yield a Playwright BrowserContext backed by a persistent profile.

    headless=False by default: logging in and watching a form get filled both
    need a visible window. Tests pass headless=True.

    Note this returns a BrowserContext, not a Browser —
    launch_persistent_context skips the Browser object entirely.
    """
    profile_dir = Path(profile_dir) if profile_dir is not None else DEFAULT_PROFILE_DIR
    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            viewport={"width": 1400, "height": 1000},
        )
        try:
            yield context
        finally:
            context.close()
