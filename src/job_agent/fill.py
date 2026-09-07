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


def _is_input(locator) -> bool:
    return locator.evaluate("e => e.tagName.toLowerCase()") == "input"


def combobox_value(locator) -> str:
    """Read a combobox regardless of how it is built.

    Three shapes, three places the value lives:
      - <div role=combobox>: the value IS its inner text.
      - <input role=combobox>: the value is in .value.
      - react-select style: the input is CLEARED after you pick, and the
        selection renders in a sibling element. .value reads "" on success,
        which is indistinguishable from a failed write.

    Reading the wrong place is how Greenhouse looked like nineteen failed
    writes when the writes had actually landed.
    """
    if not _is_input(locator):
        return (locator.inner_text() or "").strip()

    typed = (locator.input_value() or "").strip()
    if typed:
        return typed

    # Empty input: look for a rendered selection beside it.
    return (
        locator.evaluate(
            """e => {
                const placeholder = /^(select\\.{0,3}|choose\\.{0,3}|)$/i;
                let n = e.parentElement;
                for (let i = 0; i < 3 && n; i++, n = n.parentElement) {
                    // react-select and friends label the chosen value this way
                    const picked = n.querySelector(
                        '[class*=singleValue], [class*=single-value], [class*=selectedValue]'
                    );
                    if (picked) {
                        const t = (picked.innerText || '').trim();
                        if (t && !placeholder.test(t)) return t;
                    }
                }
                return '';
            }"""
        )
        or ""
    ).strip()


def choose_in_custom_combobox(page, locator, value: str) -> None:
    """Set a combobox that is not a native <select>.

    Three shapes have to work:
      - <div role=combobox>: click to open, click the option.
      - <input role=combobox>: click, type, wait for options, click one.
      - typeahead with async options (Greenhouse): the option list arrives from
        the server after the keystrokes, so a fixed short wait finds nothing
        and the widget clears itself on blur — which reads back as "".

    Never leave text typed into a typeahead without committing a selection.
    """
    wanted = str(value).strip()

    # Already correct: leave it alone rather than reopening it.
    if combobox_value(locator) == wanted:
        return

    locator.click()

    if _is_input(locator):
        locator.fill(wanted)

    # Wait for options to actually exist. Async typeaheads need real time.
    options = page.get_by_role("option")
    try:
        options.first.wait_for(state="visible", timeout=6000)
    except Exception:
        # No list appeared. For a plain typeahead the typed text may itself be
        # the answer; for a div-based control this is a genuine failure.
        if _is_input(locator):
            return
        raise RuntimeError(f"no option list appeared for {wanted!r}")

    page.wait_for_timeout(250)
    candidates = [
        (o, (o.inner_text() or "").strip())
        for o in options.all()
    ]
    candidates = [(o, t) for o, t in candidates if t]

    def pick():
        for o, t in candidates:                     # exact
            if t == wanted:
                return o
        for o, t in candidates:                     # case/punctuation-insensitive
            if _alnum(t) == _alnum(wanted):
                return o
        for o, t in candidates:                     # containment, either way
            a, b = _alnum(t), _alnum(wanted)
            if len(b) > 6 and (b in a or a in b):
                return o
        if len(candidates) == 1:                    # only one thing to choose
            return candidates[0][0]
        return None

    chosen = pick()
    if chosen is None:
        # Do not leave uncommitted text sitting in a typeahead — it disappears
        # on blur and reads back empty, which looks like the write silently
        # failed rather than like no option matched.
        if _is_input(locator):
            locator.fill("")
        raise RuntimeError(f"no option matching {wanted!r} among {[t for _, t in candidates][:8]}")

    chosen.click()
    page.wait_for_timeout(300)


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
        return combobox_value(locator)
    if field.kind == "file":
        # the intended value is a path, but the only thing worth verifying is
        # that a file actually got attached
        return "attached" if locator.evaluate("e => e.files && e.files.length") else ""
    return locator.input_value()


def _alnum(text: str) -> str:
    return "".join(c for c in text.lower() if c.isalnum())


def _compare(field: FormField, intended: str, observed: str) -> str:
    """verified | normalized | mismatch."""
    if field.kind == "file":
        # a path can never equal "attached"; the attachment is the success
        return "verified" if observed == "attached" else "mismatch"

    if field.kind == "select":
        # a <select> reports its VALUE; the plan names the visible LABEL
        return "verified" if observed.strip().lower() == intended.strip().lower() else "mismatch"

    if observed.strip() == intended.strip():
        return "verified"

    # Differs only in punctuation or spacing: the form applied an input mask
    # or trimmed something. The content survived, so this is not a failure.
    if _alnum(observed) == _alnum(intended) and _alnum(intended):
        return "normalized"

    return "mismatch"


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

    outcome = _compare(field, intended, observed)
    return FieldResult(
        field_id=planned.field_id,
        outcome=outcome,
        intended=intended,
        observed=observed,
        detail="form reformatted the value; content unchanged" if outcome == "normalized" else None,
    )
