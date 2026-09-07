# Job Application Agent

Give it a link to a job posting. It opens the posting in a real browser, reads
the application form, fills every field it can source from your profile, and
tells you exactly what it refused to answer and why.

**It cannot submit.** That is deliberate — see [Why it cannot submit](#why-it-cannot-submit).

```
  Apply - Graduate Quantitative Trader   (rippling)
  14 fields filled, 2 left for you

  profile     First name                First name           Alex
  profile     Email                     alex.kim@example.com
  profile     Phone number              (555) 010-0100   (site reformatted to '555-010-0100')
  profile     Please identify your race Middle Eastern or North African
  ...

  NEEDS YOU:
    Drop or select (.doc / .docx / .pdf)   second upload, purpose unlabelled
    Select the second word of this sen…    attention check — a human answers this

  The browser is open and it is yours now.
  Finish the fields above, check the rest, and submit it yourself.
  This agent cannot submit — by design.
```

---

## How it works

Claude is a text model. It cannot click, type, or read a page. What it *can* do
is emit a structured request — and everything here is built around that one
fact.

```
  browser     persistent Chromium; a login survives between runs
     ↓
  extract     page → FormSnapshot: label, role, requiredness, options
     ↓         (via the accessibility tree, never CSS selectors)
  plan        snapshot + profile → FillPlan     ← the only LLM step
     ↓         each value tagged with where it came from
  fill        execute the plan, read every value back to confirm it stuck
     ↓
  you         finish what it refused to answer, and submit it yourself
```

The model decides **what goes where**. Deterministic code decides **how to
click**. That split is why the browser layer and the planning layer can each be
tested without the other.

### Why the accessibility tree, not CSS selectors

Not a style preference — a measured constraint. Rippling regenerates every
field's `name` attribute per render:

```html
<input name="4Za8M3kpmM" ...>   <!-- "First name", next render: n6i9CInKB6_ -->
```

Selecting by `name` or `id` is impossible. The accessible name — what a screen
reader announces — is the only stable handle, and it is also exactly what a
human sees. The same page renders its dropdowns as `<div role="combobox">`, so
a tag-based query (`input, textarea, select`) misses them entirely — including
every EEO question.

### Why a DOM snapshot, not screenshots

An 18-field application form becomes **3.3 KB of JSON**. A screenshot of the
same page costs roughly an order of magnitude more tokens and carries no field
structure. It is also reproducible: a re-render invalidates pixel coordinates,
but not a label.

### Why every write is read back

A `fill()` that silently reverts is routine on React-controlled inputs. Without
verification it looks identical to success, and you submit a blank field with
no error anywhere. Every value is read back after writing:

| outcome | meaning |
|---|---|
| `verified` | the value landed exactly |
| `normalized` | the form reformatted it but kept the content — e.g. an input mask turning `(555) 010-0100` into `555-010-0100` |
| `mismatch` | the content actually changed. A real failure |
| `error` | the write threw |
| `skipped` | refused on purpose, e.g. an attention check |

---

## Safety

The agent will not invent a fact about you. Enforced in code, not just
requested in a prompt:

- **Never generated:** work authorization, sponsorship, visa, GPA, degrees,
  dates, salary, EEO/demographics. Those come from your profile verbatim, or
  the field goes to you.
- **Confidence floor.** Anything the model reports below 0.6 confidence is
  routed to you regardless of what it produced.
- **Attention checks are never answered.** Questions like *"select the second
  word of this sentence"* exist to verify a human read the form. A model
  answers them trivially, which defeats the purpose. They always go to you.
- **A prefilled field is not a correct field.** Sites parse your résumé to
  autofill, and parsers get things wrong. Values you can confirm from the
  profile get overwritten; values you cannot are flagged, never endorsed.

`apply_safety_rules()` re-checks all of this after the model responds. A prompt
rule is a request; code is the guarantee.

### Why it cannot submit

Originally this stopped at a review screen and submitted on approval. That was
removed after the first real run.

The submit click is the least valuable part of the system and carries all of
the irreversible risk. Typing 14 fields correctly is the entire benefit;
clicking a button afterwards saves a second and creates the one action that
cannot be undone.

The capability is **removed, not disabled** — a default can be flipped by a
flag, a config, or a future edit that seemed reasonable at the time. Four tests
enforce it: `run_application` has no submit parameter, no module contains a
locator targeting a submit control, the decision table is empty, and the
summary tells you that you submit.

---

## Setup

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/JohnyEskandar/job-application-agent.git
cd job-application-agent

uv sync
source .venv/bin/activate
playwright install chromium

cp .env.example .env          # add your key from console.anthropic.com
cp profile.example.yaml profile.yaml   # fill in your real details
```

Put your résumé in `docs/` and point `profile.yaml` at it. Name it the way
you want a recruiter to see it — `docs/Lastname, Firstname Resume.pdf` rather
than `resume.pdf`, since that filename travels with the upload. Both `.env` and `profile.yaml` are
gitignored, along with `runs/` (screenshots) and `browser-profile/` (cookies).

**Set a spend cap** at console.anthropic.com → Settings → Limits. A whole job
search costs single-digit dollars; a cap makes overspending impossible rather
than merely unlikely.

## Usage

```bash
python scripts/apply.py "<application url>"              # fill it, then hand over
python scripts/apply.py "<url>" --headless               # no window
```

Other tools:

```bash
python scripts/capture_fixture.py <url> tests/fixtures/x.html   # save a form for testing
python scripts/resume_parse_check.py <url>                      # what the site's parser gets wrong
python scripts/login_once.py <url>                              # log in once; the session persists
```

## Tests

```bash
pytest          # 91 tests
```

None of them make an API call or load a live page. Browser tests run against
committed HTML fixtures, and the planner is tested against a stub. Captured
fixtures have their `<script>` tags stripped — otherwise the framework
re-hydrates on `file://` load and wipes the DOM you captured.

---

## Project layout

```
src/job_agent/
  config.py     API key, model names
  models.py     every shared type — Profile, FormSnapshot, FillPlan, FillReport
  profile.py    load and strictly validate profile.yaml
  prompt.py     render the profile into a cache-marked system prompt
  browser.py    persistent Chromium; no LLM in this file, deliberately
  extract.py    page → FormSnapshot via the accessibility tree
  plan.py       snapshot + profile → FillPlan, plus the safety rules
  fill.py       execute a plan, verify every write
  flow.py       the page loop and its guards
  review.py     the handoff summary
  fixtures.py   reload-safe fixture capture
```

`docs/superpowers/` holds the design spec and the staged implementation plans.
[`NOTES.md`](NOTES.md) is a running log of what was built, what broke, and what
each failure taught — including the three separate bugs that were all the same
shape: an empty value that looked like an answer.

## Status

Tested against four real ATSs:

| ATS | State |
|---|---|
| Rippling | Works end to end — 14 fields filled, 0 failures |
| Greenhouse | Most fields fill; a file input and a few widget variants still fail |
| Workday | Fills a five-block experience page and advances a seven-step form |
| Eightfold | Redirects to Workday before its own flow matters |

Extraction and planning generalized across all four with no per-ATS code.
Writing needed per-widget work every time — see the retrospective in
[`NOTES.md`](NOTES.md).

Not yet handled: multi-selects (`Field of Study`, skills pickers), deleting
spurious blocks a resume parser created, and questions whose text is rendered
away from their control so the accessibility tree cannot reach it.

**Skip a form's "autofill from resume" step if it offers one.** Workday's
produced a job title of "Mastercard", a company of "LEADERSHIP & INVOLVEMENT…",
and a whole resume section pasted into one role's description. Filling from a
clean profile beats correcting a parse.

## Built as a learning project

The agent loop is hand-written rather than taken from a framework —
`tool_use` / `tool_result` / `stop_reason` by hand, on purpose, so the protocol
is understood rather than abstracted. LangGraph is a planned comparison, not a
starting point.
