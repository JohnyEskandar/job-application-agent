"""Capture real form HTML in a form that survives being reloaded.

ATS pages are single-page apps. Saving page.content() gives you the rendered
DOM, which is what we want — but reloading it from file:// lets the framework
hydrate, fail to reach its API, and replace everything you captured with an
error state or an empty shell.

Stripping <script> tags freezes the DOM exactly as it was.
"""

import re
from pathlib import Path

_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)


def strip_scripts(html: str) -> str:
    """Remove every <script> element, including its contents."""
    return _SCRIPT.sub("", html)


def capture(page, path: Path) -> Path:
    """Save the page's current DOM as a reload-safe fixture."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(strip_scripts(page.content()))
    return path
