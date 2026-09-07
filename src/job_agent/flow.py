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


def _click_first(page, patterns) -> bool:
    for pattern in patterns:
        for role in ("button", "link"):
            candidates = page.get_by_role(role, name=re.compile(pattern, re.I))
            if candidates.count():
                candidates.first.click()
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

        # A page with a submit control is the end of the agent's job. It fills;
        # the human submits.
        if snapshot.submit_buttons:
            return FlowResult(
                "ready_for_human", pages, reports,
                f"filled and stopped. Submit it yourself with the "
                f"{snapshot.submit_buttons[0]!r} button.",
            )

        if not _click_first(page, [r"\bnext\b", r"\bcontinue\b"]):
            return FlowResult("ready_for_human", pages, reports, "no way to advance")

    return FlowResult("guard_tripped", pages, reports, f"hit the {max_pages}-page cap")
