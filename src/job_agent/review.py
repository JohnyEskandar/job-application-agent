"""The human approval gate.

Everything the agent is about to submit, shown with where each value came
from, so a wrong answer is visible before it is permanent. An application
cannot be un-sent; this is the one place in the design where convenience
loses.
"""

from job_agent.models import FillPlan, FillReport, FormSnapshot

VALID_DECISIONS = {"s": "submit", "e": "edit", "o": "open", "a": "abandon"}


def render_review(snapshot: FormSnapshot, plan: FillPlan, report: FillReport, screenshot: str) -> str:
    by_id = {f.field_id: f for f in snapshot.fields}
    outcomes = {r.field_id: r for r in report.results}
    lines: list[str] = []

    lines.append("")
    lines.append(f"  {snapshot.page_title}   ({snapshot.ats or 'unknown ATS'})")
    lines.append(f"  {len(plan.fields)} fields filled, {len(plan.unresolved)} left for you")
    lines.append("")

    for planned in plan.fields:
        field = by_id.get(planned.field_id)
        name = field.accessible_name if field else planned.field_id
        result = outcomes.get(planned.field_id)
        status = ""
        if result and result.outcome != "verified":
            status = f"   FAILED ({result.outcome}: saw {result.observed!r})"
        flag = "   <-- REVIEW" if planned.source == "generated" else ""
        lines.append(
            f"  {planned.source:11} {name[:34]:36} {str(planned.value)[:40]}{flag}{status}"
        )

    if plan.unresolved:
        lines.append("")
        lines.append("  NEEDS YOU:")
        for u in plan.unresolved:
            field = by_id.get(u.field_id)
            name = field.accessible_name if field else u.field_id
            lines.append(f"    {name[:34]:36} {u.reason[:60]}")

    lines.append("")
    lines.append(f"  Screenshot: {screenshot}")
    lines.append("")
    lines.append("  [s]ubmit   [e]dit a field   [o]pen the browser   [a]bandon")
    return "\n".join(lines)


def ask(snapshot: FormSnapshot, plan: FillPlan, report: FillReport, screenshot: str) -> str:
    """Print the review and block until a human types a decision.

    No default, no timeout. Pressing Enter alone re-prompts rather than
    accepting anything.
    """
    print(render_review(snapshot, plan, report, screenshot))
    while True:
        choice = input("  > ").strip().lower()
        if choice in VALID_DECISIONS:
            return VALID_DECISIONS[choice]
        print("  please type s, e, o, or a")
