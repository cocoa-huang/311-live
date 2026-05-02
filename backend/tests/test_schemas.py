from backend.schemas import Location, ReportDraft


def test_report_draft_schema_accepts_placeholder_contract() -> None:
    draft = ReportDraft(
        id="draft_demo",
        category="street_flooding",
        subcategory="near_school_crossing",
        title="Flooding near school crossing",
        description="Standing water is blocking a pedestrian crossing near a school.",
        narrative="The issue creates a pedestrian safety concern near a school.",
        location=Location(label="Demo school crossing", confirmed=False),
    )

    assert draft.status == "draft"
    assert draft.location.confirmed is False
    assert draft.evidence == []
    assert draft.dtpr_chain == []
