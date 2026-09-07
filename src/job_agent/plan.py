"""Turn a FormSnapshot plus a Profile into a FillPlan.

The model decides what goes in each field. It never touches the page — this
module returns a plan, and fill.py executes it. That split is what makes the
planner testable with a stub and the executor testable with a fixture.
"""

import re

from job_agent.config import MAX_TOKENS, PLANNER_MODEL
from job_agent.models import FillPlan, FormSnapshot, PlannedField, Profile, Unresolved
from job_agent.prompt import cached_system, profile_system_prompt

# Below this, a value is treated as a guess and routed to the human.
CONFIDENCE_FLOOR = 0.6

# Answers that must come from the profile verbatim or not at all. A wrong
# value here is a misrepresentation on a real application, not a bug.
SENSITIVE_PATTERNS = [
    (re.compile(r"authoriz|sponsor|visa|work permit|eligible to work", re.I), "work authorization"),
    (re.compile(r"\bgpa\b|grade point", re.I), "GPA"),
    (re.compile(r"salary|compensation|pay expectation", re.I), "salary"),
    (re.compile(r"gender|race|ethnic|veteran|disab|hispanic|latino|sexual orientation", re.I), "EEO/demographic"),
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
parsed the candidate's resume to prefill the form. Resume parsers are
unreliable. Treat `current_value` as a third party's guess, never as correct:
  - If the candidate facts cover that field, plan a value anyway. Yours
    overwrites theirs.
  - If the facts do NOT cover it and `current_value` is non-empty, mark it
    unresolved, saying it was prefilled and cannot be verified.

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
            unresolved.append(Unresolved(
                field_id=planned.field_id,
                reason="field_id is not in the snapshot",
            ))
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
                reason="prefilled by the site's resume parser and not confirmable "
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
