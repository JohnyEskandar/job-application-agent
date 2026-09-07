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
    result = run_application(page, planner=planner, decide=lambda *_: "abandon")

    assert planner.calls == 2, "planned page 1 and page 2"
    assert result.pages_visited == 2


def test_the_page_cap_is_enforced(ctx):
    page = ctx.new_page()
    page.goto(url("wizard_page1.html"))
    result = run_application(
        page, planner=StubPlanner(), decide=lambda *_: "abandon", max_pages=1
    )
    assert result.pages_visited == 1
    assert result.outcome in {"guard_tripped", "abandoned"}


def test_the_flow_never_submits_without_approval(ctx):
    """The load-bearing test of this entire project."""
    page = ctx.new_page()
    page.goto(url("wizard_page2.html"))

    submitted = []
    result = run_application(
        page,
        planner=StubPlanner(),
        decide=lambda *_: "abandon",
        submit=lambda *_: submitted.append(True),
    )
    assert submitted == [], "submit was called without approval"
    assert result.outcome == "abandoned"


def test_no_decision_other_than_submit_submits(ctx):
    """Every non-'submit' answer must abandon, including a typo or None."""
    for decision in ["abandon", "edit", "open", "", None, "SUBMIT ", "yes"]:
        page = ctx.new_page()
        page.goto(url("wizard_page2.html"))
        submitted = []
        run_application(
            page,
            planner=StubPlanner(),
            decide=lambda *_, d=decision: d,
            submit=lambda *_: submitted.append(True),
        )
        assert submitted == [], f"decision {decision!r} caused a submit"


def test_approval_is_what_calls_submit(ctx):
    page = ctx.new_page()
    page.goto(url("wizard_page2.html"))

    submitted = []
    run_application(
        page,
        planner=StubPlanner(),
        decide=lambda *_: "submit",
        submit=lambda *_: submitted.append(True),
    )
    assert submitted == [True]
