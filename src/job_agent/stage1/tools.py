"""Stage 1 scaffolding: the candidate profile exposed as Claude tools.

This is deliberately the WRONG long-term architecture. A profile is static,
small, and needed on every turn, so it belongs in the system prompt where it
can be prompt-cached. Making it a tool costs a round-trip and lets the model
skip it. Stage 2 deletes this module and proves the point.

Tools are verbs. Context is nouns.
"""

import json

_PROFILE = {
    "name": "Johny Eskandar",
    "school": "Washington University in St. Louis",
    "major": "Business and Computer Science",
}

# PLACEHOLDER — invented content so get_resume_text() has something to return.
# Replace with real experience, or let Stage 2 delete it.
_RESUME_TEXT = """\
Johny Eskandar
Washington University in St. Louis - B.S. Computer Science and Business

EXPERIENCE
Software Engineering Intern, Summer 2025
  Built an internal dashboard in React and FastAPI used by the support team.
  Cut a nightly batch job's runtime from 40 minutes to 6 by batching queries.

PROJECTS
  Job Application Agent - Python agent that reads a job posting, fills the
  application form in a real browser, and pauses for human approval.
"""


class UnknownToolError(Exception):
    """Raised when Claude requests a tool this dispatcher does not implement."""


def get_profile() -> dict[str, str]:
    """Return the candidate's stored profile."""
    return dict(_PROFILE)


def get_resume_text() -> str:
    """Return the plain text of the candidate's resume."""
    return _RESUME_TEXT


TOOLS = [
    {
        "name": "get_profile",
        "description": (
            "Return the job candidate's stored profile as JSON: their name, "
            "the school they attend, and their major. Takes no arguments."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_resume_text",
        "description": (
            "Return the full plain text of the job candidate's resume, "
            "including experience and projects. Takes no arguments."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


def dispatch_tool(name: str, tool_input: dict) -> str:
    """Run the named tool and return its result as a string.

    Tool results are sent back to the API as text, so anything structured is
    serialized here rather than at the call site.
    """
    if name == "get_profile":
        return json.dumps(get_profile())
    if name == "get_resume_text":
        return get_resume_text()
    raise UnknownToolError(f"Claude requested an unknown tool: {name}")
