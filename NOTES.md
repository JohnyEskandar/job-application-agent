# Build Notes

One entry per stage: what surprised me, what broke, what I changed and why.
Written while it's fresh, mostly so I can talk about this properly later.

---

## Stage 0 — setup

### The Python on this machine was a mess

`python` resolved to anaconda's 3.11.5 while `python3` resolved to the system
3.9.6. Two different interpreters in the same shell, which means "I installed
that package" and "Python can't find that package" could both be true at once.

Fixed by installing 3.14.7 through `uv` with `--default`, which drops `python`,
`python3`, and `python3.14` shims into `~/.local/bin`. That directory was
already first on my PATH, so nothing in my shell config had to change and conda
was left alone — my `cse217a` and `otter-py311` course envs still work via
`conda activate`.

Deliberately did **not** remove `~/Library/Python/3.9/bin` from PATH even though
it's stale, because it holds `jupyter`, `ipython`, and `otter`, which I use for
class.

### The pip landmine

Bare `pip` / `pip3` still resolve to that stale 3.9 install. Installing with it
puts packages somewhere 3.14 can't see, which produces the most confusing error
in Python: the package is definitely installed and definitely not importable.

Rule I'm adopting: **outside a venv, always `python -m pip`.** It follows
whichever `python` just ran, so it can't disagree with the interpreter.

### Why a venv at all

`.venv` holds this project's own interpreter and its 27 packages. Two projects
needing different versions of the same library don't fight. `uv` also installed
the project itself into the venv in **editable mode** — that's why
`from job_agent.config import ...` resolves from anywhere in the repo without
touching `sys.path` or `PYTHONPATH`.

`pyproject.toml` declares intent (`anthropic>=1.4.0`); `uv.lock` records the
exact resolved versions. The pair is what makes this reproducible on someone
else's machine.

<!-- TODO(me): anything else about setup that tripped me up? -->

---

## Stage 0 — three bugs I caused, and what each taught me

### 1. Markdown fences in a TOML file

Pasted a code block out of the plan into `pyproject.toml` and brought the
` ```toml ` and closing ` ``` ` with it. TOML failed to parse at that exact line.

The fences are *document* syntax telling the renderer how to highlight the
block — they are never part of the content. Obvious in hindsight; would have
been much more confusing in a `.py` file, where it shows up as
`SyntaxError` on line 1.

### 2. `.env` needs `NAME=value`

I wrote the bare key into `.env` with no variable name. `load_dotenv()` read the
file, found no assignment, and set nothing — so `require_api_key()` would have
raised "not set" while the key sat right there in the file.

A `.env` file is a list of assignments, like a shell script. A line with only a
value assigns it to nothing.

### 3. The two different `ModuleNotFoundError`s

Ran `pytest` and got `No module named 'job_agent'`. Ran `.venv/bin/pytest` and
got `No module named 'job_agent.config'`. **Different errors, different
meanings:**

- `'job_agent'` — the package isn't found at all → wrong interpreter. I was on
  anaconda's 3.11 with pytest 7.4.0, which has never heard of this project.
- `'job_agent.config'` — package found, submodule missing → correct interpreter,
  and the actual thing the test was waiting for me to write.

The giveaway was in pytest's first line the whole time:
`platform darwin -- Python 3.11.5, pytest-7.4.0`. **Read the header before the
traceback.** "Am I even on the right interpreter" is the first question when a
test suite behaves inexplicably, and pytest answers it for free on every run.

Root cause: `source .venv/bin/activate` only modifies the shell it runs in. If
each command spawns a fresh shell, the activation dies with it. Real Terminal
session → activate once, works all session.

<!-- TODO(me): which of these actually cost me the most time? worth ranking. -->

---

## Stage 0 — decisions I made and why

### Anthropic SDK, not LangChain

LangChain's `create_agent` would make Stage 1 about six lines — and would hide
the exact `tool_use` / `tool_result` protocol Stage 1 exists to teach. Framework
APIs churn; the wire format doesn't.

Provider-swapping isn't a reason to adopt one either: `llm.py` is the only file
that imports `anthropic`, and everything downstream depends on `FillPlan`, so a
second provider is one ~40-line class.

Planning to port to LangGraph in Stage 8.5 and write up the comparison. Making
the tradeoff beats inheriting it.

### Haiku for the learning stages, Opus for the planner

Stages 1–6 prove mechanics, not judgment, so they run on `claude-haiku-4-5` at
roughly $0.002/call. `claude-opus-5` is reserved for the Stage 5 field planner,
where deciding what actually goes in a form field needs the better model.

Set a hard spend cap in the console rather than trusting an estimate.

Caught a real bug making this change: the Stage 1 code passed
`thinking={"type": "adaptive"}` on every call, which **Haiku 4.5 rejects with a
400** — adaptive thinking is an Opus 4.6+ feature. Thinking config is
model-dependent, not universal. Would have hit this on my first API call.

### `gh` over SSH keys

Used GitHub CLI with HTTPS auth instead of registering an SSH key. Token lives
in the macOS keychain. My existing SSH key is from a class and also authorizes a
WashU shell server and two EC2 boxes — keeping GitHub off it means those
concerns stay separate.

<!-- TODO(me): do I actually agree with the Haiku/Opus split, or would I just
     use one model? worth having an opinion for interviews. -->

---

## Stage 0 — on secrets

`.gitignore` was written and committed **before** the first commit, not after.
That ordering is the whole point: a secret committed once stays in git history
even after you delete the file, and cleaning it means rewriting history or
rotating the key.

Detail worth remembering: `^\.env$` is anchored. Unanchored `.env` would also
match `.env.example`, which *should* be committed so anyone cloning knows which
variables to set.

I did paste an API key into a chat transcript at one point. Nothing bad came of
it and spend was capped, but the lesson stands: **you can't un-leak a secret,
you can only make the leaked copy worthless.** Rotation invalidates every copy
at once; chasing down copies is a losing game.

<!-- TODO(me): rewrite this section in my own words — it's the one an
     interviewer is most likely to poke at. -->

---

## Stage 1 — the tool protocol

<!-- Fill in after Task 3 and Task 5. Questions to answer:
     - What does stop_reason tell you? Which values did I see?
     - Why must the assistant's content go back verbatim, not summarized?
     - Why do parallel tool results go in a single user message?
     - Did my run chain or parallelize, and how could I tell?
     - What did the deliberately-broken tool_use_id error say?
-->
