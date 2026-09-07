from job_agent.fill import order_for_execution
from job_agent.models import FormField, FormSnapshot, PlannedField


def field(fid, name, kind):
    return FormField(
        field_id=fid, role="textbox", accessible_name=name, kind=kind,
        options=[] if kind in {"select", "radio", "combobox"} else None,
    )


SNAP = FormSnapshot(
    url="https://x", page_title="t", page_kind="form",
    fields=[
        field("f_01", "First name", "text"),
        field("f_02", "Resume", "file"),
        field("f_03", "Email", "text"),
    ],
)


def planned(fid):
    return PlannedField(field_id=fid, value="v", source="profile", confidence=1.0, note="t")


def test_file_uploads_are_executed_first():
    """The site parses the resume to prefill. Uploading first means our values
    land afterwards and win; uploading last would let the parser overwrite us."""
    ordered = order_for_execution(SNAP, [planned("f_01"), planned("f_02"), planned("f_03")])
    assert [p.field_id for p in ordered][0] == "f_02"


def test_non_file_order_is_otherwise_preserved():
    ordered = order_for_execution(SNAP, [planned("f_03"), planned("f_01")])
    assert [p.field_id for p in ordered] == ["f_03", "f_01"]


def test_ordering_is_stable_with_no_files_at_all():
    ordered = order_for_execution(SNAP, [planned("f_01"), planned("f_03")])
    assert [p.field_id for p in ordered] == ["f_01", "f_03"]
