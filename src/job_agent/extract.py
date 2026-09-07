"""Turn a live page into a compact FormSnapshot.

No LLM here. This module only reads the DOM and the accessibility tree.

Why the accessibility tree rather than CSS selectors: Rippling regenerates
every field's name/id per render (4Za8M3kpmM, n6i9CInKB6_), so those are
useless as handles. The accessible name — "First name", "LinkedIn Link" — is
the only stable identifier, and it is also exactly what a human sees.
"""

import re
from urllib.parse import urlparse

from job_agent.models import FormField, FormSnapshot

ATS_HOSTS = {
    "ats.rippling.com": "rippling",
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby",
    "myworkdayjobs.com": "workday",
}

# Questions designed to verify a human read the page. Never auto-answered.
ATTENTION_PATTERNS = [
    re.compile(r"\b(select|type|enter|write)\s+the\s+(first|second|third|fourth|last)\s+word\b", re.I),
    re.compile(r"\bto show (that )?you (have )?read\b", re.I),
    re.compile(r"\bwhat is \d+\s*[+\-x*]\s*\d+", re.I),
    re.compile(r"\bprove you (are|'re) (a )?human\b", re.I),
]

TYPE_KINDS = {"file", "email", "tel", "number", "url", "date", "checkbox", "radio"}

# Placeholder text that custom widgets expose instead of a real label.
GENERIC_NAMES = re.compile(r"^(select\.{0,3}|choose\.{0,3}|please select|-+)$", re.I)


def detect_ats(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    for known, name in ATS_HOSTS.items():
        if host == known or host.endswith("." + known) or known in host:
            return name
    return None


def _looks_like_attention_check(text: str) -> bool:
    return any(p.search(text or "") for p in ATTENTION_PATTERNS)


def _accessible_name(element) -> str:
    """The name a screen reader announces, however the page provides it."""
    return (
        element.evaluate(
            """e => {
                const byId = id => id && document.getElementById(id);
                const lb = e.getAttribute('aria-labelledby');
                if (lb) {
                    const parts = lb.split(/\\s+/).map(byId).filter(Boolean);
                    if (parts.length) return parts.map(n => n.innerText).join(' ').trim();
                }
                if (e.getAttribute('aria-label')) return e.getAttribute('aria-label').trim();
                if (e.labels && e.labels.length) return e.labels[0].innerText.trim();
                if (e.placeholder) return e.placeholder.trim();
                return '';
            }"""
        )
        or ""
    ).strip()


def _nearby_text(element) -> str:
    """Text of the nearest ancestor that says more than the control itself.

    Custom widgets bury their question surprisingly far up. On Rippling the
    attention-check combobox renders as seven nested divs that all contain
    only the word "Select"; the question lives on the eighth ancestor. So walk
    until the text is meaningfully larger than the control's own text rather
    than stopping at a fixed depth.
    """
    return (
        element.evaluate(
            """e => {
                const clean = n => (n.innerText || '').replace(/\\s+/g, ' ').trim();
                const own = clean(e);
                let n = e.parentElement, hops = 0;
                while (n && hops < 10) {
                    const t = clean(n);
                    if (t.length > own.length + 15 && t.length > 25) return t.slice(0, 400);
                    n = n.parentElement; hops++;
                }
                return '';
            }"""
        )
        or ""
    ).strip()


def _is_required(element, name: str) -> bool:
    # aria-required first: Rippling never sets the HTML required attribute
    if (element.get_attribute("aria-required") or "").lower() == "true":
        return True
    if element.get_attribute("required") is not None:
        return True
    # a trailing asterisk on the rendered label is the visual convention
    return name.rstrip().endswith("*")


def _kind_for(element, tag: str, role: str, name: str) -> str:
    # Only the field's OWN resolved label counts. Surrounding text is a name
    # fallback, never classification evidence — a wide context walk picks up
    # the attention-check question and would mark every field on the page.
    if _looks_like_attention_check(name):
        return "attention_check"
    input_type = (element.get_attribute("type") or "").lower()
    if input_type in TYPE_KINDS:
        return input_type
    if tag == "textarea":
        return "textarea"
    if tag == "select":
        return "select"
    if role == "combobox":
        return "combobox"
    return "text"


# Native form tags PLUS custom ARIA widgets. Rippling renders its dropdowns
# as <div role="combobox">, which a tag-only query misses entirely — including
# the attention-check question. Querying by role is not a stylistic choice.
CONTROL_SELECTOR = (
    "input, textarea, select, "
    "[role=combobox], [role=textbox], [role=listbox], [role=spinbutton]"
)


def extract_snapshot(page) -> FormSnapshot:
    fields: list[FormField] = []
    index = 0

    for element in page.locator(CONTROL_SELECTOR).all():
        input_type = (element.get_attribute("type") or "").lower()
        if input_type == "hidden":
            continue
        # file inputs are routinely hidden behind a styled button — keep them
        if input_type != "file" and not element.is_visible():
            continue

        tag = element.evaluate("e => e.tagName.toLowerCase()")
        role = element.get_attribute("role") or ("combobox" if tag == "select" else "textbox")
        # A custom widget carries its label in surrounding text, not on itself.
        if not element.get_attribute("aria-labelledby") and tag not in {"input", "textarea", "select"}:
            pass
        raw_name = _accessible_name(element)
        context = _nearby_text(element)

        # "Select", "Select...", "Choose" are placeholder text, not a label.
        # When that is all a custom widget offers, the real question is in the
        # surrounding text.
        if GENERIC_NAMES.match(raw_name or "") and context:
            raw_name = context

        if not raw_name and input_type != "file":
            continue

        kind = _kind_for(element, tag, role, raw_name)

        options = None
        if kind in {"select", "radio", "combobox"}:
            options = [
                (o.inner_text() or o.get_attribute("value") or "").strip()
                for o in element.locator("option").all()
            ]

        name = re.sub(r"\s*(Select\.{0,3}|Choose\.{0,3})\s*$", "", raw_name, flags=re.I)
        name = name.rstrip("* ").strip()[:150] or "(unlabelled file upload)"
        index += 1
        fields.append(
            FormField(
                field_id=f"f_{index:02d}",
                role=role,
                accessible_name=name,
                kind=kind,
                required=_is_required(element, raw_name),
                options=options,
                current_value=element.get_attribute("value") or None,
                help_text=context[:300] if kind == "attention_check" else None,
            )
        )

    def button_names(pattern: str) -> list[str]:
        found = []
        for b in page.get_by_role("button").all():
            text = (b.inner_text() or "").strip()
            if text and re.search(pattern, text, re.I):
                found.append(text)
        return found

    return FormSnapshot(
        url=page.url,
        page_title=page.title(),
        page_kind="form" if fields else "unknown",
        ats=detect_ats(page.url),
        fields=fields,
        next_buttons=button_names(r"\b(next|continue)\b"),
        submit_buttons=button_names(r"\b(submit|apply|send)\b"),
    )


def locator_for(page, field: FormField):
    """Resolve a FormField back to a Playwright locator.

    Role + accessible name, because that pair is stable across renders while
    name/id are not.
    """
    return page.get_by_role(field.role, name=field.accessible_name, exact=True)
