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
