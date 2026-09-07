from pathlib import Path

import pytest

from job_agent.browser import browser_context
from job_agent.flow import classify_page, run_application
from job_agent.models import FillPlan, PlannedField

FIXTURES = Path(__file__).parent / "fixtures"


def url(name):
    return (FIXTURES / name).resolve().as_uri()


@pytest.fixture(scope="module")
def ctx():
    with browser_context(headless=True) as context:
        yield context


def test_a_page_with_a_password_field_is_a_login(ctx):
    page = ctx.new_page()
    page.goto(url("login.html"))
    assert classify_page(page) == "login"


def test_a_page_with_no_fields_and_confirmation_wording_is_a_confirmation(ctx):
    page = ctx.new_page()
    page.goto(url("confirmation.html"))
    assert classify_page(page) == "confirmation"


def test_a_page_with_editable_fields_is_a_form(ctx):
    page = ctx.new_page()
    page.goto(url("wizard_page1.html"))
    assert classify_page(page) == "form"


class StubPlanner:
    """Plans the first field of every page, so the loop has work to do."""

    def __init__(self):
        self.calls = 0

    def __call__(self, snapshot):
        self.calls += 1
        if not snapshot.fields:
            return FillPlan()
        return FillPlan(fields=[PlannedField(
            field_id=snapshot.fields[0].field_id, value="x",
            source="profile", confidence=1.0, note="stub",
        )])


def test_the_loop_advances_through_a_two_page_wizard(ctx):
    page = ctx.new_page()
    page.goto(url("wizard_page1.html"))
    planner = StubPlanner()
    result = run_application(page, planner=planner)

    assert planner.calls == 2, "planned page 1 and page 2"
    assert result.pages_visited == 2


def test_the_page_cap_is_enforced(ctx):
    page = ctx.new_page()
    page.goto(url("wizard_page1.html"))
    result = run_application(page, planner=StubPlanner(), max_pages=1)
    assert result.pages_visited == 1
    assert result.outcome in {"guard_tripped", "ready_for_human"}


def test_run_application_has_no_submit_parameter():
    """The agent cannot submit. Not "does not by default" — cannot.

    Removing the capability rather than defaulting it off means there is no
    flag, no config, and no callable that could turn it back on by accident.
    """
    import inspect

    params = inspect.signature(run_application).parameters
    assert "submit" not in params
    assert not any("submit" in p.lower() for p in params)


def test_no_module_clicks_a_submit_control():
    """Structural guard: nothing in the package targets a submit/apply button.

    Navigation clicks Next/Continue, extraction opens comboboxes, and filling
    clicks options. None of those is a submit. This test exists so that
    re-adding one has to be deliberate rather than incidental.
    """
    import re
    from pathlib import Path

    offenders = []
    for path in sorted(Path("src/job_agent").glob("*.py")):
        source = path.read_text()
        for match in re.finditer(r"""name\s*=\s*["'](submit|apply)""", source, re.I):
            line = source[: match.start()].count("\n") + 1
            offenders.append(f"{path}:{line}")
    assert not offenders, f"submit-targeting locator found: {offenders}"


def test_reaching_a_page_with_a_submit_button_stops_and_hands_over(ctx):
    page = ctx.new_page()
    page.goto(url("wizard_page2.html"))
    result = run_application(page, planner=StubPlanner())

    assert result.outcome == "ready_for_human"
    assert "yourself" in (result.detail or "").lower()


def test_the_form_is_still_filled_before_handing_over(ctx):
    """Stopping short of submit must not mean stopping short of filling."""
    page = ctx.new_page()
    page.goto(url("wizard_page2.html"))
    run_application(page, planner=StubPlanner())
    assert page.input_value("#b") == "x"


def test_a_consent_dialog_is_dismissed_so_clicks_land(ctx):
    """A privacy dialog intercepting pointer events makes every click time out
    with a log that says the element is "visible, enabled and stable"."""
    from job_agent.flow import dismiss_overlays

    page = ctx.new_page()
    page.goto(url("consent_dialog.html"))
    assert page.locator("#backdrop").count() == 1

    closed = dismiss_overlays(page)

    assert closed == 1
    assert page.locator("#backdrop").count() == 0


def test_overlay_dismissal_never_clicks_a_dangerous_button(ctx):
    """The dismisser uses an allowlist, so it cannot press Submit or Apply."""
    from job_agent.flow import CONSENT_WORDS

    for dangerous in ["Submit", "Apply", "Apply Now", "Delete", "Send application"]:
        assert not CONSENT_WORDS.match(dangerous), dangerous
    for safe in ["OK", "Accept all", "I agree", "Got it"]:
        assert CONSENT_WORDS.match(safe), safe


def test_a_blocked_navigation_click_does_not_crash(ctx):
    """An exception here would close the browser and discard hand-typed work."""
    page = ctx.new_page()
    page.set_content(
        "<div role='dialog' style='position:fixed;inset:0;z-index:9'>blocked</div>"
        "<button>Next</button><input aria-label='Name'>"
    )
    result = run_application(page, planner=StubPlanner(), max_pages=2)
    assert result.outcome in {"ready_for_human", "needs_human", "guard_tripped"}


def test_advance_matches_save_and_continue(ctx):
    """Multi-step forms label this button many ways; a bare \\bnext\\b misses
    most of them."""
    from job_agent.flow import ADVANCE_PATTERNS
    import re

    for label in ["Next", "Continue", "Save and continue", "Save & Continue",
                  "Save and Next", "Proceed", "Next Step"]:
        assert any(re.search(p, label, re.I) for p in ADVANCE_PATTERNS), label


def test_advance_can_never_match_a_submitting_button():
    """Advancing must not be able to send the application."""
    from job_agent.flow import ADVANCE_PATTERNS
    import re

    for label in ["Submit", "Submit application", "Apply", "Apply Now", "Send application"]:
        assert not any(re.search(p, label, re.I) for p in ADVANCE_PATTERNS), label


def test_advance_clicks_the_next_control(ctx):
    page = ctx.new_page()
    page.goto(url("wizard_page1.html"))
    from job_agent.flow import advance

    assert advance(page) is True
    assert "wizard_page2" in page.url
