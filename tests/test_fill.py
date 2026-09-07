from pathlib import Path

import pytest

from job_agent.browser import browser_context
from job_agent.extract import extract_snapshot
from job_agent.fill import execute_plan
from job_agent.models import FillPlan, PlannedField

FIXTURES = Path(__file__).parent / "fixtures"
SIMPLE = (FIXTURES / "simple_form.html").resolve().as_uri()


@pytest.fixture(scope="module")
def ctx():
    with browser_context(headless=True) as context:
        yield context


def plan_for(snapshot, name, value, source="profile"):
    field = next(f for f in snapshot.fields if f.accessible_name == name)
    return PlannedField(
        field_id=field.field_id, value=value, source=source, confidence=0.99, note="test"
    )


def test_a_text_field_is_written_and_verified(ctx):
    page = ctx.new_page()
    page.goto(SIMPLE)
    snap = extract_snapshot(page)
    report = execute_plan(page, snap, FillPlan(fields=[plan_for(snap, "First name", "Johny")]))

    assert report.ok
    assert report.results[0].outcome == "verified"
    assert page.input_value("#first_name") == "Johny"


def test_a_textarea_is_written_and_verified(ctx):
    page = ctx.new_page()
    page.goto(SIMPLE)
    snap = extract_snapshot(page)
    report = execute_plan(
        page, snap, FillPlan(fields=[plan_for(snap, "Why do you want this role?", "Because.")])
    )
    assert report.ok
    assert page.input_value("#cover") == "Because."


def test_a_native_select_is_chosen_and_verified(ctx):
    page = ctx.new_page()
    page.goto(SIMPLE)
    snap = extract_snapshot(page)
    report = execute_plan(
        page, snap, FillPlan(fields=[plan_for(snap, "How did you hear about us?", "Referral")])
    )
    assert report.ok
    assert page.input_value("#source") == "referral"


def test_a_value_that_will_not_stick_is_reported_as_mismatch(ctx):
    """The failure mode that matters: a write that silently reverts.

    This is what a controlled React input does when its onChange handler
    rejects the value. Without read-back it looks like success.
    """
    page = ctx.new_page()
    page.goto(SIMPLE)
    page.eval_on_selector(
        "#first_name", "el => el.addEventListener('input', () => { el.value = ''; })"
    )
    snap = extract_snapshot(page)
    report = execute_plan(page, snap, FillPlan(fields=[plan_for(snap, "First name", "Johny")]))

    assert not report.ok
    assert report.results[0].outcome == "mismatch"
    assert report.results[0].observed == ""


def test_a_plan_referencing_a_missing_field_is_an_error_not_a_crash(ctx):
    page = ctx.new_page()
    page.goto(SIMPLE)
    snap = extract_snapshot(page)
    bogus = PlannedField(
        field_id="f_99", value="x", source="profile", confidence=1.0, note="not on this page"
    )
    report = execute_plan(page, snap, FillPlan(fields=[bogus]))
    assert report.results[0].outcome == "error"


def test_attention_check_fields_are_never_filled_even_if_planned(ctx):
    """Belt and braces: the planner should never plan one, but if it does,
    the executor still refuses."""
    page = ctx.new_page()
    page.goto(SIMPLE)
    snap = extract_snapshot(page)
    field = next(f for f in snap.fields if f.accessible_name == "First name")
    patched = field.model_copy(update={"kind": "attention_check"})
    snap = snap.model_copy(update={"fields": [patched]})

    planned = PlannedField(
        field_id=patched.field_id, value="value", source="generated", confidence=1.0, note="x"
    )
    report = execute_plan(page, snap, FillPlan(fields=[planned]))
    assert report.results[0].outcome == "skipped"
    assert page.input_value("#first_name") == ""
