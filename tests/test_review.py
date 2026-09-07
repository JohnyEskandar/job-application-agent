from job_agent.models import (
    FieldResult, FillPlan, FillReport, FormField, FormSnapshot, PlannedField, Unresolved,
)
from job_agent.review import VALID_DECISIONS, render_review

SNAP = FormSnapshot(
    url="https://x/apply", page_title="Apply - Quant Trader", page_kind="form", ats="rippling",
    fields=[
        FormField(field_id="f_01", role="textbox", accessible_name="First name", kind="text"),
        FormField(field_id="f_02", role="textbox", accessible_name="Why this firm?", kind="textarea"),
        FormField(field_id="f_03", role="textbox", accessible_name="Select the second word", kind="attention_check"),
    ],
)
PLAN = FillPlan(
    fields=[
        PlannedField(field_id="f_01", value="Johny", source="profile", confidence=1.0, note="profile"),
        PlannedField(field_id="f_02", value="I admire the...", source="generated", confidence=0.8, note="drafted"),
    ],
    unresolved=[Unresolved(field_id="f_03", reason="attention check - human only")],
)
REPORT = FillReport(results=[
    FieldResult(field_id="f_01", outcome="verified", intended="Johny", observed="Johny"),
    FieldResult(field_id="f_02", outcome="verified", intended="I admire the...", observed="I admire the..."),
])


def test_review_shows_every_value_with_its_source():
    text = render_review(SNAP, PLAN, REPORT, screenshot="runs/x.png")
    assert "First name" in text
    assert "Johny" in text
    assert "profile" in text


def test_generated_values_are_visually_flagged():
    text = render_review(SNAP, PLAN, REPORT, screenshot="runs/x.png")
    generated_line = next(l for l in text.splitlines() if "Why this firm?" in l)
    assert "REVIEW" in generated_line.upper()


def test_profile_values_are_not_flagged_for_review():
    text = render_review(SNAP, PLAN, REPORT, screenshot="runs/x.png")
    profile_line = next(l for l in text.splitlines() if "First name" in l)
    assert "REVIEW" not in profile_line.upper()


def test_unresolved_fields_appear_so_they_cannot_be_missed():
    text = render_review(SNAP, PLAN, REPORT, screenshot="runs/x.png")
    assert "Select the second word" in text
    assert "attention check" in text.lower()


def test_a_failed_write_is_shown_as_a_failure():
    report = FillReport(results=[
        FieldResult(field_id="f_01", outcome="mismatch", intended="Johny", observed=""),
    ])
    text = render_review(SNAP, PLAN, report, screenshot="runs/x.png")
    assert "FAILED" in text


def test_the_screenshot_path_is_shown():
    text = render_review(SNAP, PLAN, REPORT, screenshot="runs/2026/page.png")
    assert "runs/2026/page.png" in text


def test_there_is_no_submit_decision_at_all():
    """Not "submit is off by default" — there is no submit option to choose."""
    assert VALID_DECISIONS == {}


def test_the_summary_says_who_submits():
    text = render_review(SNAP, PLAN, REPORT, screenshot="runs/x.png")
    assert "cannot submit" in text.lower()
    assert "yourself" in text.lower()
