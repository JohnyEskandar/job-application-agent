# Job Application Agent — Design

**Date:** 2026-09-06
**Status:** Approved design, not yet implemented
**Author:** Johny Eskandar (with Claude)

## 1. Purpose

Give the agent a URL to a job posting. It opens the posting in a real browser,
finds the application form, fills every field from a stored profile, drafts
answers to questions the profile does not cover, then stops and shows what it
is about to submit. On approval it clicks Submit and records what happened.

This is also a **learning project**. A secondary requirement is that the author
can explain every layer of it in a technical interview: the tool-use loop, why
tools are verbs and context is not, why a DOM snapshot beats a screenshot, and
where an LLM belongs in a system versus where deterministic code belongs.
That requirement shapes the build order (Section 9) and rules out reaching for
an agent framework that hides the loop.

## 2. Goals and Non-Goals

### Goals

- One command, one URL, one application.
- Works on an unknown site, not just on ATS platforms with hand-written support.
- Never submits without an explicit human yes.
- Never invents a fact about the candidate.
- Gets less interruptive over time as the answer bank fills up.
- Every layer independently testable without touching a live job posting.

### Non-Goals (deliberately cut)

- **Job discovery.** No board scraping, no search, no matching. You supply the URL.
- **Mass application.** One at a time, human-paced. A tool that fires off
  hundreds of applications is both a worse product and a worse interview story.
- **Resume tailoring.** The resume PDF is uploaded as-is. Per-job resume
  rewriting is a separate project with its own failure modes.
- **Multi-user, hosting, accounts.** Single user, local machine, local files.
- **A provider-abstraction layer as a reason to adopt a framework.** Swapping
  models is already cheap: `llm.py` is the only file importing `anthropic`, and
  everything downstream depends on `FillPlan`, not on a vendor. A second
  provider is one ~40-line class implementing the same protocol. LangGraph
  arrives in Stage 8.5 to be *evaluated*, not to solve this.
- **Beating bot detection.** If a site actively blocks automation, the agent
  surfaces that and hands control to the human. It does not fingerprint-spoof
  or solve CAPTCHAs.

## 3. Key Decisions

| Decision | Choice | Why |
|---|---|---|
| Language | Python 3.14.7, pinned via `uv python pin 3.14` | Playwright and the Anthropic SDK are both first-class; author is strongest here |
| Env | project `.venv`, activated | `python`/`pip`/`pytest` work bare; reproducible for anyone cloning |
| Browser | Playwright Chromium, `launch_persistent_context` | Logins survive between runs; real browser survives real ATS portals |
| Playwright API | **sync**, not async | No async coloring, readable stack traces. Nothing here is IO-bound enough to need concurrency |
| Model | `claude-haiku-4-5` for Stages 1-6; `claude-opus-5` + `thinking={"type": "adaptive"}` for the planner | Mechanics stages need a working loop, not judgment. Spend the better model only where field decisions are made. Note Haiku 4.5 rejects adaptive thinking |
| SDK | `anthropic` **1.x** (1.4.0 at time of writing) | Most tutorials online are written against 0.x; signatures moved and it is on `httpx2`. Expect copied snippets to need adjusting |
| Agent loop | hand-written, no framework | It is the thing being learned. No LangChain, no Tool Runner in v1 |
| Field decisions | LLM plans, code executes | The model never clicks. It emits a plan; Playwright runs it and verifies |
| Static profile | system prompt, **not** a tool | Needed every turn, cheap to include, and prompt-cacheable |
| Submission | human approval gate, always | An application cannot be un-sent |
| Storage | YAML profile + JSONL run log + screenshot dirs | No schema migrations, greppable, readable in a text editor |

### 3.1 Why the profile is not a tool

Stage 1 of the build (Section 9) deliberately implements `get_profile()` as a
Claude tool, proves the tool-use loop, and then **removes it**.

Static, small, always-needed data belongs in the system prompt. Making it a
tool costs a full extra round-trip on every run, and the model may simply not
call it. Tools are for things that are dynamic, expensive, or have side effects
— reading the page as it is *right now*, filling a field, uploading a file.
The rule: **tools are verbs; context is nouns.**

Both versions stay in git history. The refactor is the lesson.

### 3.2 Why a DOM snapshot, not screenshots

A vision loop (screenshot → model picks coordinates → click) is more general
but worse on every axis that matters here: a re-render invalidates coordinates,
failures are not reproducible, and a screenshot costs far more tokens than the
structured form it depicts.

Instead, `extract` walks the page and emits a compact JSON description of every
field. The model sees labels, types, options, and requiredness — everything it
needs to decide *what goes where* and nothing it needs to decide *how to click*.
Screenshots exist in this system for exactly one purpose: showing the human
what is about to be submitted.

## 4. Architecture

```
                 profile.yaml + resume.pdf          (hand-edited, gitignored)
                            |
   apply <url>  ->  browser  ->  jobctx  ->  [ flow loop ]  ->  review  ->  submit
                            |                    |                            |
                            |         extract -> plan -> fill                 |
                            |                    ^                            v
                            |                    |                        runlog
                            +-- persistent Chromium profile          (+ answer bank update)
```

### Module map

```
job_agent/
  config.py     paths, env loading, constants
  models.py     every Pydantic model; the shared vocabulary
  profile.py    load + validate profile.yaml; read/write answer bank
  browser.py    persistent Chromium lifecycle
  ats.py        detect ATS from URL/DOM; per-ATS quirks
  jobctx.py     scrape job title/company/description from the posting
  extract.py    Page -> FormSnapshot
  llm.py        Anthropic client; the only file that talks to the API
  plan.py       FormSnapshot + Profile + JobContext -> FillPlan
  fill.py       FillPlan -> executed, verified fields
  flow.py       the page loop and page classification
  review.py     terminal review gate
  runlog.py     run records, screenshots, answer-bank learning
  cli.py        argument parsing, entry points
```

Each module has one job and a narrow interface. `llm.py` is the **only** file
that imports `anthropic`; `fill.py` is the only file that mutates the page.
That separation is what makes Stage 3 (browser, no LLM) and Stage 5 (LLM, no
browser) testable in isolation.

## 5. Data Shapes

These are the contracts between modules. All are Pydantic models in `models.py`.

### Profile (`profile.yaml`)

```yaml
identity:      {first_name, last_name, email, phone, pronouns?}
location:      {city, state, country, postal_code, willing_to_relocate}
links:         {linkedin, github, portfolio?}
work_authorization:
  authorized_to_work_us: true
  requires_sponsorship_now: false
  requires_sponsorship_future: true
  status: "F-1 (OPT eligible)"
education:     [{school, degree, field, start, end, gpa?}]
experience:    [{company, title, start, end, location, bullets: [...]}]
skills:        [...]
documents:     {resume: ./docs/resume.pdf, transcript?: ...}
preferences:   {desired_salary, earliest_start_date, notice_period, remote_preference}
eeo:           {gender: decline, race: decline, veteran_status: decline, disability_status: decline}
answer_bank:   [{id, question_pattern, answer, times_used, last_used}]
```

`eeo` defaults to `decline` for every field. It is only ever answered from an
explicit value the human typed into the file.

### FormField / FormSnapshot

```python
class FormField(BaseModel):
    field_id: str                    # stable id we assign, e.g. "f_07"
    selector: str                    # Playwright selector resolving to this element
    label: str                       # visible label or aria-label
    kind: Literal["text", "textarea", "email", "tel", "number", "url",
                  "select", "radio", "checkbox", "file", "date", "combobox"]
    required: bool
    options: list[str] | None        # for select/radio/combobox
    current_value: str | None
    max_length: int | None
    help_text: str | None            # nearby hint text, char limits, etc.

class FormSnapshot(BaseModel):
    url: str
    page_title: str
    ats: str | None                  # "greenhouse" | "lever" | "ashby" | "workday" | None
    page_kind: Literal["form", "login", "review", "confirmation", "captcha", "unknown"]
    fields: list[FormField]
    next_buttons: list[str]          # selectors for Next/Continue
    submit_buttons: list[str]        # selectors for Submit/Apply
```

`field_id` matters: the model refers to fields by this opaque id, never by
selector. That keeps CSS out of the model's output and makes plans replayable
against a recorded snapshot in tests.

### FillPlan

```python
class PlannedField(BaseModel):
    field_id: str
    value: str | bool | list[str]
    source: Literal["profile", "answer_bank", "generated", "default"]
    confidence: float                # 0.0 - 1.0
    note: str                        # one line: where this came from

class Unresolved(BaseModel):
    field_id: str
    reason: str                      # why the model could not answer it

class FillPlan(BaseModel):
    fields: list[PlannedField]
    unresolved: list[Unresolved]
```

`source` is the spine of the whole safety story. It is what the review gate
displays, what decides whether a value needs human eyes, and what tells the
answer bank which responses are worth remembering.

### RunRecord (one JSONL line per application)

```python
class RunRecord(BaseModel):
    run_id: str                      # timestamp-based
    url: str
    company: str | None
    role: str | None
    ats: str | None
    started_at: datetime
    finished_at: datetime | None
    outcome: Literal["submitted", "abandoned", "failed", "needs_human"]
    pages: int
    fields_filled: int
    generated_answers: list[dict]    # question -> answer, for the answer bank
    screenshots: list[str]
    error: str | None
```

## 6. The Flow Loop

```
open url -> jobctx.scrape() -> find and follow "Apply" if the form is not on this page

loop (max 12 pages, max 3 visits to the same URL):
    snapshot = extract(page)
    match snapshot.page_kind:
        login        -> pause; tell human to log in in the open window; wait for keypress
        captcha      -> pause; hand over the browser; wait for keypress
        form         -> plan = plan(snapshot, profile, jobctx)
                        if plan.unresolved has a required field: ask human, save to answer bank
                        results = fill(page, plan)
                        if any required field failed to verify: retry once, then pause
                        click next_buttons[0]
        review       -> break to review gate
        confirmation -> log success; done
        unknown      -> screenshot, pause, ask human
```

**Page classification** is heuristic, not LLM: a form with a Submit button and
no editable required fields is a review page; a page containing a password
field is a login; a page with confirmation words and no form is a confirmation.
When heuristics are ambiguous the loop pauses rather than guessing — a wrong
guess here can mean submitting a half-filled application.

**Loop guards** exist because the most common agent failure is not a wrong
answer, it is an infinite loop. Twelve pages covers Workday's longest wizard
with room to spare; three visits to one URL means a Next click is not advancing.

## 7. The Review Gate

Before any Submit click, the terminal prints:

```
  Software Engineer Intern - Acme Corp   (greenhouse)
  9 fields across 3 pages

  profile      First name           Johny
  profile      Email                alex.kim@example.com
  profile      School               Washington University in St. Louis
  answer_bank  Sponsorship          Yes, will require sponsorship in the future
  generated    Why Acme?            "I have been following Acme's work on..."   <-- review
  default      Gender               Decline to self-identify

  Resume: docs/resume.pdf uploaded
  Screenshot: runs/2026-09-06T18-22/page3.png

  [s]ubmit  [e]dit a field  [o]pen browser  [a]bandon
```

`generated` rows are visually flagged. Editing a field writes the correction
back to the page **and** offers to save it to the answer bank, which is how the
system gets quieter over time.

Submit requires pressing `s`. There is no `--yes` flag and no timeout-defaults-
to-submit. This is the one place in the design where convenience loses.

## 8. Safety Rules

**Never LLM-generated, under any circumstance.** Work authorization and
sponsorship, EEO/demographics, degrees, dates, GPA, employment history,
salary expectations, references. These come from the profile verbatim or the
field goes to `unresolved` and the human is asked. Any of these being wrong is
a misrepresentation on a real job application, not a bug.

**Generated content is always flagged and always reviewed.** Free-text answers
and cover-letter prose are drafted from the profile and the job description,
shown in full at the review gate, and editable before submission.

**Confidence floor.** Any planned field below 0.6 confidence is treated as
unresolved regardless of what the model produced.

**Verification after fill.** Every field is read back after writing. Custom
comboboxes and React-controlled inputs frequently accept a `fill()` and then
silently revert; catching that is the difference between a working agent and
one that submits blank fields.

**Secrets and PII.** `.env`, `profile.yaml`, `runs/`, `browser-profile/`, and
`docs/resume.pdf` are all gitignored. `profile.example.yaml` is committed with
fake data so the repo is usable by someone else.

**Rate.** One application per invocation. No batching, no scheduling, no
overnight loops.

## 9. Build Stages

Each stage ends with working code, a passing test, and something new the author
can explain. No stage depends on a later stage.

| # | Build | Learned | Done when |
|---|---|---|---|
| 0 | `git init`, `.env` + `.gitignore`, `uv init`, venv, deps | project hygiene | `python -c "import anthropic, playwright"` passes |
| 1 | Hand-written tool loop: `get_profile` as a tool, manual `tool_result`, then a second tool (`get_resume_text`) and generalize to `while stop_reason == "tool_use"` | tool schemas, `tool_use`/`tool_result` pairing by id, `stop_reason`, conversation state, parallel vs. chained calls | Claude answers a question needing both tools by chaining calls; the full message transcript is printed and understood |
| 2 | Delete the tool. Profile → Pydantic model → system prompt. Add prompt caching | tools-are-verbs, context design, cache economics | Same answers, one fewer round-trip; `cache_read_input_tokens` > 0 on run two |
| 3 | Playwright only, **no LLM**: persistent context, navigate, fill a field by hand, screenshot | browser automation, selectors, why persistent auth matters | Logs into a site once; a second run is already authenticated |
| 4 | `extract.py`: page → `FormSnapshot`, against saved fixtures | accessibility tree, structured extraction, token economics | Golden-JSON tests pass on Greenhouse, Lever, and Ashby fixtures |
| 5 | `plan.py`: snapshot + profile → `FillPlan` via structured outputs | schema design, provenance, confidence, structured outputs | Recorded snapshot yields a valid plan with correct `source` labels |
| 6 | `fill.py`: execute a plan, verify every field | LLM for judgment / code for execution; idempotency | Fixture page ends with the exact expected DOM values |
| 7 | `flow.py` + `review.py`: multi-page loop, guards, approval gate, Submit | agent loops, human-in-the-loop, guardrails | A real application submitted end-to-end after approval |
| 8 | `runlog.py`: JSONL history, screenshots, answer bank learns from edits | feedback loops, cheap memory | Second application to the same ATS asks fewer questions |
| 8.5 | Port `llm.py` + `flow.py` to LangGraph behind a `--engine` flag; keep both | what a framework buys and costs; checkpointing, `interrupt()`, provider abstraction | Same application submits successfully on both engines; tradeoffs written up in `NOTES.md` |
| 9 | Web dashboard (deferred) | — | out of scope for v1 |

**Stage 8.5 is the framework comparison, and it comes last on purpose.**
LangChain's `create_agent` (which calls LangGraph internally since 1.0) would
have made Stage 1 six lines — and hidden exactly the `tool_use` / `tool_result`
protocol Stage 1 exists to teach. Framework APIs churn; the wire format does not.
So the loop gets hand-written first and ported second.

The port is expected to be a real trade, not a victory lap. LangGraph should
delete the loop guards from Section 6 and give the Section 7 approval gate
checkpoint-and-resume for free — pausing for a human is precisely what
`interrupt()` exists for. It should cost easy access to Anthropic prompt
caching (Section 3, Stage 2) and make the stubbed tests in Section 10 harder to
write. Both directions get recorded in `NOTES.md`. Having made the tradeoff
beats having inherited it.

**Stage 3 contains no LLM on purpose.** When something breaks later, you need to
know instantly whether it is a browser problem or a model problem. Systems that
tangle the two are miserable to debug, and being able to say why is itself a
good interview answer.

`NOTES.md` gets a few lines per stage: what surprised you, what broke, what you
changed and why. That file is the interview prep.

## 10. Testing

No test touches a live job posting.

- **Fixtures.** Real application-form HTML saved from Greenhouse, Lever, Ashby,
  and a Workday wizard, committed under `tests/fixtures/`, served to Playwright
  from disk. Real markup, zero network, zero flake.
- **`extract`** — golden JSON per fixture. Snapshot tests catch selector drift.
- **`plan`** — recorded `FormSnapshot` + recorded API response. The LLM call is
  stubbed, so planner logic (confidence floor, source labelling, unresolved
  handling) is deterministic. One opt-in live test behind `--live` for real
  model behavior.
- **`fill`** — fixture page + hand-written plan, assert final DOM values.
  Explicitly covers the revert-after-fill case with a React-controlled input.
- **`flow`** — a two-page fixture wizard; asserts the loop advances, and
  asserts the guards fire on a page that never advances.
- **Safety** — a test asserting that a profile with no `work_authorization`
  produces `unresolved`, never a generated answer. This one is the most
  important test in the suite.

## 11. Cost and Performance

Per form page the planner sends ~6k tokens (snapshot + cached profile + job
context) and receives ~1.5k. Applications average 2-3 pages.

| Model | per page | per application | 100 applications |
|---|---|---|---|
| Opus 5 | ~$0.07 | ~$0.18 | ~$18 |
| Sonnet 5 | ~$0.04 | ~$0.10 | ~$10 |
| Haiku 4.5 | ~$0.014 | ~$0.04 | ~$4 |

An entire job search costs single-digit to low-double-digit dollars. Three
design decisions hold it there: DOM snapshots instead of screenshots (§3.2),
which is roughly a 10x token difference; prompt caching on the profile, which
is identical on every call; and the loop guards in §6, since runaway retries
are how agent costs actually explode.

**A hard spend cap is set in the Anthropic console** (Settings -> Limits)
rather than trusted to estimates. Development runs on Haiku 4.5; only the
Stage 5 planner uses Opus 5.

Wall-clock is dominated by page loads, not inference — expect 30-90 seconds
plus however long the human spends at the review gate.

If cost needs to come down further, the lever is routing simple pages to a
smaller model based on `FormSnapshot` complexity. Not built in v1.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Site blocks automation | Detect, screenshot, hand the browser to the human. No evasion |
| Selector drift breaks extraction | Fixtures pinned in tests; `field_id` indirection keeps CSS out of model output |
| Model invents a fact | Hard-coded never-generate list + confidence floor + review gate |
| Silent fill failure | Read-back verification on every field |
| Infinite wizard loop | Page cap and repeat-URL cap |
| Workday account walls | Detected as `login`; human creates the account once, cookies persist |

## 13. Open Questions

None blocking. Two to revisit after Stage 7, with real usage data:

1. Whether cover-letter drafting deserves its own stage, or whether a template
   in the profile with a few substituted fields is good enough.
2. Whether the answer bank should match questions by embedding similarity
   rather than the v1 approach of normalized-string and keyword matching.
   Defer until the bank has enough entries for matching to actually fail.
