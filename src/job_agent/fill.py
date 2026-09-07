"""Execute a FillPlan against a live page, verifying every write.

The model produced the plan. This module does the typing, and it trusts
nothing: every value is read back after being written. A fill() that silently
reverts — routine on React-controlled inputs — would otherwise submit a blank
field with no error anywhere.
"""

from pathlib import Path

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


def upload_file(page, locator, path) -> None:
    """Attach a file to a file input.

    File inputs are routinely hidden behind a styled button, so this targets
    the underlying <input type=file> rather than whatever is visible.
    """
    locator.set_input_files(str(Path(path)))


def choose_in_custom_combobox(page, locator, value: str) -> None:
    """Open a div-based combobox and click the matching option.

    select_option() only works on a native <select>. Rippling — and most
    component libraries — render dropdowns as divs, so the only way in is to
    drive it the way a person would: click to open, click the option.
    """
    locator.click()
    option = page.get_by_role("option", name=str(value), exact=True)
    option.wait_for(state="visible", timeout=5000)
    option.click()


def _write(page, locator, field: FormField, value) -> None:
    if field.kind in TEXTUAL_KINDS:
        locator.fill(str(value))
    elif field.kind == "select":
        locator.select_option(label=str(value))
    elif field.kind == "checkbox":
        locator.set_checked(bool(value))
    elif field.kind == "radio":
        locator.check()
    elif field.kind == "combobox":
        choose_in_custom_combobox(page, locator, value)
    elif field.kind == "file":
        upload_file(page, locator, value)
    else:
        raise NotImplementedError(f"no writer for kind={field.kind}")


def _read_back(page, locator, field: FormField) -> str:
    if field.kind in {"checkbox", "radio"}:
        return "true" if locator.is_checked() else "false"
    if field.kind == "combobox":
        # a div has no value — what it displays IS its value
        return (locator.inner_text() or "").strip()
    if field.kind == "file":
        # the intended value is a path, but the only thing worth verifying is
        # that a file actually got attached
        return "attached" if locator.evaluate("e => e.files && e.files.length") else ""
    return locator.input_value()


def _matches(field: FormField, intended: str, observed: str) -> bool:
    if field.kind == "file":
        # a path can never equal "attached"; the attachment is the success
        return observed == "attached"
    if field.kind == "select":
        # a <select> reports its VALUE; the plan names the visible LABEL
        return observed.strip().lower() == intended.strip().lower()
    return observed.strip() == intended.strip()


def order_for_execution(snapshot: FormSnapshot, planned: list[PlannedField]) -> list[PlannedField]:
    """File uploads first.

    The site parses the resume to prefill fields. Uploading first means our
    values are written afterwards and win. Uploading last would let the parser
    overwrite everything we just typed.
    """
    by_id = {f.field_id: f for f in snapshot.fields}

    def is_file(p: PlannedField) -> bool:
        field = by_id.get(p.field_id)
        return bool(field and field.kind == "file")

    return [p for p in planned if is_file(p)] + [p for p in planned if not is_file(p)]


def execute_plan(
    page, snapshot: FormSnapshot, plan: FillPlan, *, retries: int = 1
) -> FillReport:
    by_id = {f.field_id: f for f in snapshot.fields}
    results: list[FieldResult] = []

    for planned in order_for_execution(snapshot, plan.fields):
        field = by_id.get(planned.field_id)
        result = _execute_one(page, field, planned)

        # A mismatch is often a re-render racing the write. Pausing before the
        # retry matters — an immediate one loses the same race.
        if result.outcome == "mismatch" and retries > 0:
            page.wait_for_timeout(300)
            result = _execute_one(page, field, planned)

        results.append(result)

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
