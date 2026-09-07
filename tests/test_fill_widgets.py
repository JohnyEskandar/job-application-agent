from pathlib import Path

import pytest

from job_agent.browser import browser_context
from job_agent.extract import extract_snapshot, locator_for
from job_agent.fill import choose_in_custom_combobox, execute_plan, upload_file
from job_agent.models import FillPlan, PlannedField

FIXTURES = Path(__file__).parent / "fixtures"
WIDGETS = (FIXTURES / "custom_combobox.html").resolve().as_uri()
ANY_FILE = Path("profile.example.yaml").resolve()


@pytest.fixture(scope="module")
def ctx():
    with browser_context(headless=True) as context:
        yield context


def test_a_div_based_combobox_can_be_set(ctx):
    page = ctx.new_page()
    page.goto(WIDGETS)
    snap = extract_snapshot(page)
    field = next(f for f in snap.fields if f.accessible_name == "Favourite colour")

    choose_in_custom_combobox(page, locator_for(page, field), "Blue")

    assert page.locator("#fav").inner_text().strip() == "Blue"


def test_select_option_would_not_have_worked(ctx):
    """Documents why choose_in_custom_combobox exists at all."""
    page = ctx.new_page()
    page.goto(WIDGETS)
    with pytest.raises(Exception):
        page.locator("#fav").select_option("Blue")


def test_a_file_upload_is_verified_by_the_file_being_attached(ctx):
    page = ctx.new_page()
    page.goto(WIDGETS)
    upload_file(page, page.locator("#cv"), ANY_FILE)
    assert page.eval_on_selector("#cv", "e => e.files.length") == 1


def test_execute_plan_routes_the_combobox_kind(ctx):
    page = ctx.new_page()
    page.goto(WIDGETS)
    snap = extract_snapshot(page)
    combo = next(f for f in snap.fields if f.kind == "combobox")
    report = execute_plan(page, snap, FillPlan(fields=[PlannedField(
        field_id=combo.field_id, value="Red", source="profile", confidence=1.0, note="t"
    )]))
    assert report.results[0].outcome == "verified", report.results[0]


def test_execute_plan_routes_the_file_kind(ctx):
    page = ctx.new_page()
    page.goto(WIDGETS)
    snap = extract_snapshot(page)
    file_field = next(f for f in snap.fields if f.kind == "file")
    report = execute_plan(page, snap, FillPlan(fields=[PlannedField(
        field_id=file_field.field_id, value=str(ANY_FILE), source="profile",
        confidence=1.0, note="t"
    )]))
    assert report.results[0].outcome == "verified", report.results[0]
