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
from backend.tools.nyc_311_context import (
    CivicContextProvider,
    ContextProviderError,
    Fallback311ContextProvider,
    fallback_311_context,
)
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


DEMO_VARIANTS = {
    "baseline": {
        "transcript": DEMO_TRANSCRIPT,
        "image_summary": DEMO_IMAGE_SUMMARY,
        "location": DEMO_LOCATION,
        "human_impact": "Pedestrians, including children, may be pushed into traffic.",
        "description": (
            "Standing water is affecting a pedestrian crossing near a school and may "
            "be forcing children and caregivers into traffic."
        ),
        "narrative": (
            "A resident reports flooding at a school crossing. Based on the description "
            "and visual context, the concern is not only standing water but pedestrian "
            "safety: children may need to walk around the flooded area into the roadway."
        ),
    },
    "confirmed_location": {
        "transcript": (
            "I am at the exact school crossing at West 43rd Street and 8th Avenue. "
            "There is flooding at the curb ramp and children are walking around it."
        ),
        "image_summary": DEMO_IMAGE_SUMMARY,
        "location": DEMO_LOCATION.model_copy(update={"confirmed": True}),
        "human_impact": "The resident has confirmed the exact crossing before submission.",
        "description": (
            "Standing water is affecting the confirmed school crossing at West 43rd "
            "Street and 8th Avenue."
        ),
        "narrative": (
            "A resident confirmed the exact crossing and reports flooding at the curb "
            "ramp. The report should preserve both the drainage concern and the school "
            "crossing pedestrian-safety context."
        ),
    },
    "blocked_crosswalk": {
        "transcript": (
            "The whole crosswalk edge is blocked by water. Students are stepping into "
            "the traffic lane to get around it."
        ),
        "image_summary": (
            "Standing water appears to cover the curb ramp and part of the crosswalk approach."
        ),
        "location": DEMO_LOCATION,
        "human_impact": "The crosswalk approach may be blocked, increasing pedestrian risk.",
        "description": (
            "Flooding may be blocking the crosswalk approach near a school and forcing "
            "students or caregivers into the traffic lane."
        ),
        "narrative": (
            "A resident reports that water is blocking the crosswalk approach near a "
            "school. This should be framed as both a flooding condition and a pedestrian "
            "safety issue because students may be stepping into traffic to pass."
        ),
    },
    "visible_drain_obstruction": {
        "transcript": (
            "The drain at the corner looks clogged with leaves and trash, and water is "
            "pooling into the school crossing."
        ),
        "image_summary": (
            "Standing water is visible near the curb with possible debris around a catch basin."
        ),
        "location": DEMO_LOCATION,
        "human_impact": "A visible catch-basin obstruction may be contributing to the flooding.",
        "description": (
            "A possible clogged catch basin is causing standing water near a school crossing."
        ),
        "narrative": (
            "A resident reports flooding near a school crossing and possible debris around "
            "a catch basin. The report should include the visible obstruction as routing "
            "context while still requiring human review."
        ),
    },
}


def build_report_draft(
    request: ReportDraftRequest,
    context_provider: CivicContextProvider | None = None,
) -> ReportDraft:
    if request.scenario and request.scenario != "flooding_near_school_crossing":
        raise ValueError("Unsupported scenario")

    variant = DEMO_VARIANTS[request.demo_variant or "baseline"]
    transcript = request.transcript or str(variant["transcript"])
    image_summary = request.image_summary or str(variant["image_summary"])
    location = request.location or variant["location"]
    routing = fallback_route_for_category("street_flooding", "near_school_crossing")
    provider = context_provider or Fallback311ContextProvider()
    try:
        civic_context = provider.context_for_report(request)
    except ContextProviderError as exc:
        civic_context = fallback_311_context(f"Open Data context unavailable: {exc}")
    location_confirmed = location.confirmed

    return ReportDraft(
        id=f"draft_{uuid4().hex[:10]}",
        status="draft",
        category="street_flooding",
        subcategory="near_school_crossing",
        title="Flooding blocking a school crossing",
        description=str(variant["description"]),
        narrative=str(variant["narrative"]),
        location=location,
        observed_at=datetime.now(timezone.utc),
        priority=Priority.HIGH,
        routing=routing,
        civic_context=civic_context,
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
                value=str(variant["human_impact"]),
                confidence=0.84 if request.demo_variant == "blocked_crosswalk" else 0.78,
            ),
            InferredContext(
                label="Likely service category",
                value="Street flooding near a school crossing",
                confidence=0.76,
                origin=DataOrigin.SELECTED,
            ),
            InferredContext(
                label="311 historical context",
                value=civic_context.evidence_summary,
                confidence=civic_context.confidence,
            ),
        ],
        human_review=[
            HumanReviewField(
                field="location.confirmed",
                reason=(
                    "Resident confirmed the exact crossing for this draft."
                    if location_confirmed
                    else "Resident must confirm the exact crossing before live submission."
                ),
                current_value=str(location_confirmed),
            ),
            HumanReviewField(
                field="routing",
                reason=(
                    "Routing should be reviewed against live NYC311 service rules and "
                    "historical Open Data context."
                ),
                current_value=routing.service,
            ),
            HumanReviewField(
                field="civic_context",
                reason=(
                    "Historical 311 context informs the draft but does not verify this "
                    "resident's current issue."
                ),
                current_value=civic_context.source,
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
                reason=(
                    "Resident confirmed the exact crossing for this draft."
                    if location_confirmed
                    else "Demo location is approximate until the resident confirms it."
                ),
                confidence=0.92 if location_confirmed else 0.68,
            ),
            UncertaintyItem(
                field="responsible_department",
                reason=(
                    "Sewer, street, and transportation safety routing can overlap; "
                    "historical 311 context is advisory."
                ),
                confidence=max(0.74, civic_context.confidence),
            ),
            UncertaintyItem(
                field="historical_context",
                reason=(
                    "Similar 311 records can guide wording and routing but are not proof "
                    "of the current condition."
                ),
                confidence=civic_context.confidence,
            ),
        ],
        dtpr_chain=build_demo_dtpr_chain(civic_context),
    )
