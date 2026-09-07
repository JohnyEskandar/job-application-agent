"""The page loop.

Agent loops do not usually fail by giving a wrong answer. They fail by never
terminating. Hence the two guards.

`submit` is injected rather than imported, so a test can prove the loop never
calls it without approval — and so production has exactly one call site.
"""

import re
from dataclasses import dataclass, field as dc_field

from job_agent.extract import extract_snapshot
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
    outcome: str                       # submitted | abandoned | needs_human | guard_tripped
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
    decide,
    submit=None,
    max_pages: int = 12,
    max_repeats: int = 3,
) -> FlowResult:
    """Walk the application until it is submitted, abandoned, or guarded out.

    `planner(snapshot) -> FillPlan`, `decide(snapshot, plan, report) -> str`,
    and `submit(page)` are injected so the whole loop is testable offline and
    so submission has exactly one caller.
    """
    seen: dict[str, int] = {}
    reports = []
    pages = 0

    while pages < max_pages:
        kind = classify_page(page)

        if kind == "login":
            return FlowResult("needs_human", pages, reports, "login required")
        if kind == "confirmation":
            return FlowResult("submitted", pages, reports, "confirmation page reached")
        if kind == "unknown":
            return FlowResult("needs_human", pages, reports, "could not classify page")

        seen[page.url] = seen.get(page.url, 0) + 1
        if seen[page.url] > max_repeats:
            return FlowResult("guard_tripped", pages, reports, f"revisited {page.url}")

        pages += 1
        snapshot = extract_snapshot(page)
        plan = planner(snapshot)
        report = execute_plan(page, snapshot, plan)
        reports.append(report)

        if snapshot.submit_buttons:
            decision = decide(snapshot, plan, report)
            if decision == "submit":
                if submit is not None:
                    submit(page)
                return FlowResult("submitted", pages, reports)
            return FlowResult("abandoned", pages, reports, f"decision={decision}")

        if not _click_first(page, [r"\bnext\b", r"\bcontinue\b"]):
            return FlowResult("needs_human", pages, reports, "no way to advance")

    return FlowResult("guard_tripped", pages, reports, f"hit the {max_pages}-page cap")
