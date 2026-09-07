from pathlib import Path

from job_agent.models import FillPlan, FormField, FormSnapshot, PlannedField
from job_agent.plan import CONFIDENCE_FLOOR, apply_safety_rules, build_plan
from job_agent.profile import load_profile


def field(fid, name, kind="text", required=True, current_value=None) -> FormField:
    return FormField(
        field_id=fid,
        role="textbox",
        accessible_name=name,
        kind=kind,
        required=required,
        current_value=current_value,
    )


SNAPSHOT = FormSnapshot(
    url="https://ats.rippling.com/x/apply",
    page_title="Apply",
    page_kind="form",
    ats="rippling",
    fields=[
        field("f_01", "First name"),
        field("f_02", "Email"),
        field("f_03", "Select the second word of this sentence", kind="attention_check"),
        field("f_04", "Are you authorized to work in the US?"),
    ],
)


class StubClient:
    """Stands in for anthropic.Anthropic().messages.parse."""

    def __init__(self, plan: FillPlan):
        self._plan = plan
        self.calls = []

    @property
    def messages(self):
        return self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return type("R", (), {"parsed_output": self._plan, "usage": None})()


def test_low_confidence_values_become_unresolved():
    raw = FillPlan(fields=[
        PlannedField(field_id="f_01", value="Johny", source="profile", confidence=0.99, note="from profile"),
        PlannedField(field_id="f_02", value="guess@x.com", source="generated", confidence=0.4, note="guessed"),
    ])
    safe = apply_safety_rules(raw, SNAPSHOT)
    ids = {f.field_id for f in safe.fields}
    assert "f_01" in ids
    assert "f_02" not in ids
    assert any(u.field_id == "f_02" for u in safe.unresolved)


def test_attention_checks_are_always_unresolved_even_at_full_confidence():
    raw = FillPlan(fields=[
        PlannedField(field_id="f_03", value="value", source="generated", confidence=1.0, note="easy"),
    ])
    safe = apply_safety_rules(raw, SNAPSHOT)
    assert not safe.fields
    assert any("attention" in u.reason.lower() for u in safe.unresolved)


def test_generated_work_authorization_answers_are_refused():
    raw = FillPlan(fields=[
        PlannedField(field_id="f_04", value="Yes", source="generated", confidence=0.95, note="inferred"),
    ])
    safe = apply_safety_rules(raw, SNAPSHOT)
    assert not safe.fields
    assert any("authorization" in u.reason.lower() for u in safe.unresolved)


def test_profile_sourced_work_authorization_is_allowed():
    raw = FillPlan(fields=[
        PlannedField(field_id="f_04", value="Yes", source="profile", confidence=0.99, note="from profile"),
    ])
    safe = apply_safety_rules(raw, SNAPSHOT)
    assert [f.field_id for f in safe.fields] == ["f_04"]


def test_a_plan_for_an_unknown_field_id_is_dropped():
    raw = FillPlan(fields=[
        PlannedField(field_id="f_99", value="x", source="profile", confidence=1.0, note="hallucinated"),
    ])
    safe = apply_safety_rules(raw, SNAPSHOT)
    assert not safe.fields
    assert any(u.field_id == "f_99" for u in safe.unresolved)


def test_endorsing_a_prefilled_value_we_cannot_confirm_is_refused():
    snapshot = FormSnapshot(
        url="https://x", page_title="t", page_kind="form",
        fields=[field("f_10", "Current employer", required=False, current_value="Acme Corp")],
    )
    raw = FillPlan(fields=[
        PlannedField(field_id="f_10", value="Acme Corp", source="generated",
                     confidence=0.9, note="already filled, looks fine"),
    ])
    safe = apply_safety_rules(raw, snapshot)
    assert not safe.fields
    assert any("parser" in u.reason.lower() for u in safe.unresolved)


def test_profile_values_overwrite_a_prefilled_field():
    snapshot = FormSnapshot(
        url="https://x", page_title="t", page_kind="form",
        fields=[field("f_11", "First name", current_value="Jonathan")],
    )
    raw = FillPlan(fields=[
        PlannedField(field_id="f_11", value="Johny", source="profile",
                     confidence=0.99, note="from profile; parser guessed Jonathan"),
    ])
    safe = apply_safety_rules(raw, snapshot)
    assert [f.value for f in safe.fields] == ["Johny"]


def test_build_plan_sends_the_snapshot_and_the_cached_profile():
    client = StubClient(FillPlan(fields=[], unresolved=[]))
    profile = load_profile(Path("profile.example.yaml"))

    build_plan(client, SNAPSHOT, profile)

    call = client.calls[0]
    assert call["output_format"] is FillPlan
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "f_01" in str(call["messages"])


def test_confidence_floor_is_documented_not_magic():
    assert 0.0 < CONFIDENCE_FLOOR < 1.0
