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

### Measured result

| | Stage 1 (tool) | Stage 2 (context) |
|---|---|---|
| turns to answer | 2 | **1** |
| round-trips | ask -> tool_use -> run -> answer | ask -> answer |

The round-trip is gone. Claude no longer has to request the profile and wait —
it's already in front of it on every call.

### Caching didn't kick in, and the reason is worth knowing

`cache_creation_input_tokens` and `cache_read_input_tokens` were both **0** on
both runs. Not a bug: **the minimum cacheable prefix is ~1024 tokens**, and my
system prompt is currently 1,156 characters (~289 tokens) because
`profile.yaml` still has `experience: []` and `skills: []`.

Under the threshold, caching silently does not happen. No error, no warning
from the API — just zeros. I added an explicit size check to the demo so it
says so out loud instead of looking broken.

TODO: fill in profile.yaml properly, rerun, record the real numbers here.

### The safety instruction actually worked

`profile.yaml` has `status: "VERIFY - ..."` in the work authorization block.
Asked whether the candidate needs sponsorship, the model answered the boolean
fields but **explicitly flagged that the status needs verification** rather than
inventing "US Citizen."

That's the `Never infer work authorization, salary, dates, or GPA` rule in the
system prompt doing its job. Worth remembering that a prompt rule is only as
good as its test — this was the first evidence it holds.

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
