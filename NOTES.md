# Build Notes

How this project works and why it's built the way it is. Written as I go, so I
can explain any layer of it without re-reading the code.

---

## What this is

Give it a URL to a job posting. It opens the posting in a real browser, fills
the application form from a stored profile, drafts answers to questions the
profile doesn't cover, then stops and shows what it's about to submit. On my
approval it clicks Submit.

Full design: `docs/superpowers/specs/2026-09-06-job-application-agent-design.md`

---

## How it works

### Claude never runs anything. It asks.

This is the core idea and everything else follows from it.

Claude is a text model — input goes in, text comes out. It cannot execute a
function, read a file, or make a network call. "Tool use" means Claude can emit
a **structured request** saying *"please run `get_profile` and tell me what it
returned."*

**My code runs everything, every time.** `dispatch_tool()` is the only thing
that actually executes. Claude asks and waits.

It never sees my source either. All it gets is what I put in the `tools` array:

```python
{
  "name": "get_profile",
  "description": "Return the job candidate's stored profile as JSON: ...",
  "input_schema": {"type": "object", "properties": {}, "required": []}
}
```

Name, description, schema. That is the entire basis for its decision — which is
why a vague description produces a tool that gets misused or skipped. **The
description is the interface.**

### The API is stateless

There is no session on Anthropic's side. Nothing is remembered between requests.
Every request resends the **whole** conversation.

That's why the `tool_use_id` matters: it's the only thing linking my answer to
its question. Claude emits `id=toolu_012gr...` with its request; I send back a
`tool_result` carrying that same id. Mismatch is a 400.

### The exchange

```
ME     ->  "What school does the candidate attend?"
           + the tools it may request
           + API key (auth only — nothing to do with tools)

CLAUDE ->  stop_reason: "tool_use"
           "I need get_profile.  id=toolu_012gr..."
           <- has NOT answered. it can't. it's asking.

ME     ->  my code runs get_profile() -> {"school": "Washington University..."}
           resends the ENTIRE conversation, plus:
           tool_result with tool_use_id=toolu_012gr...

CLAUDE ->  stop_reason: "end_turn"
           "The candidate attends Washington University in St. Louis."
```

### The loop

The loop exists because Claude can't do anything without a round-trip. Each turn
it either answers or asks. If it asks, control has to come back to my code.

```python
while stop_reason == "tool_use":
    run whatever it asked for
    send results back
    ask again
```

It stops when `stop_reason` becomes `end_turn` — Claude produced an answer
instead of a request.

`stop_reason` is the whole control flow. Three values I care about:
`tool_use` (asking), `end_turn` (done), and a `max_turns` guard for when it
never terminates — which is how agent loops actually fail in practice, not with
a wrong answer.

### Parallel vs chained

Claude can ask for several tools in **one** turn, or ask for them across
separate turns.

- **Parallel** — the two lookups are independent, so it requests both at once.
  My run did this: 2 turns, both `tool_use` blocks in one assistant turn.
- **Chained** — it needs the first result to form the second call. Would have
  been 3 turns.

My loop doesn't check which. It returns every result from a turn in one user
message and goes again — both cases fall out of the same code.

Two details that aren't obvious:

- **All parallel results go back in ONE user message.** Splitting them across
  messages trains the model to stop making parallel calls.
- **A failing tool still gets a `tool_result`,** with `is_error: True`. Dropping
  it leaves an unanswered `tool_use` and the next request 400s.

### An assistant turn can hold several kinds of block

My live run returned a text block ("I'll retrieve the profile and resume...")
*alongside* two `tool_use` blocks, in the same turn. So the code searches
`content` by block type instead of taking `content[0]`.

---

## What each file does

| File | Job |
|---|---|
| `config.py` | Loads the API key from `.env`; holds model names |
| `stage1/tools.py` | The Python functions, the JSON schemas describing them to Claude, and `dispatch_tool()` — the only thing that executes anything |
| `stage1/loop.py` | The loop: send, check `stop_reason`, run what was asked, send results, repeat |
| `scripts/manual_roundtrip.py` | One round-trip done by hand and printed, to see the protocol |
| `scripts/chained_demo.py` | The same via the loop, with a question needing both tools |
| `tests/` | Prove the loop works against a fake client — no network, no cost |

---

## Decisions, and why

### Tools are verbs. Context is nouns.

`get_profile` as a tool is **deliberately the wrong architecture**, kept for one
stage to prove the protocol.

The profile is static, small, and needed on every turn. Making Claude spend a
round-trip asking for it wastes latency, and it might not ask. Static context
belongs in the **system prompt**, where it also gets prompt-cached.

Tools are for things that are **dynamic or have side effects** — read the page
as it is *right now*, fill a field, upload a file, click Next. Things whose
answer depends on the current state of the world, or that *change* something.

Stage 2 deletes `stage1/tools.py` and proves it: one fewer round-trip, and a
non-zero `usage.cache_read_input_tokens` on the second run. Both versions stay
in git history — the diff is the point.

### Raw Anthropic SDK, not LangChain

LangChain's `create_agent` would make this about six lines — and would hide the
exact `tool_use` / `tool_result` protocol above, which is the thing worth
knowing. Framework APIs churn; the wire format doesn't.

Provider-swapping isn't a reason to adopt one either. `llm.py` will be the only
file importing `anthropic`, and everything downstream depends on `FillPlan`, so
a second provider is one ~40-line class.

Stage 8.5 ports the loop to LangGraph and writes up the comparison. Expecting it
to delete my loop guards and give the human-approval gate checkpoint/resume for
free via `interrupt()`, while costing easy access to prompt caching and making
the tests harder. Making the tradeoff beats inheriting it.

### The client is a parameter, not a global

```python
def run_conversation(client, user_message, ...):
```

If the function built its own `anthropic.Anthropic()`, there'd be no way to test
it without real API calls — slow, costs money, and non-deterministic since
Claude phrases answers differently each run.

Injected, tests pass a fake that records requests and replays canned responses.
Python never checks the type; anything supporting `client.messages.create(...)`
works.

The payoff is testing what the real API can't be made to do on demand: force
two tool calls in one response, force a three-turn chain, force a tool to raise,
force a runaway loop. All eight loop tests run offline.

Same instinct drives Stage 3 having **no LLM in it at all** — pure Playwright.
When something breaks later I need to know instantly whether it's a browser
problem or a model problem.

### Cheap model for mechanics, good model for judgment

Stages 1–6 run on `claude-haiku-4-5` (~$0.002/call) because they prove
mechanics, not judgment. `claude-opus-5` is reserved for the Stage 5 planner,
where deciding what actually goes in a form field needs the better model.

Thinking config is model-dependent, not universal: Haiku 4.5 **rejects**
`thinking={"type": "adaptive"}` with a 400. That's an Opus 4.6+ feature.

Spend cap set in the console rather than trusted to an estimate. Whole job
search should land in single-digit dollars.

### DOM snapshots, not screenshots

A vision loop (screenshot → model picks coordinates → click) is more general and
worse on every axis that matters: a re-render invalidates coordinates, failures
aren't reproducible, and a screenshot costs ~10x the tokens of the structured
JSON describing the same form.

Instead: walk the page, emit compact JSON of every field, let the model decide
*what goes where* and let Playwright decide *how to click*. Screenshots exist
only to show me what's about to be submitted.

### Human approval before Submit, always

An application can't be un-sent. The agent fills everything, then stops at a
review screen showing each value and where it came from — `profile`,
`answer_bank`, `generated`, or `default`. Generated answers are flagged.

Nothing legally significant is ever LLM-generated: work authorization, EEO,
degrees, dates, GPA, salary. Those come from the profile verbatim or the agent
stops and asks.

---

## Stage 2 — the profile stopped being a tool

Deleted `stage1/tools.py` and moved the profile into the system prompt behind a
`cache_control` breakpoint. This is the payoff for building Stage 1 the wrong
way on purpose.

### The round-trip is gone

| | Stage 1 (tool) | Stage 2 (context) |
|---|---|---|
| turns to answer | 2 | **1** |
| shape | ask -> tool_use -> run -> answer | ask -> answer |

Claude no longer has to request the profile and wait. It is already in front of
it on every call.

### Caching: the minimum prefix is model-dependent, and NOT monotonic

This cost me two rounds of confusion, and the lesson is the useful part.

A `cache_control` marker on a prompt below the model's minimum is **silently
ignored**. No error, no warning — just zeros in the usage numbers, which looks
identical to the feature being broken.

| Model | Minimum cacheable prefix |
|---|---|
| Claude Opus 5 | 512 tokens |
| Opus 4.8, Sonnet 5, Sonnet 4.6 | 1024 |
| Opus 4.7 | 2048 |
| **Haiku 4.5** | **4096** |

Newer does not mean smaller. Opus 5 needs 512 while Haiku 4.5 needs 4096 — eight
times more.

Measured on my real profile (~2165 tokens):

```
Haiku 4.5   under the 4096 minimum   creation=0     read=0        no caching
Opus 5 #1   over the 512 minimum     creation=2165  read=0        cache WRITTEN
Opus 5 #2   same prompt              creation=0     read=2165     cache READ
```

`input_tokens` went **1510 -> 24** on the cached runs. The 2165 cached tokens
bill at the cache-read rate instead of full input price.

So: Stage 2 buys a round-trip on every model, but the caching half only pays off
on the planner model. The demo now takes `--planner` and prints the model's
threshold with a verdict, so a zero never looks like a bug again.

Side note: estimating tokens as `len(text) // 4` said 1403 when the real count
was 2165. Fine as a smoke check, useless as a threshold test.

### The safety instruction actually worked

`profile.yaml` has `status: "VERIFY - ..."` in the work authorization block.
Asked whether the candidate needs sponsorship, the model answered the boolean
fields but **explicitly flagged that the status needs verification** rather than
inventing "US Citizen."

That is the `Never infer work authorization, salary, dates, or GPA` rule doing
its job. A prompt rule is only worth what its evidence is; this was the first
evidence it holds.

---

## Stages 4 and 5 — extraction and planning

A live application page now becomes 16-18 fields of JSON, and that JSON plus
the profile becomes a plan saying what goes in each field and where it came
from.

### The extractor: three things real markup taught

**1. Custom ARIA widgets are invisible to a tag query.** `input, textarea,
select` missed every dropdown on the Rippling form, because Rippling renders
them as `<div role="combobox">`. That silently dropped **all five EEO
questions and the attention check** — the agent would have skipped them
without any error. The selector now includes ARIA roles.

**2. A label can live far from its control.** The attention-check combobox is
seven nested divs that each contain only the word "Select". The question is on
the eighth ancestor. A fixed-depth walk finds nothing; the fix is to climb
until the text is meaningfully larger than the control's own.

**3. Surrounding text must not drive classification.** Once the context walk
got wide enough to find the question, it started matching the attention-check
pattern for *every* field on the page — First name, Email, and LinkedIn were
all classified `attention_check`, because the context blob contained the
question. Context is a name fallback only; classification keys off the field's
own resolved label.

That third one is the interesting failure: **fixing the first bug caused the
second.** Widening a search to find something makes it find things you did not
want. Worth remembering as a shape, not just as this instance.

### Snapshot size

3.3KB of JSON for an 18-field form. A screenshot of the same page would be
roughly an order of magnitude more tokens and would carry no field structure.
This is the DOM-over-vision decision paying off in a number.

### The planner: defense in depth, observed

Run against the fixture and against the live page, the same EEO fields were
refused by **different rules each time**:

| Run | What stopped it |
|---|---|
| fixture | sensitive-pattern rule — "EEO/demographic may never be generated" |
| live | confidence floor — model self-reported 0.50, below 0.6 |

Neither run needed both. Having both is why it held twice.

Everything the planner did fill came back `source=profile` — name, email, phone,
location, LinkedIn, website, resume path. Nothing was generated. Everything it
could not source went to the human: the attention check by policy, all five EEO
fields, the SMS-consent radios, and an unlabelled second file upload it
correctly refused to guess the purpose of.

### Safety rules live in code, not in the prompt

`apply_safety_rules()` re-checks everything the prompt asks for: the confidence
floor, the never-generate list, hallucinated `field_id`s, attention checks, and
unconfirmable resume-parser prefills. Five of the nine planner tests target
that function rather than the model.

**A prompt rule is a request. Code is the guarantee.** The model is well-behaved
here, but "the model behaved" is not a property you can test or rely on.

### Open

- The live page returned 16 fields, the fixture 18 — the fixture has two
  SMS-consent radios the live page did not show. Fixture drift, or a variant.
  Recapture and compare before trusting either.
- This form has **no work-authorization question at all**, so the `en-CA`
  locale concern is moot for this posting. Still open for others.
### What Rippling's resume parser actually gets wrong

Uploaded the real resume to the live form and re-extracted. Never submitted.

| Field | Parser produced | Profile says | |
|---|---|---|---|
| First name | Johny | Johny | match |
| Last name | Eskandar | Eskandar | match |
| Email | alex.kim@example.com | alex.kim@example.com | match |
| Location | St. Louis, MO | St. Louis, MO | match |
| Phone | `555-010-0100` | `(555) 010-0100` | reformatted |
| LinkedIn | `https://www.linkedin.com/in/...` | `https://linkedin.com/in/...` | added www. |
| Website | `https://www.johnyeskandar.com/` | `https://johnyeskandar.com` | added www. + slash |

Three of seven differ, and all three are **normalizations rather than factual
errors**. Nothing false, just not byte-exact.

**The caveat that matters:** this form only collects contact information. No
employer, no titles, no dates, no education. That is the easy half of resume
parsing. The horror stories about parsers are about work history and dates,
which this form never asks for — so this test says nothing about how Rippling
handles them.

The overwrite-everything rule stands anyway. You cannot reliably tell a
cosmetic normalization from a substantive error without already knowing which
is which, and being wrong about that is exactly the failure being avoided.

---

## Stages 6 and 7 — filling the form and the approval gate

The agent can now fill a real application and stop for approval. Ran it against
the live Edgehog form: 9 fields filled from the profile, 7 routed to me,
nothing submitted.

### Read-back verification earned its keep on the first live run

Two failures surfaced immediately that no amount of "it looked fine" would have
caught:

**A phone input mask.** Wrote `(555) 010-0100`, the field held `555-010-0100`.
The form strips punctuation on input. The *content* survived — this is the
site's formatting prerogative, not a failure. Flagging it FAILED is noise, and
noise is how you learn to ignore real failures.

Added a `normalized` outcome: if the values differ only in punctuation and
whitespace, the content survived. A test asserts that truncation (`Johnathan` ->
`Joh`) is still a `mismatch`, because truncation changes alphanumerics and so
cannot hide as normalization.

**Two kinds of combobox.** The phone country-code selector errored. It turned
out to be an `<input role="combobox">`, while the ones I had handled were
`<div role="combobox">`. They store their value in different places:

| shape | value lives in |
|---|---|
| `<div role=combobox>` | inner text |
| `<input role=combobox>` | `.value`; inner text is `""` |

Reading the wrong one returns `""`, which looks exactly like an empty field. So
the code decided the already-correct `+1 US` needed changing, opened a
searchable dropdown whose options only exist after you type, and timed out.

Two fixes: read the value according to the element's shape, and **no-op when
the combobox already holds the wanted value.** The second is the more general
lesson — the safest way to handle a widget is often not to touch it.

### The load-bearing test

```python
def test_the_flow_never_submits_without_approval(ctx):
    submitted = []
    run_application(page, planner=..., decide=lambda *_: "abandon",
                    submit=lambda *_: submitted.append(True))
    assert submitted == []
```

`submit` is **injected, not imported**, purely so this test can exist. A second
test runs every non-approval answer — `""`, `None`, `"yes"`, `"SUBMIT "` with a
trailing space — and asserts each abandons. Production has exactly one
`submit(page)` call site, inside the approval branch.

### --dry-run

`scripts/apply.py --dry-run` fills everything, prints the review screen, and
always abandons. Full pipeline, zero risk, no keypress. It is how the two bugs
above were found, and it is the right way to try a new posting.

### Still open

- The second file upload has no label saying what it is (cover letter?
  transcript?). The planner correctly refuses to guess.
- The live page shows 16 fields, the committed fixture 18. Unresolved.

---

## The planner was choosing blind

Biggest bug of the whole build, and it hid for two stages.

`FormField.options` was `[]` for **every** custom combobox. The extractor read
options with `element.locator("option")`, which finds native `<option>`
children — and a `<div role=combobox>` has none. Its options are rendered into
a portal that does not exist in the DOM until the control is opened.

So the planner was picking values for six dropdowns without ever knowing what
they offered. It looked like it was working, because it guessed plausible
strings. The failures it produced were misleading:

- **Disability Status "failed"** — the profile says "No, I do not have a
  disability and have not had one in the past" (the federal wording); the form
  offers "No, I don't have a disability". No exact match, so the click timed out.
- **Race went unresolved** — the planner could not evaluate "Middle Eastern if
  offered, otherwise Two or More Races" against an empty options list.

Neither failure pointed at the real cause. Both looked like wording problems.

**Fix:** `probe_combobox_options()` opens each combobox, reads the visible
`[role=option]` items, and presses Escape. The flow probes before planning.

| | before | after |
|---|---|---|
| fields filled | 9 | **14** |
| left for the human | 7 | **2** |
| failures | 1 | **0** |

With real options in hand, the preference-ordered race rule resolved on its
first choice — the form does offer "Middle Eastern or North African" — and
Disability matched the form's own shorter wording.

**The lesson:** an empty list is not the same as no answer, and a planner given
`options=[]` will confidently invent plausible values rather than report that it
cannot see. Silent absence again — the same shape as the EEO fields missing from
the tag-based extractor in Stage 4. Twice now, the expensive bug was something
that was not there rather than something that was wrong.

---

## Decision change: the agent cannot submit

Originally designed as "fill everything, pause for approval, then submit."
Changed to **fill-only** after the first real run.

What prompted it: I pressed `s`, and the submit crashed — the code looked for a
button named "Submit" while Rippling calls its button "Apply". The snapshot had
recorded `submit_buttons: ['Apply']` correctly; apply.py ignored it and used a
hardcoded guess. Nothing was sent, but the crash closed the browser and threw
away the attention-check answer I had typed by hand.

Two lessons, and only one of them is about the bug.

**The small one:** never hardcode what the snapshot already knows. The
extractor had the right answer and the caller substituted a guess.

**The real one:** the submit click was the least valuable part of the system
and carried all of the risk. The agent typing 14 fields correctly is the whole
benefit. Clicking one button afterwards saves a second and creates the only
irreversible action in the design.

So the capability is **removed, not defaulted off**:

- `run_application` has no `submit` parameter — a test asserts that by
  inspecting its signature
- no module targets a submit or apply control — a test greps the package and
  fails if one appears
- `VALID_DECISIONS` in review.py is `{}` — a test asserts it is empty
- the review screen is a handoff summary, not a prompt

Removing a capability is stronger than disabling it. A default can be flipped
by a flag, a config, or a future edit that seemed reasonable at the time. There
is nothing here to flip.

The browser stays open when the run ends so nothing typed by hand is lost.

---

## Retrospective — Stages 4 and 5

Hypotheses under test:

- **Stage 4:** a page can be reduced to compact structured JSON via the
  accessibility tree — cheaper and more reliable than screenshots.
- **Stage 5:** given that JSON plus a profile, a model can decide what goes in
  each field, with safety enforced in code rather than requested in a prompt.

### What worked

**The size claim, concretely.** An 18-field application form becomes **3.3KB of
JSON**. A screenshot would be roughly an order of magnitude more tokens and
carry no field structure. The DOM-over-vision decision stopped being an
argument and became a number.

**Role-based selectors survived the hashed names.** Rippling regenerates
`name="4Za8M3kpmM"` per render; every label came through anyway, because
nothing ever touched `name` or `id`.

**`aria-required` answered Stage 3's open question.** First name `True`,
LinkedIn `False` — available, just not from the HTML attribute.

**The planner generated nothing.** Every filled value on both runs came back
`source=profile`. Nothing invented.

**Defense in depth got observed, not assumed.** The EEO fields were refused by
the sensitive-pattern rule on one run and by the confidence floor on the other.
Neither run needed both. That is the argument for redundant guards made by
evidence rather than principle.

### What went wrong

**My first extractor silently skipped all five EEO fields and the attention
check.** It queried `input, textarea, select`; Rippling renders dropdowns as
`<div role="combobox">`. No error, no warning — those fields simply did not
exist in the snapshot.

This is the worst failure shape in the project: the agent would have submitted
an application having never seen the legally-relevant questions, and nothing
would have looked broken.

**Fixing that caused a second bug.** Once the context walk got wide enough to
find the attention question, it matched that pattern for *every* field — First
name, Email, and LinkedIn all became `attention_check`, because the context
blob contained the question. **Widening a search to find something makes it
find things you did not want.** A shape, not just an instance.

**I guessed the traversal depth and was wrong.** Wrote a 3-hop ancestor walk;
the question is on the **eighth** ancestor — seven nested divs each containing
only the word "Select". A magic number where a condition belonged.

**The test structure was wrong.** A module-scoped browser fixture plus per-test
contexts blew up: Playwright's sync API refuses to start a second
`sync_playwright()` while one is live.

**The first fixture I committed was broken.** 19 `<script>` tags, so it
re-hydrated and wiped itself on reload — its `<form>` locator timed out. It was
committed with a confident README about what it proved.

### What we found that we were not looking for

**Tag-based extraction is not suboptimal — it is structurally insufficient.**
Any form built with a component library renders its selects as divs. Not a
Rippling quirk; most of the modern web.

**The resume parser normalizes rather than corrupts**, at least here. Three of
seven fields differ; none are false.

**But that finding is narrow.** This form collects only contact information —
no employer, titles, dates, or education. That is the easy half of resume
parsing. The horror stories are about work history, which this test never
exercised. We measured the shallow end.

### What it changes

| Finding | Consequence |
|---|---|
| Custom ARIA widgets invisible to tag queries | Extraction must be role-based, permanently |
| Context blob caused over-classification | Classification keys off the field's own label; context is a name fallback only |
| Ancestor depth is unpredictable | Walk until a condition holds, never a fixed depth |
| SPA fixtures re-hydrate | Strip scripts, and test that they are stripped |
| Parser findings are contact-only | Do not generalize; work-history parsing is still untested |

**Honest headline:** the two most valuable moments here were both bugs I
introduced, and both were caught by tests asserting a **specific named thing
must be present** — `"attention_check" in kinds`, `"Gender" in names` — rather
than by reading output and deciding it looked fine.

A test asserting "some fields were found" would have passed while five EEO
questions quietly went missing. **Specific assertions catch silent omissions;
generic ones do not.**

---

## Retrospective — Stages 2 and 3

Each stage was a hypothesis, not just a build.

- **Stage 2:** static context behind a tool is wasteful; move it to the system
  prompt and you save a round-trip and get caching.
- **Stage 3:** a persistent browser profile keeps logins alive, and browser code
  can be tested offline.

### What worked

**The round-trip claim, cleanly.** 2 turns -> 1. Measurable, not argued. That is
the entire payoff for building Stage 1 the wrong way on purpose.

**Offline browser testing.** Five tests driving real Chromium against a local
HTML file in 4.4 seconds. No network, no dependency on a live posting staying
up.

**The safety instruction, with evidence.** `work_authorization.status` says
`"VERIFY - ..."`. Asked about sponsorship, the model answered the booleans and
explicitly flagged the status as unverified rather than inventing "US Citizen."
The never-infer rule held under a real test instead of being a comment.

**Strict validation.** `extra="forbid"` turns a typo in profile.yaml into a load
error instead of a blank field on a submitted application.

### What didn't

**I was wrong about caching.** I assumed a universal ~1024-token minimum. It is
model-dependent and **not monotonic**: Opus 5 needs 512, Haiku 4.5 needs 4096 —
eight times more, on a newer model. Below the threshold `cache_control` is
silently ignored, and zeros look identical to a broken feature. Chased it twice
before checking the docs.

**Which exposed a tension in an earlier decision.** Haiku was chosen for Stages
1-6 to save money, but Haiku cannot cache a profile of realistic size. So Stage
2's thesis splits in half:

- round-trip saving: works on every model
- caching: only pays off on the planner model

Running the numbers, Haiku-uncached still beats Opus-cached — output tokens
dominate and caching only discounts input. On the Stage 5 planner (~6k in,
~1.5k out) caching saves roughly a third. Real, worth having, smaller than I
first implied.

**Login persistence is unproven.** Scripts exist; the hypothesis is untested
because logging in needs hands.

**profile.yaml cannot be finished from a resume.** It gave experience,
education, projects, skills. It says nothing about work authorization, mailing
address, or salary expectations — and work authorization is exactly where a
wrong guess becomes a misrepresentation on a real application.

### What we found that we weren't looking for

**Rippling's field names are random per-render hashes** (`4Za8M3kpmM`,
`n6i9CInKB6_`). Selecting by `name` or `id` is impossible on that ATS.

This is the most valuable thing in these two stages. The spec *assumed* the
accessibility tree beat CSS selectors on debuggability grounds. It turns out to
be the only thing that works at all on my actual target. An assumption became a
constraint — found by looking at a real form for ten minutes instead of by
having Stage 4 fail mysteriously.

**Rippling never sets the HTML `required` attribute**; it validates in
JavaScript. So `FormField.required` cannot be read from the DOM. An open design
question for Stage 4, known before writing the extractor rather than after.

**Test doubles have maintenance cost.** Adding `usage` to the real response
shape broke every loop test until `FakeResponse` grew the same field. That is
the tax on fakes: they must track what they stand in for, or they start passing
tests that would fail in production.

### What it changes

| Finding | Consequence |
|---|---|
| Haiku cannot cache realistic prompts | Caching is a Stage 5 planner optimization, not a general one |
| Rippling hashes field names | Accessibility tree is mandatory, not preferred |
| No `required` attribute in the DOM | Stage 4 needs another requiredness signal |
| Work auth unknowable from a resume | The never-generate list is not theoretical; the data genuinely is not there |

**Honest headline:** Stage 2's thesis was half right, and finding out which half
took a wrong assumption, two confused runs, and a docs check. Stage 3's real
value was not the code — it was ten minutes looking at a live Rippling form,
which turned one spec assumption into a confirmed constraint and one into an
open question.

---

## What's next

**Stage 2** — profile out of a tool and into a cached system prompt.
**Stage 3** — Playwright with no LLM: persistent browser profile so logins
survive between runs.
**Stages 4–7** — page → `FormSnapshot` → `FillPlan` → execute → review gate.

---

## Gotchas worth remembering

- `AttributeError`/`TypeError` = my code is wrong, nothing left the machine.
  `BadRequestError` (400) = my code ran fine and the *server* rejected the
  protocol. The traceback tells you which in two seconds.
- Assignment in Python never copies — it binds another name to the same object.
  Anything recording mutable state for later inspection has to snapshot it.
- Environment changes only affect shells started *after* the change. `source`
  in a throwaway shell does nothing.
- Bare `pip` on this machine points at a stale 3.9 install. Use `python -m pip`,
  or work inside the activated venv.
- `.gitignore` before the first commit, not after. A secret committed once stays
  in history even after you delete the file.

<!-- TODO(me): rewrite the "how it works" section in my own words once I'm sure
     I could explain it cold. That's the section an interviewer would poke at. -->
