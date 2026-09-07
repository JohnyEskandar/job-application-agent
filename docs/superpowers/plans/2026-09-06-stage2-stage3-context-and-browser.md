# Stage 2 + Stage 3: Cached Context and the Browser

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the profile out of a tool and into a prompt-cached system prompt, measuring the difference. Then stand up a persistent browser that stays logged in between runs — with no LLM anywhere in it.

**Architecture:** Stage 2 replaces `stage1/tools.py` with a validated `Profile` model rendered into the `system` field, carrying a `cache_control` breakpoint. `run_conversation` gains a `system` parameter and makes `tools` optional, so a no-tool call is a single turn. Stage 3 is pure Playwright: a persistent Chromium profile directory means a login survives process restarts, and everything is tested against local HTML fixtures rather than live sites.

**Tech Stack:** Python 3.14.7, `anthropic` 1.x, `pydantic` 2.x, `pyyaml`, `playwright` 1.62 (sync API), `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-06-job-application-agent-design.md`

## Global Constraints

- Models split by stage: `claude-haiku-4-5` (`config.MODEL`) here; `claude-opus-5` (`config.PLANNER_MODEL`) is reserved for Stage 5. Haiku 4.5 rejects `thinking={"type": "adaptive"}` with a 400 — do not add it.
- **Playwright sync API only.** `from playwright.sync_api import sync_playwright`. No `async`/`await` anywhere in this project.
- **Stage 3 contains no LLM calls.** Not one. If a task here seems to need the model, it belongs in Stage 4.
- `profile.yaml` is real personal data and is gitignored. `profile.example.yaml` is fake and committed.
- `browser-profile/` (the persistent Chromium dir) is gitignored — it holds session cookies.
- Run everything from an activated venv, or prefix `.venv/bin/`.
- Commit at the end of each task; the suite must be green first.

---

### Task 1: A validated Profile, loaded from YAML

**Files:**
- Create: `src/job_agent/models.py`
- Create: `src/job_agent/profile.py`
- Create: `profile.example.yaml`
- Create: `profile.yaml` (not committed — your real data)
- Test: `tests/test_profile.py`

**Interfaces:**
- Consumes: `job_agent.config.PROJECT_ROOT`
- Produces: `models.Profile`, `models.Education`, `models.Experience`, `models.WorkAuthorization`; `profile.load_profile(path: Path | None = None) -> Profile`

- [ ] **Step 1: Write the failing test**

`tests/test_profile.py`:

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from job_agent.models import Profile
from job_agent.profile import load_profile


def test_example_profile_loads_and_validates():
    profile = load_profile(Path("profile.example.yaml"))
    assert profile.identity.first_name
    assert profile.identity.email
    assert profile.education, "at least one school"


def test_missing_required_field_fails_loudly(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("identity:\n  first_name: Alex\n")
    with pytest.raises(ValidationError):
        load_profile(bad)


def test_unknown_field_is_rejected_not_silently_ignored(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "identity:\n"
        "  first_name: Alex\n"
        "  last_name: Kim\n"
        "  email: a@b.com\n"
        "  phone: '555'\n"
        "  favourite_colour: blue\n"
    )
    with pytest.raises(ValidationError):
        load_profile(bad)


def test_missing_file_says_which_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="nope.yaml"):
        load_profile(tmp_path / "nope.yaml")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `pytest tests/test_profile.py -v`
Expected: `ModuleNotFoundError: No module named 'job_agent.models'`

- [ ] **Step 3: Write `src/job_agent/models.py`**

```python
"""Shared data shapes. Every module speaks these types."""

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    """Reject unknown fields instead of silently dropping them.

    A typo in profile.yaml should be an error, not a field that quietly
    never gets filled in on a real job application.
    """

    model_config = ConfigDict(extra="forbid")


class Identity(Strict):
    first_name: str
    last_name: str
    email: str
    phone: str
    pronouns: str | None = None


class Location(Strict):
    city: str
    state: str
    country: str = "United States"
    postal_code: str | None = None
    willing_to_relocate: bool = False


class Links(Strict):
    linkedin: str | None = None
    github: str | None = None
    portfolio: str | None = None


class WorkAuthorization(Strict):
    authorized_to_work_us: bool
    requires_sponsorship_now: bool
    requires_sponsorship_future: bool
    status: str | None = None


class Education(Strict):
    school: str
    degree: str
    field: str
    start: str
    end: str
    gpa: str | None = None


class Experience(Strict):
    company: str
    title: str
    start: str
    end: str
    location: str | None = None
    bullets: list[str] = Field(default_factory=list)


class Preferences(Strict):
    desired_salary: str | None = None
    earliest_start_date: str | None = None
    notice_period: str | None = None
    remote_preference: str | None = None


class Profile(Strict):
    identity: Identity
    location: Location
    links: Links = Field(default_factory=Links)
    work_authorization: WorkAuthorization
    education: list[Education] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    preferences: Preferences = Field(default_factory=Preferences)
```

Note: `email` is a plain `str`. Pydantic's `EmailStr` would validate the format but needs the `email-validator` package — add it later if that's wanted.

- [ ] **Step 4: Write `src/job_agent/profile.py`**

```python
"""Load and validate profile.yaml."""

from pathlib import Path

import yaml

from job_agent.config import PROJECT_ROOT
from job_agent.models import Profile

DEFAULT_PROFILE_PATH = PROJECT_ROOT / "profile.yaml"


def load_profile(path: Path | None = None) -> Profile:
    """Read a profile YAML file and validate it into a Profile.

    Validation is strict: unknown keys raise rather than being ignored, so a
    typo surfaces here instead of as a blank field on a job application.
    """
    path = Path(path) if path is not None else DEFAULT_PROFILE_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"No profile at {path}. Copy profile.example.yaml to profile.yaml "
            "and fill it in with your real details."
        )
    data = yaml.safe_load(path.read_text()) or {}
    return Profile.model_validate(data)
```

- [ ] **Step 5: Write `profile.example.yaml` (committed, fake data)**

```yaml
identity:
  first_name: Alex
  last_name: Kim
  email: alex.kim@example.com
  phone: "+1 555 010 0100"

location:
  city: St. Louis
  state: MO
  country: United States
  postal_code: "63130"
  willing_to_relocate: true

links:
  linkedin: https://linkedin.com/in/example
  github: https://github.com/example

work_authorization:
  authorized_to_work_us: true
  requires_sponsorship_now: false
  requires_sponsorship_future: false
  status: US Citizen

education:
  - school: Example University
    degree: B.S.
    field: Computer Science
    start: "2022-08"
    end: "2026-05"
    gpa: "3.8"

experience:
  - company: Example Corp
    title: Software Engineering Intern
    start: "2025-06"
    end: "2025-08"
    location: Remote
    bullets:
      - Built an internal dashboard used by the support team.
      - Reduced a nightly batch job from 40 minutes to 6.

skills:
  - Python
  - TypeScript
  - React

preferences:
  desired_salary: "Open to discussion"
  earliest_start_date: "2026-06-01"
  remote_preference: Hybrid
```

- [ ] **Step 6: Create your real `profile.yaml`**

```bash
cp profile.example.yaml profile.yaml
# edit profile.yaml with your real details
git status --short   # profile.yaml must NOT appear
```

Fill it in properly — every field. Stage 2's caching measurement depends on the profile being large enough to cache (see Task 3), and Stages 5-7 fill real applications from it.

- [ ] **Step 7: Run the tests**

Run: `pytest tests/test_profile.py -v`
Expected: 4 passed

- [ ] **Step 8: Commit**

```bash
git add src/job_agent/models.py src/job_agent/profile.py profile.example.yaml tests/test_profile.py
git status --short          # profile.yaml must NOT be staged
git commit -m "feat: strict Profile model loaded from YAML"
```

---

### Task 2: Render the profile into a system prompt

**Files:**
- Create: `src/job_agent/prompt.py`
- Modify: `src/job_agent/stage1/loop.py`
- Test: `tests/test_prompt.py`
- Test: `tests/test_stage1_loop.py` (add two cases)

**Interfaces:**
- Consumes: `models.Profile`
- Produces: `prompt.profile_system_prompt(profile: Profile) -> str`, `prompt.cached_system(text: str) -> list[dict]`; `run_conversation(..., system: list[dict] | None = None, tools: list[dict] | None = None)`

- [ ] **Step 1: Write the failing test**

`tests/test_prompt.py`:

```python
from pathlib import Path

from job_agent.profile import load_profile
from job_agent.prompt import cached_system, profile_system_prompt


def test_prompt_contains_the_facts_a_form_would_ask_for():
    profile = load_profile(Path("profile.example.yaml"))
    text = profile_system_prompt(profile)
    assert profile.identity.first_name in text
    assert profile.identity.email in text
    assert profile.education[0].school in text
    assert "sponsorship" in text.lower()


def test_prompt_is_deterministic_because_caching_needs_a_stable_prefix():
    profile = load_profile(Path("profile.example.yaml"))
    assert profile_system_prompt(profile) == profile_system_prompt(profile)


def test_cached_system_marks_a_breakpoint():
    blocks = cached_system("hello")
    assert blocks == [
        {"type": "text", "text": "hello", "cache_control": {"type": "ephemeral"}}
    ]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `pytest tests/test_prompt.py -v`
Expected: `ModuleNotFoundError: No module named 'job_agent.prompt'`

- [ ] **Step 3: Write `src/job_agent/prompt.py`**

```python
"""Render a Profile into the system prompt.

The profile is static, small, and needed on every turn — so it goes here,
not behind a tool call. Tools are verbs; context is nouns.
"""

from job_agent.models import Profile

INSTRUCTIONS = """\
You are helping a specific job candidate complete employment applications.
Everything you need to know about them is below.

Rules:
- Answer only from the facts given. Never invent a detail about this person.
- If a question cannot be answered from these facts, say exactly what is
  missing rather than guessing.
- Never infer work authorization, salary, dates, or GPA. Those must come from
  the facts below verbatim or not at all.
"""


def profile_system_prompt(profile: Profile) -> str:
    """Render the profile as stable, deterministic text.

    Determinism matters: prompt caching is a prefix match, so any byte that
    changes between requests invalidates the cache. No timestamps, no dict
    ordering surprises, no random IDs.
    """
    p = profile
    lines = [
        INSTRUCTIONS,
        "## Candidate",
        f"Name: {p.identity.first_name} {p.identity.last_name}",
        f"Email: {p.identity.email}",
        f"Phone: {p.identity.phone}",
        f"Location: {p.location.city}, {p.location.state}, {p.location.country}",
        f"Postal code: {p.location.postal_code or 'not provided'}",
        f"Willing to relocate: {'yes' if p.location.willing_to_relocate else 'no'}",
        "",
        "## Links",
        f"LinkedIn: {p.links.linkedin or 'none'}",
        f"GitHub: {p.links.github or 'none'}",
        f"Portfolio: {p.links.portfolio or 'none'}",
        "",
        "## Work authorization",
        f"Authorized to work in the US: {'yes' if p.work_authorization.authorized_to_work_us else 'no'}",
        f"Requires sponsorship now: {'yes' if p.work_authorization.requires_sponsorship_now else 'no'}",
        f"Requires sponsorship in future: {'yes' if p.work_authorization.requires_sponsorship_future else 'no'}",
        f"Status: {p.work_authorization.status or 'not provided'}",
        "",
        "## Education",
    ]
    for e in p.education:
        lines.append(
            f"- {e.degree} {e.field}, {e.school} ({e.start} to {e.end})"
            + (f", GPA {e.gpa}" if e.gpa else "")
        )

    lines += ["", "## Experience"]
    for x in p.experience:
        lines.append(f"- {x.title}, {x.company} ({x.start} to {x.end})")
        for bullet in x.bullets:
            lines.append(f"    - {bullet}")

    lines += [
        "",
        "## Skills",
        ", ".join(p.skills) if p.skills else "none listed",
        "",
        "## Preferences",
        f"Desired salary: {p.preferences.desired_salary or 'not provided'}",
        f"Earliest start date: {p.preferences.earliest_start_date or 'not provided'}",
        f"Notice period: {p.preferences.notice_period or 'not provided'}",
        f"Remote preference: {p.preferences.remote_preference or 'not provided'}",
    ]
    return "\n".join(lines)


def cached_system(text: str) -> list[dict]:
    """Wrap system text in a block with a cache breakpoint.

    `system` must be a LIST of blocks for this — a plain string cannot carry
    cache_control.
    """
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]
```

- [ ] **Step 4: Add two cases to `tests/test_stage1_loop.py`**

```python
def test_system_prompt_is_forwarded_on_every_request():
    client = FakeClient([tool_response("get_profile"), text_response("ok")])
    system = [{"type": "text", "text": "facts"}]
    run_conversation(client, "q", system=system)

    for call in client.calls:
        assert call["system"] == system


def test_tools_are_omitted_entirely_when_there_are_none():
    client = FakeClient([text_response("ok")])
    result = run_conversation(client, "q", tools=None)

    assert "tools" not in client.calls[0]
    assert result.turns == 1
```

The second one matters: sending `tools=[]` is not the same as omitting the key. With the profile in context there is nothing to call, and a no-tool request should be one turn.

- [ ] **Step 5: Run both test files and watch the new ones fail**

Run: `pytest tests/test_prompt.py tests/test_stage1_loop.py -v`
Expected: `test_prompt.py` passes; the two new loop tests fail with `TypeError: run_conversation() got an unexpected keyword argument 'system'`

- [ ] **Step 6: Update `run_conversation` in `src/job_agent/stage1/loop.py`**

Change the signature and the request construction:

```python
def run_conversation(
    client,
    user_message: str,
    *,
    system: list[dict] | None = None,
    tools: list[dict] | None = None,
    dispatch=dispatch_tool,
    model: str = MODEL,
    max_turns: int = 10,
) -> ConversationResult:
```

Then inside the loop, build the kwargs conditionally instead of passing `tools=tools` unconditionally:

```python
        request = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "messages": messages,
        }
        if system is not None:
            request["system"] = system
        if tools:
            request["tools"] = tools

        response = client.messages.create(**request)
```

Note `if tools:` not `if tools is not None:` — an empty list should also be omitted.

Also change the default: `tools` no longer defaults to `TOOLS`. Callers that want tools pass them.

- [ ] **Step 7: Run the whole suite**

Run: `pytest -v`
Expected: all green. `scripts/chained_demo.py` now needs `tools=TOOLS` passed explicitly — update it:

```python
    result = run_conversation(client, QUESTION, tools=TOOLS)
```

and add `from job_agent.stage1.tools import TOOLS` to its imports.

- [ ] **Step 8: Commit**

```bash
git add src/job_agent/prompt.py src/job_agent/stage1/loop.py tests/ scripts/chained_demo.py
git commit -m "feat: render profile into a cache-marked system prompt"
```

---

### Task 3: Measure what the change bought, then delete the tools

This is the task that justifies Stage 1's deliberate detour. Do not skip the measurement — the number is the point.

**Files:**
- Create: `scripts/cached_profile_demo.py`
- Delete: `src/job_agent/stage1/tools.py`, `tests/test_stage1_tools.py`, `scripts/manual_roundtrip.py`, `scripts/chained_demo.py`
- Modify: `src/job_agent/stage1/loop.py` (drop the `dispatch_tool` import)
- Modify: `NOTES.md`

**Interfaces:**
- Consumes: `profile.load_profile`, `prompt.profile_system_prompt`, `prompt.cached_system`, `loop.run_conversation`
- Produces: nothing importable

- [ ] **Step 1: Write `scripts/cached_profile_demo.py`**

```python
"""Stage 2: the profile as cached context instead of a tool.

Run it TWICE:  python scripts/cached_profile_demo.py

Run 1 writes the cache. Run 2 should read it. Compare the usage numbers.
"""

import anthropic

from job_agent.config import require_api_key
from job_agent.profile import load_profile
from job_agent.prompt import cached_system, profile_system_prompt
from job_agent.stage1.loop import run_conversation

QUESTION = "What school does the candidate attend, and do they need sponsorship?"


def main() -> None:
    require_api_key()
    client = anthropic.Anthropic()

    profile = load_profile()
    system = cached_system(profile_system_prompt(profile))

    print(f"system prompt: {len(system[0]['text'])} characters")

    result = run_conversation(client, QUESTION, system=system, tools=None)

    print(f"\nturns: {result.turns}   (Stage 1 needed 2 for this — no tool round-trip now)")
    print(f"\nanswer:\n{result.final_text}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it once, then again, and read the usage**

`run_conversation` does not currently expose `usage`. Add it — in `loop.py`, extend the dataclass:

```python
@dataclass
class ConversationResult:
    messages: list[dict]
    final_text: str
    turns: int
    usage: object | None = None
```

and set it on return: `return ConversationResult(messages, final_text, turn, response.usage)`.

Then print it in the demo:

```python
    u = result.usage
    print(f"input                 {u.input_tokens}")
    print(f"cache_creation_input  {u.cache_creation_input_tokens}")
    print(f"cache_read_input      {u.cache_read_input_tokens}")
```

Run: `python scripts/cached_profile_demo.py` twice.

Expected:
- **Run 1** — `cache_creation_input_tokens` > 0, `cache_read_input_tokens` == 0
- **Run 2** — `cache_creation_input_tokens` == 0, `cache_read_input_tokens` > 0
- **Both runs** — `turns: 1`, versus 2 in Stage 1

- [ ] **Step 3: If `cache_read_input_tokens` is 0 on run 2, the prompt is too short**

The minimum cacheable prefix is **model-dependent and not monotonic across
generations**. Claude Opus 5 needs 512 tokens; Opus 4.8 / Sonnet 5 need 1024;
Opus 4.7 needs 2048; **Haiku 4.5 needs 4096**. Below the threshold the
`cache_control` marker is silently ignored — no error, just zeros.

This means Stage 2's caching **cannot be demonstrated on Haiku 4.5** with a
profile of realistic size. Run the demo with `--planner` (Opus 5) to see it
work.

Check the size:

```bash
python -c "
from job_agent.profile import load_profile
from job_agent.prompt import profile_system_prompt
t = profile_system_prompt(load_profile())
print(len(t), 'chars ~', len(t)//4, 'tokens')
"
```

If it is under ~4000 characters, fill out more of `profile.yaml` — more experience bullets, more skills. This is not padding for its own sake: Stages 5-7 need that detail to fill real applications, and it is also what makes caching pay off.

Record the actual numbers before and after in `NOTES.md`.

- [ ] **Step 4: Delete Stage 1's tools**

```bash
git rm src/job_agent/stage1/tools.py tests/test_stage1_tools.py \
       scripts/manual_roundtrip.py scripts/chained_demo.py
```

Then remove the now-broken import from `loop.py`:

```python
from job_agent.stage1.tools import TOOLS, dispatch_tool
```

becomes

```python
from job_agent.stage1.dispatch import dispatch_tool
```

...and create `src/job_agent/stage1/dispatch.py` holding just the dispatcher and `UnknownToolError`, since the loop still needs a default dispatcher for Stages 6-7's real tools:

```python
"""Tool dispatch. The tools themselves arrive in Stage 6 (browser actions)."""


class UnknownToolError(Exception):
    """Raised when Claude requests a tool this dispatcher does not implement."""


def dispatch_tool(name: str, tool_input: dict) -> str:
    raise UnknownToolError(f"Claude requested an unknown tool: {name}")
```

Update `tests/test_stage1_loop.py`'s import from `job_agent.stage1.tools` to `job_agent.stage1.dispatch`.

- [ ] **Step 5: Run the suite**

Run: `pytest -v`
Expected: green, with the 6 deleted tool tests gone. Roughly 18 tests.

- [ ] **Step 6: Write the Stage 2 section of `NOTES.md`**

Record: the turn count before and after, the three usage numbers from both runs, and — in your own words — why static context belongs in the system prompt while tools are for actions.

- [ ] **Step 7: Commit**

```bash
git add -A
git status --short          # profile.yaml must NOT appear
git commit -m "feat: profile as cached context; delete the Stage 1 profile tools"
```

The diff on this commit is the interview story. It shows the tool version, the measurement, and the replacement.

---

### Task 4: A persistent browser, tested against local fixtures

No LLM from here to the end of the plan.

**Files:**
- Create: `src/job_agent/browser.py`
- Create: `tests/fixtures/simple_form.html`
- Test: `tests/test_browser.py`

**Interfaces:**
- Consumes: `job_agent.config.PROJECT_ROOT`
- Produces: `browser.browser_context(headless: bool = False, profile_dir: Path | None = None)` — a context manager yielding a Playwright `BrowserContext`; `browser.DEFAULT_PROFILE_DIR`

- [ ] **Step 1: Write the fixture `tests/fixtures/simple_form.html`**

```html
<!doctype html>
<html>
  <head><title>Application Form</title></head>
  <body>
    <h1>Apply</h1>
    <form>
      <label for="first_name">First name</label>
      <input id="first_name" name="first_name" type="text" required />

      <label for="email">Email</label>
      <input id="email" name="email" type="email" required />

      <label for="cover">Why do you want this role?</label>
      <textarea id="cover" name="cover"></textarea>

      <label for="source">How did you hear about us?</label>
      <select id="source" name="source">
        <option value="">Select...</option>
        <option value="linkedin">LinkedIn</option>
        <option value="referral">Referral</option>
      </select>

      <button id="submit" type="submit">Submit application</button>
    </form>
  </body>
</html>
```

A local file, so tests never touch the network and never depend on a real site staying up.

- [ ] **Step 2: Write the failing test**

`tests/test_browser.py`:

```python
from pathlib import Path

from job_agent.browser import browser_context

FIXTURE = (Path(__file__).parent / "fixtures" / "simple_form.html").resolve()
FIXTURE_URL = FIXTURE.as_uri()


def test_context_opens_and_loads_a_local_page():
    with browser_context(headless=True) as ctx:
        page = ctx.new_page()
        page.goto(FIXTURE_URL)
        assert page.title() == "Application Form"


def test_filling_a_field_actually_sticks():
    with browser_context(headless=True) as ctx:
        page = ctx.new_page()
        page.goto(FIXTURE_URL)
        page.fill("#first_name", "Alex")
        # read it back — a fill that silently reverts is the failure mode
        # that matters on real ATS forms
        assert page.input_value("#first_name") == "Alex"


def test_select_and_textarea_also_round_trip():
    with browser_context(headless=True) as ctx:
        page = ctx.new_page()
        page.goto(FIXTURE_URL)
        page.fill("#cover", "Because it is interesting.")
        page.select_option("#source", "referral")
        assert page.input_value("#cover") == "Because it is interesting."
        assert page.input_value("#source") == "referral"


def test_profile_directory_is_created(tmp_path):
    profile_dir = tmp_path / "browser-profile"
    with browser_context(headless=True, profile_dir=profile_dir):
        pass
    assert profile_dir.exists()


def test_screenshot_writes_a_file(tmp_path):
    shot = tmp_path / "page.png"
    with browser_context(headless=True) as ctx:
        page = ctx.new_page()
        page.goto(FIXTURE_URL)
        page.screenshot(path=str(shot))
    assert shot.exists() and shot.stat().st_size > 0
```

- [ ] **Step 3: Run it and watch it fail**

Run: `pytest tests/test_browser.py -v`
Expected: `ModuleNotFoundError: No module named 'job_agent.browser'`

- [ ] **Step 4: Write `src/job_agent/browser.py`**

```python
"""Browser lifecycle. No LLM in this module, deliberately.

Uses a PERSISTENT context: Chromium keeps cookies, localStorage, and session
state in a directory on disk, so a login survives process restarts. That is
what makes unattended runs possible on sites that require an account.
"""

from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import sync_playwright

from job_agent.config import PROJECT_ROOT

DEFAULT_PROFILE_DIR = PROJECT_ROOT / "browser-profile"


@contextmanager
def browser_context(headless: bool = False, profile_dir: Path | None = None):
    """Yield a Playwright BrowserContext backed by a persistent profile.

    headless=False by default: logging in and watching a form get filled both
    need a visible window. Tests pass headless=True.

    Note this returns a BrowserContext, not a Browser —
    launch_persistent_context skips the Browser object entirely.
    """
    profile_dir = Path(profile_dir) if profile_dir is not None else DEFAULT_PROFILE_DIR
    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            viewport={"width": 1400, "height": 1000},
        )
        try:
            yield context
        finally:
            context.close()
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_browser.py -v`
Expected: 5 passed. Slower than the other tests — each launches a real Chromium.

- [ ] **Step 6: Confirm `browser-profile/` is gitignored**

```bash
git check-ignore -v browser-profile
```

Expected: a match from `.gitignore`. It holds session cookies and must never be committed.

- [ ] **Step 7: Commit**

```bash
git add src/job_agent/browser.py tests/test_browser.py tests/fixtures/simple_form.html
git commit -m "feat: persistent Playwright context, tested against local fixtures"
```

---

### Task 5: Prove a login survives a restart

The whole reason for a persistent profile. Two separate script runs, in two separate processes, with the login only happening in the first.

**Files:**
- Create: `scripts/login_once.py`
- Create: `scripts/check_still_logged_in.py`
- Modify: `NOTES.md`

**Interfaces:**
- Consumes: `browser.browser_context`
- Produces: nothing importable

**Target URLs for this task.**

Public posting, no login needed — a real one you're considering applying to:

```
https://ats.rippling.com/en-CA/edgehog-trading/jobs/96354af0-1bd0-4703-a654-e3d591b07777
```

Graduate Quantitative Trader, Edgehog Trading, Chicago IL. **Rippling ATS** —
a platform not previously in the spec's list, now added. The form is *not* on
the posting page; it sits behind an "Apply now" button, which is exactly the
`find and follow Apply` step in spec section 6.

(Tracking parameters `?jobSite=...&fbclid=...` stripped — they're referral
tracking, not part of the address, and they make the URL non-deterministic
across shares.)

**One thing to check when you open it:** the path says `en-CA` but the job is
in Chicago. If that locale drives the form's work-authorization questions, you
could be shown *Canadian* eligibility questions for a US role. Worth confirming
before Stage 5 wires up `work_authorization` — answering the wrong country's
question on a real application is exactly the failure the never-generate list
exists to prevent.

Plus one site you actually log into, to prove persistence.

- [ ] **Step 1: Write `scripts/login_once.py`**

```python
"""Open a site in the persistent profile and wait while you log in by hand.

Run:  python scripts/login_once.py https://www.linkedin.com/login

Log in in the window that opens, then press Enter here. The session is saved
into browser-profile/ and survives process restarts.
"""

import sys

from job_agent.browser import DEFAULT_PROFILE_DIR, browser_context


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python scripts/login_once.py <url>")
    url = sys.argv[1]

    with browser_context(headless=False) as ctx:
        page = ctx.new_page()
        page.goto(url)
        print(f"\nOpened {url}")
        print("Log in in the browser window, then press Enter here.")
        input()
        print(f"Saved into {DEFAULT_PROFILE_DIR}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write `scripts/check_still_logged_in.py`**

```python
"""Reopen the same site in a NEW process and screenshot what we land on.

Run:  python scripts/check_still_logged_in.py https://www.linkedin.com/feed

If the persistent profile works, this shows a logged-in page without any
credentials being entered.
"""

import sys
from datetime import datetime
from pathlib import Path

from job_agent.browser import browser_context
from job_agent.config import PROJECT_ROOT


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python scripts/check_still_logged_in.py <url>")
    url = sys.argv[1]

    out_dir = PROJECT_ROOT / "runs" / datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    shot = out_dir / "logged_in_check.png"

    with browser_context(headless=False) as ctx:
        page = ctx.new_page()
        page.goto(url)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(shot), full_page=False)
        print(f"landed on: {page.url}")
        print(f"title:     {page.title()}")
        print(f"screenshot: {shot}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the login flow**

```bash
python scripts/login_once.py <your login URL>
```

Log in by hand in the window. Press Enter.

- [ ] **Step 4: Prove persistence in a fresh process**

```bash
python scripts/check_still_logged_in.py <a URL that requires being logged in>
```

You want `landed on:` to be the logged-in page, **not** a redirect to `/login`. That redirect is the failure signal.

If it does redirect: the site may be blocking automation rather than losing the session. Note which site and move on — that is a real finding for the spec's risk table, not a bug in your code.

- [ ] **Step 5: Navigate and fill a real posting**

Point `check_still_logged_in.py` at your actual job posting URL and confirm the page loads and screenshots. Then, in a Python REPL or a scratch script, try filling one real field on it:

```python
from job_agent.browser import browser_context
with browser_context() as ctx:
    page = ctx.new_page()
    page.goto("<your posting URL>")
    page.pause()          # opens Playwright Inspector — click around, copy selectors
```

`page.pause()` is the tool you will use constantly in Stage 4. It freezes the script and opens an inspector where you can point at an element and get a working selector.

- [ ] **Step 6: Confirm `runs/` is gitignored**

```bash
git check-ignore -v runs
```

Screenshots of logged-in pages contain personal data.

- [ ] **Step 7: Write the Stage 3 section of `NOTES.md`**

Record: which site you logged into, whether the session survived, what `page.pause()` showed you about the posting's HTML, and any site that blocked automation.

- [ ] **Step 8: Commit**

```bash
git add scripts/login_once.py scripts/check_still_logged_in.py NOTES.md
git status --short          # runs/ and browser-profile/ must NOT appear
git commit -m "feat: prove persistent login survives a process restart"
```

---

## Stage Exit Criteria

- [ ] `pytest` green, and no test makes a network call or an API call
- [ ] `cached_profile_demo.py` answers in **1 turn**, versus 2 in Stage 1
- [ ] Run 2 of that demo shows `cache_read_input_tokens` > 0
- [ ] `stage1/tools.py` is deleted and the suite still passes
- [ ] A login performed in one process is still active in a later one
- [ ] `profile.yaml`, `browser-profile/`, and `runs/` are all untracked
- [ ] `NOTES.md` has Stage 2 and Stage 3 sections with the real numbers in them

## What Stage 4 Needs From This

Stage 4 turns a live page into a `FormSnapshot`. It builds directly on
`browser_context` from Task 4 and on the selector work from Task 5, Step 5.

Before starting it, save 3-4 **real** application forms as HTML fixtures —
Rippling (the Edgehog posting above), Greenhouse, Lever, Ashby, and a Workday
wizard page. `page.content()` inside a
`browser_context` writes one out. Those fixtures are what make the extractor
testable without hammering live postings.
