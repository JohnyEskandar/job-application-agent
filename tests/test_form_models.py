import pytest
from pydantic import ValidationError

from job_agent.models import FormField, FormSnapshot


def make_field(**kw) -> FormField:
    base = dict(
        field_id="f_01",
        role="textbox",
        accessible_name="First name",
        kind="text",
        required=True,
    )
    return FormField(**{**base, **kw})


def test_field_ids_are_opaque_so_the_model_never_sees_css():
    field = make_field()
    assert field.field_id == "f_01"
    assert not hasattr(field, "css_selector")


def test_options_are_required_for_a_choice_field():
    with pytest.raises(ValidationError, match="options"):
        make_field(kind="select", options=None)


def test_attention_check_is_a_distinct_kind():
    field = make_field(kind="attention_check", accessible_name="Select the second word")
    assert field.kind == "attention_check"


def test_snapshot_rejects_duplicate_field_ids():
    with pytest.raises(ValidationError, match="unique"):
        FormSnapshot(
            url="https://x",
            page_title="t",
            page_kind="form",
            fields=[make_field(), make_field()],
        )


def test_snapshot_defaults_to_no_buttons():
    snap = FormSnapshot(url="https://x", page_title="t", page_kind="form", fields=[])
    assert snap.next_buttons == []
    assert snap.submit_buttons == []
