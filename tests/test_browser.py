from pathlib import Path

from job_agent.browser import browser_context

FIXTURE = (Path(__file__).parent / "fixtures" / "simple_form.html").resolve()
FIXTURE_URL = FIXTURE.as_uri()


def test_context_opens_and_loads_a_local_page():
    with browser_context(headless=True) as ctx:
        page = ctx.new_page()
        page.goto(FIXTURE_URL)
        assert page.title() == "Application Form"


def test_filling_a_field_actually_sticks():
    with browser_context(headless=True) as ctx:
        page = ctx.new_page()
        page.goto(FIXTURE_URL)
        page.fill("#first_name", "Alex")
        # read it back — a fill that silently reverts is the failure mode
        # that matters on real ATS forms
        assert page.input_value("#first_name") == "Alex"


def test_select_and_textarea_also_round_trip():
    with browser_context(headless=True) as ctx:
        page = ctx.new_page()
        page.goto(FIXTURE_URL)
        page.fill("#cover", "Because it is interesting.")
        page.select_option("#source", "referral")
        assert page.input_value("#cover") == "Because it is interesting."
        assert page.input_value("#source") == "referral"


def test_profile_directory_is_created(tmp_path):
    profile_dir = tmp_path / "browser-profile"
    with browser_context(headless=True, profile_dir=profile_dir):
        pass
    assert profile_dir.exists()


def test_screenshot_writes_a_file(tmp_path):
    shot = tmp_path / "page.png"
    with browser_context(headless=True) as ctx:
        page = ctx.new_page()
        page.goto(FIXTURE_URL)
        page.screenshot(path=str(shot))
    assert shot.exists() and shot.stat().st_size > 0
