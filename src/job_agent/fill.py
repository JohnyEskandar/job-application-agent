"""Execute a FillPlan against a live page, verifying every write.

The model produced the plan. This module does the typing, and it trusts
nothing: every value is read back after being written. A fill() that silently
reverts — routine on React-controlled inputs — would otherwise submit a blank
field with no error anywhere.
"""

from job_agent.extract import locator_for
from job_agent.models import (
    FieldResult,
    FillPlan,
    FillReport,
    FormField,
    FormSnapshot,
    PlannedField,
)

TEXTUAL_KINDS = {"text", "textarea", "email", "tel", "number", "url", "date"}


def _write(page, locator, field: FormField, value) -> None:
    if field.kind in TEXTUAL_KINDS:
        locator.fill(str(value))
    elif field.kind == "select":
        locator.select_option(label=str(value))
    elif field.kind == "checkbox":
        locator.set_checked(bool(value))
    elif field.kind == "radio":
        locator.check()
    else:
        raise NotImplementedError(f"no writer for kind={field.kind}")


def _read_back(page, locator, field: FormField) -> str:
    if field.kind in {"checkbox", "radio"}:
        return "true" if locator.is_checked() else "false"
    return locator.input_value()


def _matches(field: FormField, intended: str, observed: str) -> bool:
    if field.kind == "select":
        # a <select> reports its VALUE; the plan names the visible LABEL
        return observed.strip().lower() == intended.strip().lower()
    return observed.strip() == intended.strip()


def execute_plan(page, snapshot: FormSnapshot, plan: FillPlan) -> FillReport:
    by_id = {f.field_id: f for f in snapshot.fields}
    results = [
        _execute_one(page, by_id.get(planned.field_id), planned) for planned in plan.fields
    ]
    return FillReport(results=results)


def _execute_one(page, field: FormField | None, planned: PlannedField) -> FieldResult:
    intended = str(planned.value)

    if field is None:
        return FieldResult(
            field_id=planned.field_id,
            outcome="error",
            intended=intended,
            detail="field_id is not on this page",
        )

    # The planner should never plan one of these. If it somehow does, refuse.
    if field.kind == "attention_check":
        return FieldResult(
            field_id=planned.field_id,
            outcome="skipped",
            intended=intended,
            detail="attention check — only a human answers this",
        )

    locator = locator_for(page, field)

    try:
        _write(page, locator, field, planned.value)
    except Exception as exc:
        return FieldResult(
            field_id=planned.field_id,
            outcome="error",
            intended=intended,
            detail=f"{type(exc).__name__}: {exc}"[:200],
        )

    try:
        observed = _read_back(page, locator, field)
    except Exception as exc:
        return FieldResult(
            field_id=planned.field_id,
            outcome="error",
            intended=intended,
            detail=f"could not read back: {type(exc).__name__}: {exc}"[:200],
        )

    return FieldResult(
        field_id=planned.field_id,
        outcome="verified" if _matches(field, intended, observed) else "mismatch",
        intended=intended,
        observed=observed,
    )
