from datetime import datetime, timezone
from uuid import uuid4

from backend.schemas import (
    CollectedInput,
    DataOrigin,
    EvidenceItem,
    HumanReviewField,
    InferredContext,
    Location,
    Priority,
    ReportDraft,
    ReportDraftRequest,
    UncertaintyItem,
)
from backend.tools.dtpr import build_demo_dtpr_chain
from backend.tools.routing import fallback_route_for_category


DEMO_TRANSCRIPT = (
    "There is flooding at the school crossing. Kids are walking around the water "
    "and stepping into traffic."
)
DEMO_IMAGE_SUMMARY = "Standing water is visible along the curb and crosswalk approach."
DEMO_LOCATION = Location(
    label="Demo school crossing near W 43rd St and 8th Ave, Manhattan",
    latitude=40.7589,
    longitude=-73.9891,
    confirmed=False,
)


def build_report_draft(request: ReportDraftRequest) -> ReportDraft:
    if request.scenario and request.scenario != "flooding_near_school_crossing":
        raise ValueError("Unsupported scenario")

    transcript = request.transcript or DEMO_TRANSCRIPT
    image_summary = request.image_summary or DEMO_IMAGE_SUMMARY
    location = request.location or DEMO_LOCATION
    routing = fallback_route_for_category("street_flooding", "near_school_crossing")

    return ReportDraft(
        id=f"draft_{uuid4().hex[:10]}",
        status="draft",
        category="street_flooding",
        subcategory="near_school_crossing",
        title="Flooding blocking a school crossing",
        description=(
            "Standing water is affecting a pedestrian crossing near a school and may "
            "be forcing children and caregivers into traffic."
        ),
        narrative=(
            "A resident reports flooding at a school crossing. Based on the description "
            "and visual context, the concern is not only standing water but pedestrian "
            "safety: children may need to walk around the flooded area into the roadway."
        ),
        location=location,
        observed_at=datetime.now(timezone.utc),
        priority=Priority.HIGH,
        routing=routing,
        collected_inputs=[
            CollectedInput(kind="text", value=transcript),
            CollectedInput(
                kind="location",
                value=location.label or "Location provided without a label",
            ),
        ],
        inferred_context=[
            InferredContext(
                label="Visible condition",
                value=image_summary,
                confidence=0.82,
            ),
            InferredContext(
                label="Human impact",
                value="Pedestrians, including children, may be pushed into traffic.",
                confidence=0.78,
            ),
            InferredContext(
                label="Likely service category",
                value="Street flooding near a school crossing",
                confidence=0.76,
                origin=DataOrigin.SELECTED,
            ),
        ],
        human_review=[
            HumanReviewField(
                field="location.confirmed",
                reason="Resident must confirm the exact crossing before live submission.",
                current_value=str(location.confirmed),
            ),
            HumanReviewField(
                field="routing",
                reason="Fallback routing should be reviewed against live NYC311 service rules.",
                current_value=routing.service,
            ),
        ],
        evidence=[
            EvidenceItem(kind="text", summary=transcript),
            EvidenceItem(kind="image", summary=image_summary),
            EvidenceItem(kind="location", summary=location.label or "Approximate location"),
        ],
        questions_asked=[
            "Is this the exact crossing where the flooding is happening?",
            "Is the water actively rising or blocking the full crosswalk?",
            "Is there a visible clogged catch basin or drain?",
        ],
        uncertainty=[
            UncertaintyItem(
                field="location",
                reason="Demo location is approximate until the resident confirms it.",
                confidence=0.68,
            ),
            UncertaintyItem(
                field="responsible_department",
                reason="Sewer, street, and transportation safety routing can overlap.",
                confidence=0.74,
            ),
        ],
        dtpr_chain=build_demo_dtpr_chain(),
    )
