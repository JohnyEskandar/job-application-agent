"""The page loop.

**This agent cannot submit an application.** There is no submit callable, no
click on a submit control, and no code path that could add one without being
written on purpose. It fills what it can, stops when it reaches a page with a
submit button, and hands the browser to the human — who reviews, finishes the
remaining fields, and clicks the button themselves.

That is a deliberate product decision, not a limitation. An application cannot
be un-sent, and the value here is the typing, not the clicking.

Agent loops do not usually fail by giving a wrong answer. They fail by never
terminating. Hence the two guards.
"""

import re
from dataclasses import dataclass, field as dc_field

from job_agent.extract import extract_snapshot, probe_combobox_options
from job_agent.fill import execute_plan

CONFIRMATION_WORDS = re.compile(
    r"thank you for applying|application (has been )?(submitted|received)|"
    r"we (have )?received your application",
    re.I,
)

# Below this many editable fields, a page carrying an "Apply" button is a job
# posting rather than an application form — the button navigates to the form.
LANDING_PAGE_MAX_FIELDS = 3

EDITABLE = (
    "input:not([type=hidden]):not([type=submit]):not([type=button]), "
    "textarea, select, [role=combobox], [role=textbox]"
)


@dataclass
class FlowResult:
    # ready_for_human = filled as far as it can; the human finishes and submits
    outcome: str                       # ready_for_human | needs_human | guard_tripped
    pages_visited: int = 0
    reports: list = dc_field(default_factory=list)
    detail: str | None = None


def is_landing_page(snapshot) -> bool:
    """A job posting with an Apply button, rather than an application form.

    The discriminator is the field count. "Apply Now" beside a single resume
    upload navigates to the form; "Apply" at the end of fourteen filled fields
    sends the application. Same word, opposite meanings.
    """
    return bool(snapshot.apply_buttons) and len(snapshot.fields) < LANDING_PAGE_MAX_FIELDS


def classify_page(page) -> str:
    if page.locator("input[type=password]").count():
        return "login"

    editable = page.locator(EDITABLE).count()
    text = page.locator("body").inner_text()

    if not editable and CONFIRMATION_WORDS.search(text):
        return "confirmation"
    if editable:
        return "form"
    return "unknown"


# Consent and cookie dialogs sit on top of the page and swallow every click.
# Only these words are ever clicked, and only inside a dialog — an allowlist,
# so an overlay dismisser can never press Submit, Delete, or Apply.
CONSENT_WORDS = re.compile(
    r"^(ok|okay|accept|accept all|i accept|agree|i agree|got it|understood|"
    r"allow|allow all|dismiss|close|continue to site)$",
    re.I,
)


def dismiss_overlays(page, rounds: int = 3) -> int:
    """Close consent/cookie dialogs blocking the page. Returns how many closed.

    NVIDIA's Eightfold posting opens a privacy agreement dialog that intercepts
    pointer events, so every click times out with a confusing "element is
    visible, enabled and stable" log while nothing happens.
    """
    closed = 0
    for _ in range(rounds):
        dialogs = page.locator("[role=dialog], [role=alertdialog]")
        if not dialogs.count():
            return closed
        acted = False
        for i in range(dialogs.count()):
            dialog = dialogs.nth(i)
            # Deliberately NOT gated on dialog.is_visible(). NVIDIA's privacy
            # backdrop reports as not visible to Playwright while still
            # intercepting every pointer event on the page — so a visibility
            # check skips exactly the overlay that is blocking you.
            for button in dialog.locator("button, [role=button], a").all():
                text = (button.inner_text() or "").strip()
                if not (text and CONSENT_WORDS.match(text)):
                    continue
                for attempt in (dict(timeout=2500), dict(timeout=2500, force=True)):
                    try:
                        button.click(**attempt)
                        closed += 1
                        acted = True
                        page.wait_for_timeout(400)
                        break
                    except Exception:
                        continue
                break
        if not acted:
            return closed
    return closed


def _click_first(page, patterns) -> bool:
    for pattern in patterns:
        for role in ("button", "link"):
            candidates = page.get_by_role(role, name=re.compile(pattern, re.I))
            if not candidates.count():
                continue
            try:
                candidates.first.click(timeout=10000)
            except Exception:
                # Something is covering it, or it is not really clickable.
                # Never let this crash the run — the browser may hold work the
                # human typed by hand.
                continue
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(400)
            return True
    return False


def run_application(
    page,
    *,
    planner,
    on_page=None,
    max_pages: int = 12,
    max_repeats: int = 3,
) -> FlowResult:
    """Fill the application as far as it can, then stop.

    `planner(snapshot) -> FillPlan` decides values; `on_page(snapshot, plan,
    report)` is an optional callback for reporting progress. Neither can
    submit — there is nothing here to submit with.
    """
    seen: dict[str, int] = {}
    reports = []
    pages = 0

    while pages < max_pages:
        # Consent dialogs swallow clicks. Clear them before doing anything.
        dismiss_overlays(page)

        kind = classify_page(page)

        if kind == "login":
            return FlowResult("needs_human", pages, reports, "login required")
        if kind == "confirmation":
            # We never submit, so reaching this means the human already did.
            return FlowResult("ready_for_human", pages, reports, "already submitted")
        if kind == "unknown":
            return FlowResult("needs_human", pages, reports, "could not classify page")

        seen[page.url] = seen.get(page.url, 0) + 1
        if seen[page.url] > max_repeats:
            return FlowResult("guard_tripped", pages, reports, f"revisited {page.url}")

        pages += 1
        snapshot = extract_snapshot(page)
        # Discover what the dropdowns actually offer before planning — a
        # planner choosing against options=[] is guessing at wording.
        snapshot = probe_combobox_options(page, snapshot)
        plan = planner(snapshot)
        report = execute_plan(page, snapshot, plan)
        reports.append(report)

        if on_page is not None:
            on_page(snapshot, plan, report)

        # An "Apply" button on a page with almost no fields is navigation to
        # the real form, not a way to send an application. NVIDIA's Eightfold
        # posting page is exactly this: one resume upload and an "Apply Now".
        if is_landing_page(snapshot):
            if _click_first(page, [r"\bapply\b"]):
                continue
            return FlowResult(
                "needs_human", pages, reports,
                "looks like a posting page but the apply control could not be followed",
            )

        # A page with a submit control is the end of the agent's job. It fills;
        # the human submits.
        if snapshot.submit_buttons or snapshot.apply_buttons:
            return FlowResult(
                "ready_for_human", pages, reports,
                f"filled and stopped. Submit it yourself with the "
                f"{(snapshot.submit_buttons or snapshot.apply_buttons)[0]!r} button.",
            )

        if not _click_first(page, [r"\bnext\b", r"\bcontinue\b"]):
            return FlowResult("ready_for_human", pages, reports, "no way to advance")

    return FlowResult("guard_tripped", pages, reports, f"hit the {max_pages}-page cap")
