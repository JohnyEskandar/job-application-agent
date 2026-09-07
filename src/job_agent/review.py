"""The handoff summary.

Everything the agent filled, shown with where each value came from, plus
everything it refused to answer. The agent cannot submit — this is what it
hands you before you take over the browser and finish.
"""

from job_agent.models import FillPlan, FillReport, FormSnapshot

# Deliberately no "submit". The agent has no ability to submit an application;
# this dict exists so that fact is visible in code, not just in a comment.
VALID_DECISIONS: dict[str, str] = {}


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
        if result and result.outcome == "normalized":
            status = f"   (site reformatted to {result.observed!r})"
        elif result and result.outcome != "verified":
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
    lines.append("  The browser is open and it is yours now.")
    lines.append("  Finish the fields above, check the rest, and submit it yourself.")
    lines.append("  This agent cannot submit — by design.")
    return "\n".join(lines)


def show(snapshot: FormSnapshot, plan: FillPlan, report: FillReport, screenshot: str) -> None:
    """Print the handoff summary. Asks nothing, decides nothing."""
    print(render_review(snapshot, plan, report, screenshot))
