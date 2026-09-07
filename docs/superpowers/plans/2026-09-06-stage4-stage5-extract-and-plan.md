# Stage 4 + Stage 5: Form Extraction and the Field Planner

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a live application page into a compact `FormSnapshot`, then turn that snapshot plus the profile into a `FillPlan` that says what goes in every field and where each value came from.

**Architecture:** `extract.py` walks the page's accessibility tree and emits JSON — label, role, requiredness, options, and a *role-based* locator per field. `plan.py` sends that JSON plus the cached profile to Claude with a Pydantic output schema and gets back a validated `FillPlan`. The model does judgment; it never touches the page. Everything is tested against committed HTML fixtures with their scripts stripped.

**Tech Stack:** Python 3.14.7, `playwright` 1.62 (sync), `anthropic` 1.x (`messages.parse`), `pydantic` 2.x, `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-06-job-application-agent-design.md`

## Global Constraints

- **Selectors are role-based, never `name`/`id`.** Rippling generates field `name` attributes as per-render hashes (`4Za8M3kpmM`, `n6i9CInKB6_`). Use `get_by_role(role, name=...)`. This is a measured constraint, not a preference.
- **Requiredness comes from `aria-required="true"`**, plus a trailing `*` on the label text. Rippling never sets the HTML `required` attribute.
- **Fixtures must have `<script>` tags stripped before saving.** These are Next.js apps; reloading an unstripped capture from `file://` lets React hydrate, fail to reach its API, and wipe the DOM you captured.
- **The planner runs on `config.PLANNER_MODEL` (Opus 5)** with `thinking={"type": "adaptive"}` — supported there, and this is the one stage where judgment quality matters. Caching pays off here (Opus 5 minimum is 512 tokens; the profile is ~2165).
- **The extractor makes no API calls. The planner makes no page calls.** That separation is what keeps both testable.
- Never generate values for: work authorization, EEO/demographics, degrees, dates, GPA, salary. Profile verbatim, or `unresolved`.
- Commit at the end of each task; suite green first.

## What the Rippling reconnaissance established

Measured against the real Edgehog application form, not assumed:

| Question | Answer |
|---|---|
| Are `name`/`id` stable? | **No** — per-render hashes |
| Where does the label come from? | `aria-labelledby` -> a label element; `placeholder` duplicates it; the ARIA accessible name resolves both |
| Where does requiredness come from? | `aria-required="true"`, and a `*` suffix in the label text |
| Does the HTML `required` attribute work? | **No** — never set; validation is in JS |
| Are there file uploads? | Two — Résumé and Cover letter, `.doc/.docx/.pdf` |
| Is there an EEO section? | Yes, marked "Completion is voluntary" |

`page.locator("form").aria_snapshot()` produces exactly the shape we want:

```
- text: First name*
- textbox "First name"
- text: LinkedIn Link
- textbox "LinkedIn Link"
- combobox "Search": +1 US
```

Two findings that change behaviour, not just parsing:

**1. The résumé is parsed to autofill — and résumé parsers are unreliable.**
The form says *"The résumé will be parsed to fill in the application details."*
The naive reading is "upload first, then fill only what is still empty."

**That is wrong in the dangerous direction.** Parsers routinely mis-extract a
name, mangle a phone format, or get dates approximately right — anyone who has
used one ends up correcting fields afterwards. An agent that treats a
pre-filled field as already handled would launder those mistakes into a
submitted application and add automation on top.

Correct ordering:

1. **Upload the résumé first** — the form requires it, and going first means
   the parser cannot overwrite our values later.
2. **Re-extract.** Autofill changes the DOM; `current_value` now carries
   whatever the parser guessed.
3. **Overwrite every field the profile has a fact for**, whether or not
   something is already in it. Ours land last, so ours win.
4. **A pre-filled value the profile cannot confirm is `unresolved`, not done.**

Rule four is the one that matters: **a non-empty field is not a correct
field.**

**2. This posting contains a human-attention check.** Verbatim:

> *"Select the second word of this sentence: 'We value innovation, collaboration, and integrity.'"*

That question exists to detect inattentive or automated applications. A model answers it trivially, which arguably defeats its purpose. **The agent must never auto-answer it.** Task 4 adds an `attention_check` classification so such questions are always routed to the human, regardless of confidence. This is a deliberate product decision, not a technical limit.

---

### Task 1: Capture fixtures that survive being reloaded

**Files:**
- Create: `src/job_agent/fixtures.py`
- Create: `scripts/capture_fixture.py`
- Replace: `tests/fixtures/rippling_apply.html` (script-stripped)
- Test: `tests/test_fixtures.py`

**Interfaces:**
- Produces: `fixtures.strip_scripts(html: str) -> str`, `fixtures.capture(page, path: Path) -> Path`

- [ ] **Step 1: Write the failing test**

`tests/test_fixtures.py`:

```python
from job_agent.fixtures import strip_scripts


def test_script_tags_are_removed():
    html = "<html><body><input id='a'><script>x=1</script></body></html>"
    out = strip_scripts(html)
    assert "<script" not in out
    assert "<input id='a'>" in out


def test_multiline_and_attributed_scripts_are_removed():
    html = """<div><script type="application/json" id="__NEXT_DATA__">
    {"props": {"a": 1}}
    </script><input></div>"""
    out = strip_scripts(html)
    assert "__NEXT_DATA__" not in out
    assert "<input>" in out


def test_the_committed_rippling_fixture_has_no_scripts():
    from pathlib import Path

    html = Path("tests/fixtures/rippling_apply.html").read_text()
    assert "<script" not in html.lower(), (
        "fixture will re-hydrate and wipe itself when loaded from file://"
    )
```

- [ ] **Step 2: Run it and watch it fail**

Run: `pytest tests/test_fixtures.py -v`
Expected: `ModuleNotFoundError: No module named 'job_agent.fixtures'`

- [ ] **Step 3: Write `src/job_agent/fixtures.py`**

```python
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
```

- [ ] **Step 4: Write `scripts/capture_fixture.py`**

```python
"""Save a live application form as a test fixture.

Run:  python scripts/capture_fixture.py <url> tests/fixtures/name.html

Navigates, waits for the form to render, strips scripts, writes the file.
Fills nothing and submits nothing.
"""

import sys
from pathlib import Path

from job_agent.browser import browser_context
from job_agent.fixtures import capture


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: python scripts/capture_fixture.py <url> <out.html>")
    url, out = sys.argv[1], Path(sys.argv[2])

    with browser_context(headless=True) as ctx:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        capture(page, out)

    size = out.stat().st_size
    print(f"wrote {out} ({size // 1024} KB)")
    if "<script" in out.read_text().lower():
        raise SystemExit("ERROR: scripts survived — fixture will wipe itself on reload")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Recapture the Rippling fixture properly**

The committed one still has 19 script tags. Replace it:

```bash
python scripts/capture_fixture.py \
  "https://ats.rippling.com/en-CA/edgehog-trading/jobs/96354af0-1bd0-4703-a654-e3d591b07777/apply?jobBoardSlug=edgehog-trading&jobId=96354af0-1bd0-4703-a654-e3d591b07777&step=application" \
  tests/fixtures/rippling_apply.html
```

Note that URL is the `/apply` page, not the posting.

- [ ] **Step 6: Run the tests**

Run: `pytest tests/test_fixtures.py -v`
Expected: 3 passed, including the one asserting the committed fixture is script-free.

- [ ] **Step 7: Commit**

```bash
git add src/job_agent/fixtures.py scripts/capture_fixture.py tests/
git commit -m "feat: reload-safe fixture capture; recapture Rippling without scripts"
```

---

### Task 2: FormField and FormSnapshot

**Files:**
- Modify: `src/job_agent/models.py`
- Test: `tests/test_form_models.py`

**Interfaces:**
- Produces: `models.FieldKind`, `models.FormField`, `models.FormSnapshot`

- [ ] **Step 1: Write the failing test**

`tests/test_form_models.py`:

```python
import pytest
from pydantic import ValidationError

from job_agent.models import FormField, FormSnapshot


def make_field(**kw) -> FormField:
    base = dict(
        field_id="f_01",
        role="textbox",
        accessible_name="First name",
        kind="text",
        required=True,
    )
    return FormField(**{**base, **kw})


def test_field_ids_are_opaque_so_the_model_never_sees_css():
    field = make_field()
    assert field.field_id == "f_01"
    # no selector string is exposed on the model's view of a field
    assert not hasattr(field, "css_selector")


def test_options_are_required_for_a_choice_field():
    with pytest.raises(ValidationError, match="options"):
        make_field(kind="select", options=None)


def test_attention_check_is_a_distinct_kind():
    field = make_field(kind="attention_check", accessible_name="Select the second word")
    assert field.kind == "attention_check"


def test_snapshot_rejects_duplicate_field_ids():
    with pytest.raises(ValidationError, match="unique"):
        FormSnapshot(
            url="https://x",
            page_title="t",
            page_kind="form",
            fields=[make_field(), make_field()],
        )


def test_snapshot_defaults_to_no_buttons():
    snap = FormSnapshot(url="https://x", page_title="t", page_kind="form", fields=[])
    assert snap.next_buttons == []
    assert snap.submit_buttons == []
```

- [ ] **Step 2: Run it and watch it fail**

Run: `pytest tests/test_form_models.py -v`
Expected: `ImportError: cannot import name 'FormField'`

- [ ] **Step 3: Add the models to `src/job_agent/models.py`**

```python
from typing import Literal

from pydantic import field_validator, model_validator

FieldKind = Literal[
    "text",
    "textarea",
    "email",
    "tel",
    "number",
    "url",
    "select",
    "radio",
    "checkbox",
    "file",
    "date",
    "combobox",
    "attention_check",
]

CHOICE_KINDS = {"select", "radio", "combobox"}


class FormField(Strict):
    """One control on a page, described the way the model should see it.

    Deliberately no CSS selector: Rippling regenerates name/id per render, so
    the extractor keeps its own role+name handle and the model refers to
    fields only by the opaque field_id.
    """

    field_id: str
    role: str                      # ARIA role: textbox, combobox, button, ...
    accessible_name: str           # what a screen reader would announce
    kind: FieldKind
    required: bool = False
    options: list[str] | None = None
    # Whatever is already in the field — often the résumé parser's guess.
    # A non-empty value is NOT evidence that the field is correct.
    current_value: str | None = None
    help_text: str | None = None

    @model_validator(mode="after")
    def choice_fields_need_options(self):
        if self.kind in CHOICE_KINDS and self.options is None:
            raise ValueError(f"options are required for kind={self.kind}")
        return self


class FormSnapshot(Strict):
    url: str
    page_title: str
    page_kind: Literal["form", "login", "review", "confirmation", "captcha", "unknown"]
    ats: str | None = None
    fields: list[FormField] = Field(default_factory=list)
    next_buttons: list[str] = Field(default_factory=list)
    submit_buttons: list[str] = Field(default_factory=list)

    @field_validator("fields")
    @classmethod
    def field_ids_must_be_unique(cls, fields: list[FormField]) -> list[FormField]:
        ids = [f.field_id for f in fields]
        if len(ids) != len(set(ids)):
            raise ValueError("field_id values must be unique within a snapshot")
        return fields
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_form_models.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/job_agent/models.py tests/test_form_models.py
git commit -m "feat: FormField and FormSnapshot models"
```

---

### Task 3: The extractor

**Files:**
- Create: `src/job_agent/extract.py`
- Test: `tests/test_extract.py`

**Interfaces:**
- Consumes: `models.FormField`, `models.FormSnapshot`
- Produces: `extract.extract_snapshot(page) -> FormSnapshot`, `extract.locator_for(page, field: FormField)`, `extract.detect_ats(url: str) -> str | None`

- [ ] **Step 1: Write the failing test**

`tests/test_extract.py`:

```python
from pathlib import Path

import pytest

from job_agent.browser import browser_context
from job_agent.extract import detect_ats, extract_snapshot, locator_for

FIXTURES = Path(__file__).parent / "fixtures"
SIMPLE = (FIXTURES / "simple_form.html").resolve().as_uri()
RIPPLING = (FIXTURES / "rippling_apply.html").resolve().as_uri()


@pytest.fixture
def snapshot_of():
    def _load(url):
        with browser_context(headless=True) as ctx:
            page = ctx.new_page()
            page.goto(url)
            page.wait_for_timeout(300)
            return extract_snapshot(page)
    return _load


def test_simple_form_fields_are_found_with_their_labels(snapshot_of):
    snap = snapshot_of(SIMPLE)
    names = {f.accessible_name for f in snap.fields}
    assert "First name" in names
    assert "Email" in names


def test_rippling_labels_survive_hashed_name_attributes(snapshot_of):
    snap = snapshot_of(RIPPLING)
    names = {f.accessible_name for f in snap.fields}
    # these come from the accessibility tree; name="4Za8M3kpmM" is useless
    assert "First name" in names
    assert "Last name" in names
    assert "Email" in names
    assert "LinkedIn Link" in names


def test_requiredness_comes_from_aria_not_the_html_attribute(snapshot_of):
    snap = snapshot_of(RIPPLING)
    by_name = {f.accessible_name: f for f in snap.fields}
    assert by_name["First name"].required is True
    assert by_name["LinkedIn Link"].required is False


def test_the_attention_check_is_classified_not_treated_as_prose(snapshot_of):
    snap = snapshot_of(RIPPLING)
    kinds = {f.kind for f in snap.fields}
    assert "attention_check" in kinds, (
        "the 'select the second word' question must be flagged so it is never "
        "auto-answered"
    )


def test_file_uploads_are_found(snapshot_of):
    snap = snapshot_of(RIPPLING)
    assert any(f.kind == "file" for f in snap.fields)


def test_field_ids_are_stable_across_two_extractions(snapshot_of):
    a = snapshot_of(RIPPLING)
    b = snapshot_of(RIPPLING)
    assert [f.field_id for f in a.fields] == [f.field_id for f in b.fields]
    assert [f.accessible_name for f in a.fields] == [f.accessible_name for f in b.fields]


def test_locator_for_resolves_to_exactly_one_element():
    with browser_context(headless=True) as ctx:
        page = ctx.new_page()
        page.goto(RIPPLING)
        page.wait_for_timeout(300)
        snap = extract_snapshot(page)
        field = next(f for f in snap.fields if f.accessible_name == "First name")
        assert locator_for(page, field).count() == 1


def test_snapshot_is_small_enough_to_send_cheaply(snapshot_of):
    snap = snapshot_of(RIPPLING)
    payload = snap.model_dump_json()
    # a screenshot of this page would be an order of magnitude more tokens
    assert len(payload) < 20000, f"snapshot is {len(payload)} chars"


def test_detect_ats_reads_the_host():
    assert detect_ats("https://ats.rippling.com/en-CA/x/jobs/1/apply") == "rippling"
    assert detect_ats("https://boards.greenhouse.io/acme/jobs/1") == "greenhouse"
    assert detect_ats("https://jobs.lever.co/acme/1") == "lever"
    assert detect_ats("https://example.com/careers") is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `pytest tests/test_extract.py -v`
Expected: `ModuleNotFoundError: No module named 'job_agent.extract'`

- [ ] **Step 3: Write `src/job_agent/extract.py`**

```python
"""Turn a live page into a compact FormSnapshot.

No LLM here. This module only reads the DOM and the accessibility tree.

Why the accessibility tree rather than CSS selectors: Rippling regenerates
every field's name/id per render (4Za8M3kpmM, n6i9CInKB6_), so those are
useless as handles. The accessible name — "First name", "LinkedIn Link" — is
the only stable identifier, and it is also exactly what a human sees.
"""

import re
from urllib.parse import urlparse

from job_agent.models import FormField, FormSnapshot

ATS_HOSTS = {
    "ats.rippling.com": "rippling",
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby",
    "myworkdayjobs.com": "workday",
}

# Questions designed to verify a human read the page. Never auto-answered.
ATTENTION_PATTERNS = [
    re.compile(r"\bselect the (first|second|third|last) word\b", re.I),
    re.compile(r"\btype the word\b", re.I),
    re.compile(r"\bto show you (have )?read\b", re.I),
    re.compile(r"\bwhat is \d+\s*[+\-x*]\s*\d+", re.I),
]

ROLE_TO_KIND = {
    "textbox": "text",
    "combobox": "combobox",
    "checkbox": "checkbox",
    "radio": "radio",
    "spinbutton": "number",
}


def detect_ats(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    for known, name in ATS_HOSTS.items():
        if host == known or host.endswith("." + known) or known in host:
            return name
    return None


def _looks_like_attention_check(text: str) -> bool:
    return any(p.search(text) for p in ATTENTION_PATTERNS)


def _kind_for(element, role: str, name: str, help_text: str) -> str:
    if _looks_like_attention_check(name) or _looks_like_attention_check(help_text):
        return "attention_check"
    input_type = (element.get_attribute("type") or "").lower()
    if input_type in {"file", "email", "tel", "number", "url", "date"}:
        return "file" if input_type == "file" else input_type
    if element.evaluate("e => e.tagName.toLowerCase()") == "textarea":
        return "textarea"
    if element.evaluate("e => e.tagName.toLowerCase()") == "select":
        return "select"
    return ROLE_TO_KIND.get(role, "text")


def _accessible_name(element) -> str:
    """The name a screen reader announces, however the page provides it."""
    return element.evaluate(
        """e => {
            const byId = id => id && document.getElementById(id);
            const labelledby = e.getAttribute('aria-labelledby');
            if (labelledby) {
                const parts = labelledby.split(/\\s+/).map(byId).filter(Boolean);
                if (parts.length) return parts.map(n => n.innerText).join(' ').trim();
            }
            if (e.getAttribute('aria-label')) return e.getAttribute('aria-label').trim();
            if (e.labels && e.labels.length) return e.labels[0].innerText.trim();
            if (e.placeholder) return e.placeholder.trim();
            return '';
        }"""
    ).strip()


def _is_required(element, name: str) -> bool:
    # aria-required first: Rippling never sets the HTML required attribute
    if (element.get_attribute("aria-required") or "").lower() == "true":
        return True
    if element.get_attribute("required") is not None:
        return True
    # a trailing asterisk on the rendered label is the visual convention
    return name.rstrip().endswith("*")


def extract_snapshot(page) -> FormSnapshot:
    fields: list[FormField] = []
    index = 0

    for element in page.locator("input, textarea, select").all():
        if (element.get_attribute("type") or "").lower() == "hidden":
            continue
        if not element.is_visible():
            # file inputs are routinely visually hidden behind a styled button
            if (element.get_attribute("type") or "").lower() != "file":
                continue

        role = element.get_attribute("role") or (
            "textbox" if element.evaluate("e => e.tagName.toLowerCase()") != "select" else "combobox"
        )
        name = _accessible_name(element)
        help_text = element.get_attribute("title") or ""
        if not name and (element.get_attribute("type") or "").lower() != "file":
            continue

        kind = _kind_for(element, role, name, help_text)
        options = None
        if kind in {"select", "radio", "combobox"}:
            options = [
                (o.inner_text() or o.get_attribute("value") or "").strip()
                for o in element.locator("option").all()
            ] or []

        index += 1
        fields.append(
            FormField(
                field_id=f"f_{index:02d}",
                role=role,
                accessible_name=name.rstrip("*").strip() or "(unlabelled file upload)",
                kind=kind,
                required=_is_required(element, name),
                options=options,
                current_value=element.get_attribute("value"),
                help_text=help_text or None,
            )
        )

    def button_names(pattern: str) -> list[str]:
        found = []
        for b in page.get_by_role("button").all():
            text = (b.inner_text() or "").strip()
            if re.search(pattern, text, re.I):
                found.append(text)
        return found

    return FormSnapshot(
        url=page.url,
        page_title=page.title(),
        page_kind="form" if fields else "unknown",
        ats=detect_ats(page.url),
        fields=fields,
        next_buttons=button_names(r"\b(next|continue)\b"),
        submit_buttons=button_names(r"\b(submit|apply|send)\b"),
    )


def locator_for(page, field: FormField):
    """Resolve a FormField back to a Playwright locator.

    Role + accessible name, because that pair is stable across renders while
    name/id are not.
    """
    return page.get_by_role(field.role, name=field.accessible_name, exact=True)
```

- [ ] **Step 4: Run the tests and iterate**

Run: `pytest tests/test_extract.py -v`

Expect failures on the first pass — real markup is messier than any plan. Fix `extract.py` until green; do **not** relax the assertions. If `test_locator_for_resolves_to_exactly_one_element` fails with a count above 1, the accessible name is ambiguous on that page, and the fix is to add a disambiguator to `FormField` (an occurrence index), not to loosen the test.

- [ ] **Step 5: Commit**

```bash
git add src/job_agent/extract.py tests/test_extract.py
git commit -m "feat: extract a FormSnapshot from the accessibility tree"
```

---

### Task 4: FillPlan and the planner

**Files:**
- Modify: `src/job_agent/models.py`
- Create: `src/job_agent/plan.py`
- Test: `tests/test_plan.py`

**Interfaces:**
- Consumes: `models.FormSnapshot`, `models.Profile`, `prompt.profile_system_prompt`
- Produces: `models.ValueSource`, `models.PlannedField`, `models.Unresolved`, `models.FillPlan`; `plan.build_plan(client, snapshot, profile, job_context=None) -> FillPlan`

- [ ] **Step 1: Add the plan models to `src/job_agent/models.py`**

```python
ValueSource = Literal["profile", "answer_bank", "generated", "default"]

# Fields whose value is never allowed to be model-generated. Wrong answers
# here are misrepresentations on a real job application, not bugs.
NEVER_GENERATED = {"profile", "answer_bank", "default"}


class PlannedField(Strict):
    field_id: str
    value: str | bool | list[str]
    source: ValueSource
    confidence: float = Field(ge=0.0, le=1.0)
    note: str


class Unresolved(Strict):
    field_id: str
    reason: str


class FillPlan(Strict):
    fields: list[PlannedField] = Field(default_factory=list)
    unresolved: list[Unresolved] = Field(default_factory=list)
```

- [ ] **Step 2: Write the failing test**

`tests/test_plan.py`:

```python
from pathlib import Path

from job_agent.models import FillPlan, FormField, FormSnapshot, PlannedField, Unresolved
from job_agent.plan import CONFIDENCE_FLOOR, apply_safety_rules, build_plan
from job_agent.profile import load_profile


def field(fid, name, kind="text", required=True) -> FormField:
    return FormField(
        field_id=fid, role="textbox", accessible_name=name, kind=kind, required=required
    )


SNAPSHOT = FormSnapshot(
    url="https://ats.rippling.com/x/apply",
    page_title="Apply",
    page_kind="form",
    ats="rippling",
    fields=[
        field("f_01", "First name"),
        field("f_02", "Email"),
        field("f_03", "Select the second word of this sentence", kind="attention_check"),
        field("f_04", "Are you authorized to work in the US?"),
    ],
)


class StubClient:
    """Stands in for anthropic.Anthropic().messages.parse."""

    def __init__(self, plan: FillPlan):
        self._plan = plan
        self.calls = []

    @property
    def messages(self):
        return self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return type("R", (), {"parsed_output": self._plan, "usage": None})()


def test_low_confidence_values_become_unresolved():
    raw = FillPlan(
        fields=[
            PlannedField(field_id="f_01", value="Johny", source="profile", confidence=0.99, note="from profile"),
            PlannedField(field_id="f_02", value="guess@x.com", source="generated", confidence=0.4, note="guessed"),
        ]
    )
    safe = apply_safety_rules(raw, SNAPSHOT)
    ids = {f.field_id for f in safe.fields}
    assert "f_01" in ids
    assert "f_02" not in ids
    assert any(u.field_id == "f_02" for u in safe.unresolved)


def test_attention_checks_are_always_unresolved_even_at_full_confidence():
    raw = FillPlan(
        fields=[
            PlannedField(field_id="f_03", value="value", source="generated", confidence=1.0, note="easy"),
        ]
    )
    safe = apply_safety_rules(raw, SNAPSHOT)
    assert not safe.fields
    assert any("attention" in u.reason.lower() for u in safe.unresolved)


def test_generated_work_authorization_answers_are_refused():
    raw = FillPlan(
        fields=[
            PlannedField(field_id="f_04", value="Yes", source="generated", confidence=0.95, note="inferred"),
        ]
    )
    safe = apply_safety_rules(raw, SNAPSHOT)
    assert not safe.fields
    assert any("authorization" in u.reason.lower() for u in safe.unresolved)


def test_profile_sourced_work_authorization_is_allowed():
    raw = FillPlan(
        fields=[
            PlannedField(field_id="f_04", value="Yes", source="profile", confidence=0.99, note="from profile"),
        ]
    )
    safe = apply_safety_rules(raw, SNAPSHOT)
    assert [f.field_id for f in safe.fields] == ["f_04"]


def test_a_plan_for_an_unknown_field_id_is_dropped():
    raw = FillPlan(
        fields=[
            PlannedField(field_id="f_99", value="x", source="profile", confidence=1.0, note="hallucinated"),
        ]
    )
    safe = apply_safety_rules(raw, SNAPSHOT)
    assert not safe.fields
    assert any(u.field_id == "f_99" for u in safe.unresolved)


def test_build_plan_sends_the_snapshot_and_the_cached_profile():
    expected = FillPlan(fields=[], unresolved=[])
    client = StubClient(expected)
    profile = load_profile(Path("profile.example.yaml"))

    build_plan(client, SNAPSHOT, profile)

    call = client.calls[0]
    assert call["output_format"] is FillPlan
    # the profile rides in a cached system block
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    # the snapshot is in the user message, as JSON
    assert "f_01" in str(call["messages"])


def test_endorsing_a_prefilled_value_we_cannot_confirm_is_refused():
    snapshot = FormSnapshot(
        url="https://x", page_title="t", page_kind="form",
        fields=[
            FormField(
                field_id="f_10", role="textbox", accessible_name="Current employer",
                kind="text", required=False, current_value="Acme Corp",
            )
        ],
    )
    raw = FillPlan(fields=[
        PlannedField(field_id="f_10", value="Acme Corp", source="generated",
                     confidence=0.9, note="already filled, looks fine"),
    ])
    safe = apply_safety_rules(raw, snapshot)
    assert not safe.fields
    assert any("parser" in u.reason.lower() for u in safe.unresolved)


def test_profile_values_overwrite_a_prefilled_field():
    snapshot = FormSnapshot(
        url="https://x", page_title="t", page_kind="form",
        fields=[
            FormField(
                field_id="f_11", role="textbox", accessible_name="First name",
                kind="text", required=True, current_value="Jonathan",
            )
        ],
    )
    raw = FillPlan(fields=[
        PlannedField(field_id="f_11", value="Johny", source="profile",
                     confidence=0.99, note="from profile; parser guessed Jonathan"),
    ])
    safe = apply_safety_rules(raw, snapshot)
    assert [f.value for f in safe.fields] == ["Johny"]


def test_confidence_floor_is_documented_not_magic():
    assert 0.0 < CONFIDENCE_FLOOR < 1.0
```

- [ ] **Step 3: Run it and watch it fail**

Run: `pytest tests/test_plan.py -v`
Expected: `ModuleNotFoundError: No module named 'job_agent.plan'`

- [ ] **Step 4: Write `src/job_agent/plan.py`**

```python
"""Turn a FormSnapshot plus a Profile into a FillPlan.

The model decides what goes in each field. It never touches the page — this
module returns a plan, and fill.py executes it. That split is what makes the
planner testable with a stub and the executor testable with a fixture.
"""

import json
import re

import anthropic  # noqa: F401  (imported for type clarity at call sites)

from job_agent.config import MAX_TOKENS, PLANNER_MODEL
from job_agent.models import FillPlan, FormSnapshot, PlannedField, Profile, Unresolved
from job_agent.prompt import cached_system, profile_system_prompt

# Below this, a value is treated as a guess and routed to the human.
CONFIDENCE_FLOOR = 0.6

# Answers that must come from the profile verbatim or not at all. A wrong
# value here is a misrepresentation on a real application.
SENSITIVE_PATTERNS = [
    (re.compile(r"authoriz|sponsor|visa|work permit|eligible to work", re.I), "work authorization"),
    (re.compile(r"\bgpa\b|grade point", re.I), "GPA"),
    (re.compile(r"salary|compensation|pay expectation", re.I), "salary"),
    (re.compile(r"gender|race|ethnic|veteran|disab|sexual orientation", re.I), "EEO/demographic"),
    (re.compile(r"degree|graduat", re.I), "degree or dates"),
]

PLANNER_INSTRUCTIONS = """\
You are filling out one page of a job application form.

You will receive a JSON description of every field on the page. For each field
you can answer, return an entry in `fields` with:
  - field_id: exactly as given. Never invent one.
  - value: what to type, select, or check.
  - source: "profile" if taken from the candidate facts above; "generated" if
    you wrote it; "default" for a conventional safe answer such as declining
    to self-identify.
  - confidence: 0.0-1.0, your honest estimate.
  - note: one short line saying where the value came from.

Some fields arrive with a `current_value` already in them, because the site
parsed the candidate's résumé to prefill the form. Résumé parsers are
unreliable. Treat `current_value` as a third party's guess, never as correct:

- If the candidate facts cover that field, plan a value anyway. Yours
  overwrites theirs.
- If the facts do NOT cover it and `current_value` is non-empty, mark it
  `unresolved`, saying it was prefilled and cannot be verified. Do not endorse
  it.

For anything you cannot answer from the facts, put it in `unresolved` with a
reason. Leaving a field unresolved is always better than guessing.

Absolute rules:
- Never generate work authorization, sponsorship, visa, GPA, degree, date,
  salary, or EEO/demographic answers. Those come from the candidate facts
  verbatim, or the field is unresolved.
- Never answer a field whose kind is "attention_check".
- Never use a field_id that is not in the snapshot.
"""


def build_plan(client, snapshot: FormSnapshot, profile: Profile, job_context: str | None = None) -> FillPlan:
    """Ask the planner model for a FillPlan, then apply the safety rules."""
    system = cached_system(profile_system_prompt(profile) + "\n\n" + PLANNER_INSTRUCTIONS)

    user = ["Here is the form page as JSON:", snapshot.model_dump_json(indent=2)]
    if job_context:
        user += ["", "Job description context:", job_context]

    response = client.messages.parse(
        model=PLANNER_MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": "\n".join(user)}],
        output_format=FillPlan,
    )
    return apply_safety_rules(response.parsed_output, snapshot)


def apply_safety_rules(plan: FillPlan, snapshot: FormSnapshot) -> FillPlan:
    """Enforce in code what the prompt merely asks for.

    A prompt rule is a request. This function is the guarantee.
    """
    by_id = {f.field_id: f for f in snapshot.fields}
    kept: list[PlannedField] = []
    unresolved: list[Unresolved] = list(plan.unresolved)

    for planned in plan.fields:
        field = by_id.get(planned.field_id)

        if field is None:
            unresolved.append(Unresolved(field_id=planned.field_id, reason="field_id is not in the snapshot"))
            continue

        if field.kind == "attention_check":
            unresolved.append(Unresolved(
                field_id=planned.field_id,
                reason="attention check — must be answered by a human, never by the agent",
            ))
            continue

        if planned.confidence < CONFIDENCE_FLOOR:
            unresolved.append(Unresolved(
                field_id=planned.field_id,
                reason=f"confidence {planned.confidence:.2f} below floor {CONFIDENCE_FLOOR}",
            ))
            continue

        # A prefilled value the profile cannot confirm is unverified, not done.
        if (
            field.current_value
            and planned.source not in {"profile", "answer_bank"}
            and str(planned.value).strip() == field.current_value.strip()
        ):
            unresolved.append(Unresolved(
                field_id=planned.field_id,
                reason="prefilled by the site's résumé parser and not confirmable "
                       "from the profile — parsers get fields wrong, so a human "
                       "must check this one",
            ))
            continue

        if planned.source == "generated":
            haystack = f"{field.accessible_name} {field.help_text or ''}"
            hit = next((label for pattern, label in SENSITIVE_PATTERNS if pattern.search(haystack)), None)
            if hit:
                unresolved.append(Unresolved(
                    field_id=planned.field_id,
                    reason=f"{hit} may never be generated — needs a profile value or a human",
                ))
                continue

        kept.append(planned)

    return FillPlan(fields=kept, unresolved=unresolved)
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_plan.py -v`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add src/job_agent/models.py src/job_agent/plan.py tests/test_plan.py
git commit -m "feat: FillPlan planner with safety rules enforced in code"
```

---

### Task 5: End to end against the real form

**Files:**
- Create: `scripts/plan_demo.py`
- Modify: `NOTES.md`

**Interfaces:**
- Consumes: everything above

- [ ] **Step 1: Write `scripts/plan_demo.py`**

```python
"""Extract a real application form and plan how to fill it. Fills nothing.

Run:  python scripts/plan_demo.py <url>
      python scripts/plan_demo.py            # uses the committed Rippling fixture
"""

import sys
from pathlib import Path

import anthropic

from job_agent.browser import browser_context
from job_agent.config import require_api_key
from job_agent.extract import extract_snapshot
from job_agent.plan import build_plan
from job_agent.profile import load_profile

FIXTURE = (Path("tests/fixtures/rippling_apply.html").resolve()).as_uri()


def main() -> None:
    require_api_key()
    url = sys.argv[1] if len(sys.argv) > 1 else FIXTURE

    with browser_context(headless=True) as ctx:
        page = ctx.new_page()
        page.goto(url)
        page.wait_for_timeout(2000)
        snapshot = extract_snapshot(page)

    print(f"{len(snapshot.fields)} fields, ats={snapshot.ats}")
    print(f"snapshot payload: {len(snapshot.model_dump_json())} chars\n")

    plan = build_plan(anthropic.Anthropic(), snapshot, load_profile())

    by_id = {f.field_id: f for f in snapshot.fields}
    print("PLANNED")
    for p in plan.fields:
        flag = "  <-- REVIEW" if p.source == "generated" else ""
        print(f"  {p.source:12} {by_id[p.field_id].accessible_name[:34]:36} {str(p.value)[:36]}{flag}")

    print("\nNEEDS A HUMAN")
    for u in plan.unresolved:
        name = by_id[u.field_id].accessible_name[:34] if u.field_id in by_id else u.field_id
        print(f"  {name:36} {u.reason}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it against the fixture**

Run: `python scripts/plan_demo.py`

Check by eye:
- First name / Last name / Email / Phone / LinkedIn come back `source=profile` with correct values
- The attention check appears under NEEDS A HUMAN
- Any EEO field is `default` (declined) or unresolved — never `generated`
- Nothing in PLANNED is wrong about you

- [ ] **Step 3: Run it against the live page**

```bash
python scripts/plan_demo.py "https://ats.rippling.com/en-CA/edgehog-trading/jobs/96354af0-1bd0-4703-a654-e3d591b07777/apply?jobBoardSlug=edgehog-trading&jobId=96354af0-1bd0-4703-a654-e3d591b07777&step=application"
```

Compare with the fixture run. Differences mean the fixture has drifted from the live page and should be recaptured.

- [ ] **Step 4: Check the en-CA locale question**

The posting URL is `en-CA` while the job is in Chicago. Look at what the live form actually asks about work eligibility — Canadian or US. Record the answer in `NOTES.md`; it determines which `work_authorization` fields matter in Stage 6.

- [ ] **Step 5: Find out exactly what the résumé parser gets wrong**

Upload `docs/resume.pdf` to the résumé input in a scratch script, wait for the
parse, and re-extract the snapshot. Then compare every populated
`current_value` against the profile and write down which ones are wrong.

That list is the useful artifact: a concrete record of what Rippling's parser
mis-extracts from *your* résumé. It tells Stage 6 which fields always need
overwriting, and it is a good line in NOTES.md.

Expected, from how these parsers generally behave: names split oddly, phone
formatting mangled, dates approximate, employer or title subtly wrong.

**The agent must never accept a prefilled value as correct just because it is
non-empty.** Confirm `apply_safety_rules` routes an unconfirmable prefilled
field to the human.

- [ ] **Step 6: Write the Stage 4 + 5 section of `NOTES.md`**

Record: how many fields the snapshot found, its size in characters versus a screenshot, which fields the planner sourced from the profile versus left unresolved, whether the safety rules fired, and the two findings above.

- [ ] **Step 7: Commit**

```bash
git add scripts/plan_demo.py NOTES.md
git commit -m "feat: end-to-end extract and plan against the real Rippling form"
```

---

## Stage Exit Criteria

- [ ] `pytest` green; no test makes an API call, and no test loads a live page
- [ ] The extractor recovers correct labels from Rippling despite hashed `name` attributes
- [ ] Requiredness is read from `aria-required`, verified against a field known to be optional
- [ ] The attention-check question is classified and never planned
- [ ] `apply_safety_rules` demonstrably drops a generated work-authorization answer
- [ ] A `FormSnapshot` of the real form is under 20KB of JSON
- [ ] `plan_demo.py` produces a plan you would actually be willing to submit

## What Stage 6 Needs From This

Stage 6 executes a `FillPlan` with `locator_for` and verifies every write by
reading it back. The open questions it inherits:

- fill ordering is settled: **upload the résumé first, re-extract, then
  overwrite every field the profile knows.** Never "fill only the gaps" — a
  non-empty field is not a correct field
- which specific fields Rippling's parser gets wrong on this résumé (Task 5,
  Step 5), since those need overwriting every time
- whether `en-CA` changes the work-eligibility questions
- whether any accessible name is ambiguous enough to need an occurrence index
