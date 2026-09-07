"""Extractor tests.

All tests share ONE browser context. Playwright's sync API cannot start a
second sync_playwright() while another is live, so a module-scoped fixture
plus per-test pages is the only structure that works here.
"""

from pathlib import Path

import pytest

from job_agent.browser import browser_context
from job_agent.extract import detect_ats, extract_snapshot, locator_for

FIXTURES = Path(__file__).parent / "fixtures"
SIMPLE = (FIXTURES / "simple_form.html").resolve().as_uri()
RIPPLING = (FIXTURES / "rippling_apply.html").resolve().as_uri()


@pytest.fixture(scope="module")
def ctx():
    with browser_context(headless=True) as context:
        yield context


@pytest.fixture(scope="module")
def rippling_page(ctx):
    page = ctx.new_page()
    page.goto(RIPPLING)
    page.wait_for_timeout(400)
    return page


@pytest.fixture(scope="module")
def rippling(rippling_page):
    return extract_snapshot(rippling_page)


def test_simple_form_fields_are_found_with_their_labels(ctx):
    page = ctx.new_page()
    page.goto(SIMPLE)
    snap = extract_snapshot(page)
    names = {f.accessible_name for f in snap.fields}
    assert "First name" in names
    assert "Email" in names


def test_rippling_labels_survive_hashed_name_attributes(rippling):
    names = {f.accessible_name for f in rippling.fields}
    assert "First name" in names
    assert "Last name" in names
    assert "Email" in names
    assert "LinkedIn Link" in names


def test_requiredness_comes_from_aria_not_the_html_attribute(rippling):
    by_name = {f.accessible_name: f for f in rippling.fields}
    assert by_name["First name"].required is True
    assert by_name["LinkedIn Link"].required is False


def test_the_attention_check_is_classified_not_treated_as_prose(rippling):
    checks = [f for f in rippling.fields if f.kind == "attention_check"]
    assert len(checks) == 1, "exactly one attention check on this form"
    assert "second word" in checks[0].accessible_name.lower()


def test_ordinary_fields_are_not_swept_up_as_attention_checks(rippling):
    by_name = {f.accessible_name: f for f in rippling.fields}
    assert by_name["First name"].kind == "text"
    assert by_name["Email"].kind == "text"


def test_custom_aria_widgets_are_found_not_just_native_tags(rippling):
    """Rippling renders dropdowns as <div role=combobox>.

    A tag-only query (input, textarea, select) misses every one of these —
    including all five EEO questions.
    """
    names = {f.accessible_name for f in rippling.fields}
    assert "Gender" in names
    assert "Veteran Status" in names
    assert "Disability Status" in names


def test_file_uploads_are_found(rippling):
    assert any(f.kind == "file" for f in rippling.fields)


def test_extraction_is_deterministic(rippling_page):
    a = extract_snapshot(rippling_page)
    b = extract_snapshot(rippling_page)
    assert [f.field_id for f in a.fields] == [f.field_id for f in b.fields]
    assert [f.accessible_name for f in a.fields] == [f.accessible_name for f in b.fields]


def test_locator_for_resolves_to_exactly_one_element(rippling_page, rippling):
    field = next(f for f in rippling.fields if f.accessible_name == "First name")
    assert locator_for(rippling_page, field).count() == 1


def test_snapshot_is_small_enough_to_send_cheaply(rippling):
    payload = rippling.model_dump_json()
    assert len(payload) < 20000, f"snapshot is {len(payload)} chars"


def test_detect_ats_reads_the_host():
    assert detect_ats("https://ats.rippling.com/en-CA/x/jobs/1/apply") == "rippling"
    assert detect_ats("https://boards.greenhouse.io/acme/jobs/1") == "greenhouse"
    assert detect_ats("https://jobs.lever.co/acme/1") == "lever"
    assert detect_ats("https://example.com/careers") is None
