from backend.schemas import CivicContext, DataOrigin, DtprStep


def build_demo_dtpr_chain(civic_context: CivicContext | None = None) -> list[DtprStep]:
    steps = [
        DtprStep(
            id="voice-text",
            label="Resident description",
            data_type="voice-to-text transcript",
            purpose="Understand the reported condition in the resident's own words.",
            processor="browser placeholder, backend report pipeline",
            destination="draft report",
            retention="session draft until confirmation",
            control_point="resident can review, correct, or cancel",
            origin=DataOrigin.COLLECTED,
        ),
        DtprStep(
            id="location",
            label="Location",
            data_type="spatial location",
            purpose="Route the report and identify nearby safety context.",
            processor="browser location placeholder, backend report pipeline",
            destination="draft report routing fields",
            retention="confirmed report payload only after resident confirmation",
            control_point="resident must confirm location before live submission",
            origin=DataOrigin.COLLECTED,
        ),
        DtprStep(
            id="image-context",
            label="Camera context",
            data_type="pixel-based image summary",
            purpose="Identify visible flooding and pedestrian conditions.",
            processor="future multimodal model, mocked in this non-live pipeline",
            destination="inferred context and narrative explanation",
            retention="no image stored in this demo fixture",
            control_point="resident controls camera permission and final confirmation",
            origin=DataOrigin.INFERRED,
        ),
        DtprStep(
            id="routing",
            label="Routing suggestion",
            data_type="generated service category, agency route, and civic context",
            purpose="Suggest the city service path most likely to resolve the issue.",
            processor=(
                "backend routing fallback with 311 historical-context provider"
                if civic_context
                else "backend routing fallback"
            ),
            destination="draft report routing recommendation",
            retention="confirmed report payload only after resident confirmation",
            control_point="resident reviews the suggested category before confirmation",
            origin=DataOrigin.SELECTED,
        ),
        DtprStep(
            id="human-review",
            label="Human review",
            data_type="uncertainty and review fields",
            purpose="Show what still needs confirmation or agency judgment.",
            processor="backend report pipeline",
            destination="draft review screen and post-submission data chain",
            retention="session draft until confirmation",
            control_point="resident can correct report details before confirmation",
            origin=DataOrigin.REVIEW_REQUIRED,
        ),
    ]

    if civic_context is not None:
        steps.insert(
            3,
            DtprStep(
                id="civic-open-data-context",
                label="Civic open-data context",
                data_type="historical 311 service-request summary",
                purpose="Ground report wording, routing, and uncertainty in similar civic records.",
                processor=civic_context.source,
                destination="draft report context and future model prompt packet",
                retention="summary retained with the draft; raw historical rows are not stored",
                control_point="resident reviews and edits the draft before confirmation",
                origin=DataOrigin.INFERRED,
            ),
        )

    return steps
