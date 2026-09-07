"""Tool dispatch.

Stage 1 dispatched profile lookups. Those are gone — static context belongs in
the system prompt, not behind a round-trip. The real tools arrive in Stage 6 as
browser actions: read_page, fill_field, click, upload_file.

Tools are verbs. Context is nouns.
"""


class UnknownToolError(Exception):
    """Raised when Claude requests a tool this dispatcher does not implement."""


def dispatch_tool(name: str, tool_input: dict) -> str:
    raise UnknownToolError(f"Claude requested an unknown tool: {name}")
