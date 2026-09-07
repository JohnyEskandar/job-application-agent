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
