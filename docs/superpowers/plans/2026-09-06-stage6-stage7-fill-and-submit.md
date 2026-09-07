# Stage 6 + Stage 7: Filling the Form and the Approval Gate

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute a `FillPlan` against a real page, verify every value actually landed, walk a multi-page wizard, and stop at a review screen that a human must approve before anything is submitted.

**Architecture:** `fill.py` takes a plan and writes each value through `locator_for`, then **reads it back** — a write that silently reverts is the failure mode that matters on React forms. `flow.py` loops extract → plan → fill → advance, under hard guards. `review.py` renders what is about to be submitted and returns a decision. `submit` is called from exactly one place, only on an explicit approval.

**Tech Stack:** Python 3.14.7, `playwright` 1.62 (sync), `anthropic` 1.x, `pydantic` 2.x, `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-06-job-application-agent-design.md`

## Global Constraints

- **Nothing in this plan may submit without an explicit human approval.** There is no `--yes` flag, no timeout that defaults to submitting, and no code path from `fill` to `submit`. A test asserts the flow cannot submit without approval.
- **Every write is verified by reading it back.** An unverified write is a failure, not a success.
- **Résumé first.** Upload before filling, then overwrite every field the profile knows. A non-empty field is not a correct field (see the Stage 4/5 plan).
- **Selectors stay role-based** — `locator_for(page, field)`. Never `name` or `id`.
- Loop guards are mandatory: max 12 pages, max 3 visits to one URL. Agent loops fail by not terminating, not by being wrong.
- `runs/` holds screenshots of partly-filled applications. Gitignored, and it stays that way.
- Commit at the end of each task; suite green first.

## What Stage 4/5 handed over

Measured, not assumed:

- Rippling renders every dropdown as `<div role="combobox">`. `select_option()` **will not work** on them — they need click, type, click-the-option.
- The résumé parser prefills 7 contact fields, 3 of them differing from the profile.
- One `attention_check` field, which the planner always routes to the human. Stage 6 must never fill it.
- Five EEO comboboxes, all routed to the human.
- The live page showed 16 fields, the committed fixture 18. Resolve before trusting either.

---

### Task 1: Execute the simple field kinds, and verify them

**Files:**
- Modify: `src/job_agent/models.py`
- Create: `src/job_agent/fill.py`
- Test: `tests/test_fill.py`

**Interfaces:**
- Consumes: `extract.locator_for`, `models.FillPlan`, `models.FormSnapshot`
- Produces: `models.FillOutcome`, `models.FieldResult`, `models.FillReport`; `fill.execute_plan(page, snapshot, plan) -> FillReport`

- [ ] **Step 1: Add the result models to `src/job_agent/models.py`**

```python
FillOutcome = Literal["verified", "mismatch", "error", "skipped"]


class FieldResult(Strict):
    field_id: str
    outcome: FillOutcome
    intended: str
    observed: str | None = None
    detail: str | None = None


class FillReport(Strict):
    results: list[FieldResult] = Field(default_factory=list)

    @property
    def verified(self) -> list[FieldResult]:
        return [r for r in self.results if r.outcome == "verified"]

    @property
    def failures(self) -> list[FieldResult]:
        return [r for r in self.results if r.outcome in {"mismatch", "error"}]

    @property
    def ok(self) -> bool:
        return not self.failures
```

- [ ] **Step 2: Write the failing test**

`tests/test_fill.py`:

```python
from pathlib import Path

import pytest

from job_agent.browser import browser_context
from job_agent.extract import extract_snapshot
from job_agent.fill import execute_plan
from job_agent.models import FillPlan, PlannedField

FIXTURES = Path(__file__).parent / "fixtures"
SIMPLE = (FIXTURES / "simple_form.html").resolve().as_uri()


@pytest.fixture(scope="module")
def ctx():
    with browser_context(headless=True) as context:
        yield context


def plan_for(snapshot, name, value, source="profile"):
    field = next(f for f in snapshot.fields if f.accessible_name == name)
    return PlannedField(
        field_id=field.field_id, value=value, source=source, confidence=0.99, note="test"
    )


def test_a_text_field_is_written_and_verified(ctx):
    page = ctx.new_page()
    page.goto(SIMPLE)
    snap = extract_snapshot(page)
    report = execute_plan(page, snap, FillPlan(fields=[plan_for(snap, "First name", "Johny")]))

    assert report.ok
    assert report.results[0].outcome == "verified"
    assert page.input_value("#first_name") == "Johny"


def test_a_textarea_is_written_and_verified(ctx):
    page = ctx.new_page()
    page.goto(SIMPLE)
    snap = extract_snapshot(page)
    report = execute_plan(
        page, snap, FillPlan(fields=[plan_for(snap, "Why do you want this role?", "Because.")])
    )
    assert report.ok
    assert page.input_value("#cover") == "Because."


def test_a_native_select_is_chosen_and_verified(ctx):
    page = ctx.new_page()
    page.goto(SIMPLE)
    snap = extract_snapshot(page)
    report = execute_plan(
        page, snap, FillPlan(fields=[plan_for(snap, "How did you hear about us?", "Referral")])
    )
    assert report.ok
    assert page.input_value("#source") == "referral"


def test_a_value_that_will_not_stick_is_reported_as_mismatch(ctx):
    """The failure mode that matters: a write that silently reverts."""
    page = ctx.new_page()
    page.goto(SIMPLE)
    # make the field reject writes, the way a controlled React input does
    page.eval_on_selector(
        "#first_name",
        "el => el.addEventListener('input', () => { el.value = ''; })",
    )
    snap = extract_snapshot(page)
    report = execute_plan(page, snap, FillPlan(fields=[plan_for(snap, "First name", "Johny")]))

    assert not report.ok
    assert report.results[0].outcome == "mismatch"
    assert report.results[0].observed == ""


def test_a_plan_referencing_a_missing_field_is_an_error_not_a_crash(ctx):
    page = ctx.new_page()
    page.goto(SIMPLE)
    snap = extract_snapshot(page)
    bogus = PlannedField(
        field_id="f_99", value="x", source="profile", confidence=1.0, note="not on this page"
    )
    report = execute_plan(page, snap, FillPlan(fields=[bogus]))
    assert report.results[0].outcome == "error"


def test_attention_check_fields_are_never_filled_even_if_planned(ctx):
    """Belt and braces: the planner should never plan one, but if it does,
    the executor still refuses."""
    page = ctx.new_page()
    page.goto(SIMPLE)
    snap = extract_snapshot(page)
    field = next(f for f in snap.fields if f.accessible_name == "First name")
    object.__setattr__(field, "kind", "attention_check")
    planned = PlannedField(
        field_id=field.field_id, value="value", source="generated", confidence=1.0, note="x"
    )
    report = execute_plan(page, snap, FillPlan(fields=[planned]))
    assert report.results[0].outcome == "skipped"
    assert page.input_value("#first_name") == ""
```

- [ ] **Step 3: Run it and watch it fail**

Run: `pytest tests/test_fill.py -v`
Expected: `ModuleNotFoundError: No module named 'job_agent.fill'`

- [ ] **Step 4: Write `src/job_agent/fill.py`**

```python
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


def _write(locator, field: FormField, value) -> None:
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


def _read_back(locator, field: FormField) -> str:
    if field.kind == "checkbox":
        return "true" if locator.is_checked() else "false"
    if field.kind == "radio":
        return "true" if locator.is_checked() else "false"
    return locator.input_value()


def _verify(locator, field: FormField, intended: str) -> tuple[str, str]:
    observed = _read_back(locator, field)
    if observed.strip() == intended.strip():
        return "verified", observed
    return "mismatch", observed


def execute_plan(page, snapshot: FormSnapshot, plan: FillPlan) -> FillReport:
    by_id = {f.field_id: f for f in snapshot.fields}
    results: list[FieldResult] = []

    for planned in plan.fields:
        results.append(_execute_one(page, by_id.get(planned.field_id), planned))

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
        _write(locator, field, planned.value)
    except Exception as exc:
        return FieldResult(
            field_id=planned.field_id,
            outcome="error",
            intended=intended,
            detail=f"{type(exc).__name__}: {exc}"[:200],
        )

    try:
        outcome, observed = _verify(locator, field, intended)
    except Exception as exc:
        return FieldResult(
            field_id=planned.field_id,
            outcome="error",
            intended=intended,
            detail=f"could not read back: {type(exc).__name__}: {exc}"[:200],
        )

    return FieldResult(
        field_id=planned.field_id,
        outcome=outcome,
        intended=intended,
        observed=observed,
    )
```

- [ ] **Step 5: Run the tests and iterate**

Run: `pytest tests/test_fill.py -v`
Expected: 6 passed.

If `test_a_native_select_is_chosen_and_verified` fails, the fixture's option
label ("Referral") and value ("referral") differ — `select_option(label=...)`
is correct; `input_value()` returns the *value*. Assert on the value.

- [ ] **Step 6: Commit**

```bash
git add src/job_agent/models.py src/job_agent/fill.py tests/test_fill.py
git commit -m "feat: execute a FillPlan with read-back verification"
```

---

### Task 2: File uploads and custom comboboxes

The two kinds Rippling actually uses, and the two that `fill()` cannot handle.

**Files:**
- Create: `tests/fixtures/custom_combobox.html`
- Modify: `src/job_agent/fill.py`
- Test: `tests/test_fill_widgets.py`

**Interfaces:**
- Produces: `fill.upload_file(page, field, path)`, `fill.choose_in_custom_combobox(page, field, value)`

- [ ] **Step 1: Write `tests/fixtures/custom_combobox.html`**

Hand-written, so it may keep its script — the script-stripping rule applies to
*captured* SPA pages, not to fixtures we author. This mimics how Rippling
renders a dropdown: a div, not a select.

```html
<!doctype html>
<html>
  <head><title>Custom Widgets</title></head>
  <body>
    <label id="fav-label">Favourite colour</label>
    <div id="fav" role="combobox" aria-labelledby="fav-label" aria-expanded="false" tabindex="0">
      Select...
    </div>
    <ul id="fav-list" role="listbox" hidden>
      <li role="option" data-value="red">Red</li>
      <li role="option" data-value="blue">Blue</li>
    </ul>

    <label for="cv">Résumé</label>
    <input id="cv" type="file" />

    <script>
      const box = document.getElementById('fav');
      const list = document.getElementById('fav-list');
      box.addEventListener('click', () => {
        const open = box.getAttribute('aria-expanded') === 'true';
        box.setAttribute('aria-expanded', String(!open));
        list.hidden = open;
      });
      list.querySelectorAll('[role=option]').forEach(opt => {
        opt.addEventListener('click', () => {
          box.textContent = opt.textContent;
          box.dataset.value = opt.dataset.value;
          box.setAttribute('aria-expanded', 'false');
          list.hidden = true;
        });
      });
    </script>
  </body>
</html>
```

- [ ] **Step 2: Write the failing test**

`tests/test_fill_widgets.py`:

```python
from pathlib import Path

import pytest

from job_agent.browser import browser_context
from job_agent.extract import extract_snapshot
from job_agent.fill import choose_in_custom_combobox, execute_plan, upload_file
from job_agent.models import FillPlan, PlannedField

FIXTURES = Path(__file__).parent / "fixtures"
WIDGETS = (FIXTURES / "custom_combobox.html").resolve().as_uri()
RESUME = Path("profile.example.yaml").resolve()  # any real file will do


@pytest.fixture(scope="module")
def ctx():
    with browser_context(headless=True) as context:
        yield context


def test_a_div_based_combobox_can_be_set(ctx):
    page = ctx.new_page()
    page.goto(WIDGETS)
    snap = extract_snapshot(page)
    field = next(f for f in snap.fields if f.accessible_name == "Favourite colour")

    choose_in_custom_combobox(page, field, "Blue")

    assert page.locator("#fav").inner_text().strip() == "Blue"


def test_select_option_would_not_have_worked(ctx):
    """Documents why choose_in_custom_combobox exists at all."""
    page = ctx.new_page()
    page.goto(WIDGETS)
    with pytest.raises(Exception):
        page.locator("#fav").select_option("Blue")


def test_a_file_upload_is_verified_by_the_file_being_attached(ctx):
    page = ctx.new_page()
    page.goto(WIDGETS)
    snap = extract_snapshot(page)
    field = next(f for f in snap.fields if f.kind == "file")

    upload_file(page, field, RESUME)

    count = page.eval_on_selector("#cv", "e => e.files.length")
    assert count == 1


def test_execute_plan_routes_file_and_combobox_kinds(ctx):
    page = ctx.new_page()
    page.goto(WIDGETS)
    snap = extract_snapshot(page)
    combo = next(f for f in snap.fields if f.kind == "combobox")
    report = execute_plan(
        page,
        snap,
        FillPlan(fields=[PlannedField(
            field_id=combo.field_id, value="Red", source="profile", confidence=1.0, note="t"
        )]),
    )
    assert report.results[0].outcome == "verified"
```

- [ ] **Step 3: Run it and watch it fail**

Run: `pytest tests/test_fill_widgets.py -v`
Expected: `ImportError: cannot import name 'choose_in_custom_combobox'`

- [ ] **Step 4: Add the two writers to `src/job_agent/fill.py`**

```python
from pathlib import Path


def upload_file(page, field: FormField, path) -> None:
    """Attach a file to a file input.

    File inputs are routinely hidden behind a styled button, so this targets
    the underlying <input type=file> rather than whatever is visible.
    """
    page.locator("input[type=file]").nth(_file_index(page, field)).set_input_files(str(Path(path)))


def _file_index(page, field: FormField) -> int:
    """Which file input this field is, in DOM order."""
    return getattr(field, "_file_index", 0)


def choose_in_custom_combobox(page, field: FormField, value: str) -> None:
    """Open a div-based combobox and click the matching option.

    select_option() only works on a native <select>. Rippling — and most
    component libraries — render dropdowns as divs, so the only way in is to
    drive it the way a person would: click to open, click the option.
    """
    box = locator_for(page, field)
    box.click()
    option = page.get_by_role("option", name=str(value), exact=True)
    option.wait_for(state="visible", timeout=5000)
    option.click()


def _read_back_combobox(page, field: FormField) -> str:
    return locator_for(page, field).inner_text().strip()
```

Then route them in `_write` and `_read_back`:

```python
    elif field.kind == "combobox":
        choose_in_custom_combobox(locator.page, field, value)
    elif field.kind == "file":
        upload_file(locator.page, field, value)
```

and in `_read_back`:

```python
    if field.kind == "combobox":
        return locator.inner_text().strip()
    if field.kind == "file":
        return "attached" if locator.evaluate("e => e.files.length") else ""
```

For `file`, the intended value is a path but the observed value is
`"attached"`, so `_verify` must special-case it: a file field verifies when a
file is attached, not when the strings match.

- [ ] **Step 5: Run the tests and iterate**

Run: `pytest tests/test_fill_widgets.py -v`
Expected: 4 passed.

`locator.page` may not exist on your Playwright version — if so, pass `page`
down through `_write`/`_read_back` explicitly rather than reaching for it.

- [ ] **Step 6: Commit**

```bash
git add src/job_agent/fill.py tests/fixtures/custom_combobox.html tests/test_fill_widgets.py
git commit -m "feat: fill custom comboboxes and file inputs"
```

---

### Task 3: Résumé-first ordering and one retry

**Files:**
- Modify: `src/job_agent/fill.py`
- Test: `tests/test_fill_ordering.py`

**Interfaces:**
- Produces: `fill.execute_plan(page, snapshot, plan, *, retries: int = 1)` with file fields ordered first

- [ ] **Step 1: Write the failing test**

`tests/test_fill_ordering.py`:

```python
from job_agent.fill import order_for_execution
from job_agent.models import FormField, FormSnapshot, PlannedField


def field(fid, name, kind):
    return FormField(field_id=fid, role="textbox", accessible_name=name, kind=kind,
                     options=[] if kind in {"select", "radio", "combobox"} else None)


SNAP = FormSnapshot(
    url="https://x", page_title="t", page_kind="form",
    fields=[
        field("f_01", "First name", "text"),
        field("f_02", "Résumé", "file"),
        field("f_03", "Email", "text"),
    ],
)


def planned(fid):
    return PlannedField(field_id=fid, value="v", source="profile", confidence=1.0, note="t")


def test_file_uploads_are_executed_first():
    """The site parses the resume to prefill. Uploading first means our values
    land afterwards and win; uploading last would let the parser overwrite us."""
    ordered = order_for_execution(SNAP, [planned("f_01"), planned("f_02"), planned("f_03")])
    assert [p.field_id for p in ordered][0] == "f_02"


def test_non_file_order_is_otherwise_preserved():
    ordered = order_for_execution(SNAP, [planned("f_03"), planned("f_01")])
    assert [p.field_id for p in ordered] == ["f_03", "f_01"]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `pytest tests/test_fill_ordering.py -v`
Expected: `ImportError: cannot import name 'order_for_execution'`

- [ ] **Step 3: Add ordering and retry to `src/job_agent/fill.py`**

```python
def order_for_execution(snapshot: FormSnapshot, planned: list[PlannedField]) -> list[PlannedField]:
    """File uploads first.

    The site parses the résumé to prefill fields. Uploading first means our
    values are written afterwards and win. Uploading last would let the
    parser overwrite everything we just typed.
    """
    by_id = {f.field_id: f for f in snapshot.fields}
    files = [p for p in planned if by_id.get(p.field_id) and by_id[p.field_id].kind == "file"]
    rest = [p for p in planned if p not in files]
    return files + rest
```

In `execute_plan`, iterate `order_for_execution(snapshot, plan.fields)`, and
retry a `mismatch` once before recording it:

```python
        result = _execute_one(page, by_id.get(planned.field_id), planned)
        if result.outcome == "mismatch" and retries > 0:
            page.wait_for_timeout(300)
            result = _execute_one(page, by_id.get(planned.field_id), planned)
        results.append(result)
```

The 300ms pause matters: a mismatch is often a re-render racing the write,
and an immediate retry loses the same race.

- [ ] **Step 4: Run the whole suite**

Run: `pytest -v`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add src/job_agent/fill.py tests/test_fill_ordering.py
git commit -m "feat: upload files first, retry a mismatch once"
```

---

### Task 4: Page classification and the flow loop

**Files:**
- Create: `tests/fixtures/wizard_page1.html`, `tests/fixtures/wizard_page2.html`, `tests/fixtures/confirmation.html`, `tests/fixtures/login.html`
- Create: `src/job_agent/flow.py`
- Test: `tests/test_flow.py`

**Interfaces:**
- Produces: `flow.classify_page(page) -> str`, `flow.run_application(page, profile, client, *, decide, max_pages=12) -> FlowResult`

- [ ] **Step 1: Write the four fixtures**

`wizard_page1.html` — a form with a "Next" button linking to page 2:

```html
<!doctype html>
<html><head><title>Step 1</title></head><body>
  <form>
    <label for="a">First name</label><input id="a" name="a" required />
  </form>
  <a id="next" href="wizard_page2.html">Next</a>
</body></html>
```

`wizard_page2.html` — a second form with a Submit button:

```html
<!doctype html>
<html><head><title>Step 2</title></head><body>
  <form>
    <label for="b">Email</label><input id="b" name="b" type="email" required />
  </form>
  <button id="submit" type="button">Submit application</button>
</body></html>
```

`confirmation.html` — no fields, confirmation wording:

```html
<!doctype html>
<html><head><title>Thanks</title></head><body>
  <h1>Application submitted</h1>
  <p>Thank you for applying. We have received your application.</p>
</body></html>
```

`login.html` — a password field, which is the giveaway:

```html
<!doctype html>
<html><head><title>Sign in</title></head><body>
  <form>
    <label for="u">Email</label><input id="u" type="email" />
    <label for="p">Password</label><input id="p" type="password" />
    <button type="submit">Sign in</button>
  </form>
</body></html>
```

- [ ] **Step 2: Write the failing test**

`tests/test_flow.py`:

```python
from pathlib import Path

import pytest

from job_agent.browser import browser_context
from job_agent.flow import classify_page, run_application
from job_agent.models import FillPlan, PlannedField

FIXTURES = Path(__file__).parent / "fixtures"


def url(name):
    return (FIXTURES / name).resolve().as_uri()


@pytest.fixture(scope="module")
def ctx():
    with browser_context(headless=True) as context:
        yield context


def test_a_page_with_a_password_field_is_a_login(ctx):
    page = ctx.new_page()
    page.goto(url("login.html"))
    assert classify_page(page) == "login"


def test_a_page_with_no_fields_and_confirmation_wording_is_a_confirmation(ctx):
    page = ctx.new_page()
    page.goto(url("confirmation.html"))
    assert classify_page(page) == "confirmation"


def test_a_page_with_editable_fields_is_a_form(ctx):
    page = ctx.new_page()
    page.goto(url("wizard_page1.html"))
    assert classify_page(page) == "form"


class StubPlanner:
    """Plans the first field of every page, so the loop has work to do."""

    def __init__(self):
        self.calls = 0

    def __call__(self, snapshot):
        self.calls += 1
        if not snapshot.fields:
            return FillPlan()
        return FillPlan(fields=[PlannedField(
            field_id=snapshot.fields[0].field_id, value="x",
            source="profile", confidence=1.0, note="stub",
        )])


def test_the_loop_advances_through_a_two_page_wizard(ctx):
    page = ctx.new_page()
    page.goto(url("wizard_page1.html"))
    planner = StubPlanner()
    result = run_application(page, planner=planner, decide=lambda *_: "abandon")

    assert planner.calls == 2, "planned page 1 and page 2"
    assert result.pages_visited == 2


def test_the_loop_stops_when_a_page_never_advances(ctx):
    page = ctx.new_page()
    page.goto(url("wizard_page2.html"))  # has no Next
    result = run_application(page, planner=StubPlanner(), decide=lambda *_: "abandon")
    assert result.pages_visited <= 3, "repeat-URL guard must fire"


def test_the_page_cap_is_enforced(ctx):
    page = ctx.new_page()
    page.goto(url("wizard_page1.html"))
    result = run_application(
        page, planner=StubPlanner(), decide=lambda *_: "abandon", max_pages=1
    )
    assert result.pages_visited == 1
    assert result.outcome in {"guard_tripped", "abandoned"}


def test_the_flow_never_submits_without_approval(ctx):
    """The single most important test in this project."""
    page = ctx.new_page()
    page.goto(url("wizard_page2.html"))

    submitted = []
    result = run_application(
        page,
        planner=StubPlanner(),
        decide=lambda *_: "abandon",
        submit=lambda *_: submitted.append(True),
    )
    assert submitted == [], "submit was called without approval"
    assert result.outcome == "abandoned"


def test_approval_is_what_calls_submit(ctx):
    page = ctx.new_page()
    page.goto(url("wizard_page2.html"))

    submitted = []
    run_application(
        page,
        planner=StubPlanner(),
        decide=lambda *_: "submit",
        submit=lambda *_: submitted.append(True),
    )
    assert submitted == [True]
```

- [ ] **Step 3: Run it and watch it fail**

Run: `pytest tests/test_flow.py -v`
Expected: `ModuleNotFoundError: No module named 'job_agent.flow'`

- [ ] **Step 4: Write `src/job_agent/flow.py`**

```python
"""The page loop.

Agent loops do not usually fail by giving a wrong answer. They fail by never
terminating. Hence the two guards, and hence the fact that submit() is
injected rather than imported — a test can then prove the loop never calls it
without approval.
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


@dataclass
class FlowResult:
    outcome: str                       # submitted | abandoned | needs_human | guard_tripped
    pages_visited: int = 0
    reports: list = dc_field(default_factory=list)
    detail: str | None = None


def classify_page(page) -> str:
    if page.locator("input[type=password]").count():
        return "login"

    editable = page.locator(
        "input:not([type=hidden]):not([type=submit]), textarea, select, "
        "[role=combobox], [role=textbox]"
    ).count()

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
                page.wait_for_timeout(500)
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
```

- [ ] **Step 5: Run the tests and iterate**

Run: `pytest tests/test_flow.py -v`
Expected: 8 passed.

If `test_the_loop_advances_through_a_two_page_wizard` sees `planner.calls == 1`,
the Next link is not being found — check `_click_first` matches an `<a>` by its
link role, not only buttons.

- [ ] **Step 6: Commit**

```bash
git add src/job_agent/flow.py tests/fixtures/ tests/test_flow.py
git commit -m "feat: page classification and the guarded application loop"
```

---

### Task 5: The review gate

**Files:**
- Create: `src/job_agent/review.py`
- Create: `scripts/apply.py`
- Test: `tests/test_review.py`

**Interfaces:**
- Produces: `review.render_review(snapshot, plan, report, screenshot) -> str`, `review.ask(...) -> str`

- [ ] **Step 1: Write the failing test**

`tests/test_review.py`:

```python
from job_agent.models import (
    FieldResult, FillPlan, FillReport, FormField, FormSnapshot, PlannedField, Unresolved,
)
from job_agent.review import render_review


SNAP = FormSnapshot(
    url="https://x/apply", page_title="Apply - Quant Trader", page_kind="form", ats="rippling",
    fields=[
        FormField(field_id="f_01", role="textbox", accessible_name="First name", kind="text"),
        FormField(field_id="f_02", role="textbox", accessible_name="Why this firm?", kind="textarea"),
        FormField(field_id="f_03", role="textbox", accessible_name="Select the second word", kind="attention_check"),
    ],
)
PLAN = FillPlan(
    fields=[
        PlannedField(field_id="f_01", value="Johny", source="profile", confidence=1.0, note="profile"),
        PlannedField(field_id="f_02", value="I admire the...", source="generated", confidence=0.8, note="drafted"),
    ],
    unresolved=[Unresolved(field_id="f_03", reason="attention check — human only")],
)
REPORT = FillReport(results=[
    FieldResult(field_id="f_01", outcome="verified", intended="Johny", observed="Johny"),
    FieldResult(field_id="f_02", outcome="verified", intended="I admire the...", observed="I admire the..."),
])


def test_review_shows_every_value_with_its_source():
    text = render_review(SNAP, PLAN, REPORT, screenshot="runs/x.png")
    assert "First name" in text
    assert "Johny" in text
    assert "profile" in text


def test_generated_values_are_visually_flagged():
    text = render_review(SNAP, PLAN, REPORT, screenshot="runs/x.png")
    generated_line = next(l for l in text.splitlines() if "Why this firm?" in l)
    assert "REVIEW" in generated_line.upper()


def test_unresolved_fields_appear_so_they_cannot_be_missed():
    text = render_review(SNAP, PLAN, REPORT, screenshot="runs/x.png")
    assert "Select the second word" in text
    assert "attention check" in text.lower()


def test_a_failed_write_is_shown_as_a_failure():
    report = FillReport(results=[
        FieldResult(field_id="f_01", outcome="mismatch", intended="Johny", observed=""),
    ])
    text = render_review(SNAP, PLAN, report, screenshot="runs/x.png")
    assert "mismatch" in text.lower() or "FAILED" in text


def test_the_screenshot_path_is_shown():
    text = render_review(SNAP, PLAN, REPORT, screenshot="runs/2026/page.png")
    assert "runs/2026/page.png" in text
```

- [ ] **Step 2: Run it and watch it fail**

Run: `pytest tests/test_review.py -v`
Expected: `ModuleNotFoundError: No module named 'job_agent.review'`

- [ ] **Step 3: Write `src/job_agent/review.py`**

```python
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
        lines.append(f"  {planned.source:11} {name[:34]:36} {str(planned.value)[:40]}{flag}{status}")

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

    There is no default and no timeout. Pressing Enter alone re-prompts.
    """
    print(render_review(snapshot, plan, report, screenshot))
    while True:
        choice = input("  > ").strip().lower()
        if choice in VALID_DECISIONS:
            return VALID_DECISIONS[choice]
        print("  please type s, e, o, or a")
```

- [ ] **Step 4: Write `scripts/apply.py`**

```python
"""Apply to a job posting. Stops for your approval before submitting.

Run:  python scripts/apply.py <application-url>
      python scripts/apply.py <url> --headless
"""

import sys
from datetime import datetime

import anthropic

from job_agent.browser import browser_context
from job_agent.config import PROJECT_ROOT, require_api_key
from job_agent.flow import run_application
from job_agent.plan import build_plan
from job_agent.profile import load_profile
from job_agent.review import ask


def main() -> None:
    require_api_key()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("usage: python scripts/apply.py <url> [--headless]")
    url = args[0]

    profile = load_profile()
    client = anthropic.Anthropic()
    run_dir = PROJECT_ROOT / "runs" / datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    with browser_context(headless="--headless" in sys.argv) as ctx:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        def decide(snapshot, plan, report):
            shot = run_dir / f"page{len(list(run_dir.glob('*.png'))) + 1}.png"
            page.screenshot(path=str(shot))
            return ask(snapshot, plan, report, str(shot))

        result = run_application(
            page,
            planner=lambda snapshot: build_plan(client, snapshot, profile),
            decide=decide,
            submit=lambda p: p.get_by_role("button", name="Submit").first.click(),
        )

    print(f"\noutcome: {result.outcome}  ({result.pages_visited} pages)")
    if result.detail:
        print(f"detail:  {result.detail}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests**

Run: `pytest -v`
Expected: green, roughly 80 tests.

- [ ] **Step 6: Dry run against the fixture**

```bash
python scripts/apply.py "file://$(pwd)/tests/fixtures/rippling_apply.html"
```

Read the review screen. Every value should be traceable to your profile, the
attention check should be under NEEDS YOU, and pressing `a` should abandon
without submitting anything.

- [ ] **Step 7: Live run — your decision, your keypress**

```bash
python scripts/apply.py "<the Edgehog apply URL>"
```

Watch it fill. Read the review screen carefully. **Only press `s` if you would
have submitted that exact form yourself.**

If anything is wrong, press `a`, fix `profile.yaml` or the prompt, and run it
again. That loop — run, read, correct — is the actual product.

- [ ] **Step 8: Write the Stage 6 + 7 section of `NOTES.md`, then commit**

```bash
git add src/job_agent/review.py scripts/apply.py tests/test_review.py NOTES.md
git status --short          # runs/ must NOT appear
git commit -m "feat: the human approval gate and the apply entry point"
```

---

## Stage Exit Criteria

- [ ] `pytest` green; no test submits anything, and no test hits a live site
- [ ] `test_the_flow_never_submits_without_approval` passes — the load-bearing test
- [ ] A write that silently reverts is reported as `mismatch`, not success
- [ ] File uploads execute before text fields
- [ ] A `<div role=combobox>` can be set, and `select_option` is shown to fail on it
- [ ] The review screen shows every value with its source, flags generated ones, and lists everything unresolved
- [ ] One real application filled end to end, reviewed, and submitted by a human keypress

## What Stage 8 Needs From This

Stage 8 turns each run into a record: the `FillReport`s, the screenshots, and
the answers you typed at the review gate — so the answer bank grows and the
agent gets quieter with every application.

Before then, `profile.yaml` still has `VERIFY` markers on all four
work-authorization lines. Stage 7 writes real values into real forms; those
need to be right first.
