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
from backend.tools.location_labeler import label_location
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
    "street_trash_bags": {
        "scenario": "trash_bags_on_street",
        "category": "street_cleanliness",
        "subcategory": "trash_bags_on_street",
        "title": "Trash bags obstructing the street or sidewalk",
        "service_context": "Street trash or sanitation obstruction",
        "priority": Priority.MEDIUM,
        "transcript": (
            "There are trash bags piled on the street near my location. People have "
            "to walk around them and some loose garbage is spreading."
        ),
        "image_summary": (
            "Bagged trash and loose refuse appear to be set out along the curb or sidewalk."
        ),
        "location": DEMO_LOCATION,
        "human_impact": (
            "Pedestrians may need to walk around refuse, and loose trash may spread "
            "into the street."
        ),
        "description": (
            "Trash bags and loose refuse are obstructing part of the street or sidewalk "
            "near the resident's current location."
        ),
        "narrative": (
            "A resident reports trash bags and loose refuse near their current location. "
            "The draft should preserve whether the issue is bagged trash, loose garbage, "
            "or a sidewalk obstruction because those details affect sanitation routing."
        ),
        "questions": [
            "Is this the exact location of the trash bags?",
            "Are the bags blocking the sidewalk, curb, bike lane, or street?",
            "Does this look like missed collection, illegal dumping, or regular set-out?",
        ],
        "routing_uncertainty": (
            "Sanitation routing can depend on whether the condition is missed collection, "
            "illegal dumping, set-out timing, or a sidewalk obstruction."
        ),
    },
}


DEFAULT_VARIANT_BY_SCENARIO = {
    "flooding_near_school_crossing": "baseline",
    "trash_bags_on_street": "street_trash_bags",
}


def build_report_draft(
    request: ReportDraftRequest,
    context_provider: CivicContextProvider | None = None,
) -> ReportDraft:
    if request.scenario and request.scenario not in DEFAULT_VARIANT_BY_SCENARIO:
        raise ValueError("Unsupported scenario")

    requested_scenario = request.scenario or "flooding_near_school_crossing"
    variant_key = request.demo_variant or DEFAULT_VARIANT_BY_SCENARIO[requested_scenario]
    variant = DEMO_VARIANTS[variant_key]
    variant_scenario = str(variant.get("scenario", "flooding_near_school_crossing"))
    if request.scenario and request.scenario != variant_scenario:
        raise ValueError("Demo variant does not match scenario")

    category = str(variant.get("category", "street_flooding"))
    subcategory = str(variant.get("subcategory", "near_school_crossing"))
    title = str(variant.get("title", "Flooding blocking a school crossing"))
    service_context = str(
        variant.get("service_context", "Street flooding near a school crossing")
    )
    priority = variant.get("priority", Priority.HIGH)
    transcript = request.transcript or str(variant["transcript"])
    image_summary = (
        request.visual_evidence_summary
        or request.image_summary
        or str(variant["image_summary"])
    )
    location = label_location(request.location or variant["location"])
    routing = fallback_route_for_category(category, subcategory)
    provider = context_provider or Fallback311ContextProvider()
    context_request = request.model_copy(update={"scenario": variant_scenario})
    try:
        civic_context = provider.context_for_report(context_request)
    except ContextProviderError as exc:
        civic_context = fallback_311_context(
            f"Open Data context unavailable: {exc}", variant_scenario
        )
    location_confirmed = location.confirmed

    return ReportDraft(
        id=f"draft_{uuid4().hex[:10]}",
        status="draft",
        category=category,
        subcategory=subcategory,
        title=title,
        description=str(variant["description"]),
        narrative=str(variant["narrative"]),
        location=location,
        observed_at=datetime.now(timezone.utc),
        priority=priority,
        routing=routing,
        civic_context=civic_context,
        collected_inputs=[
            CollectedInput(kind="text", value=transcript),
            *(
                [
                    CollectedInput(
                        kind="text",
                        value=f"Resident claim: {request.resident_claim_summary}",
                    )
                ]
                if request.resident_claim_summary
                else []
            ),
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
            *(
                [
                    InferredContext(
                        label="Accessibility impact",
                        value=request.accessibility_impact,
                        confidence=0.74,
                    )
                ]
                if request.accessibility_impact
                else []
            ),
            *(
                [
                    InferredContext(
                        label="Recurrence",
                        value=request.recurrence,
                        confidence=0.68,
                    )
                ]
                if request.recurrence
                else []
            ),
            *(
                [
                    InferredContext(
                        label="Model category recommendation",
                        value=request.recommended_category,
                        confidence=0.7,
                    )
                ]
                if request.recommended_category
                else []
            ),
            *(
                [
                    InferredContext(
                        label="Model agency recommendation",
                        value=request.recommended_agency,
                        confidence=0.7,
                    )
                ]
                if request.recommended_agency
                else []
            ),
            *(
                [
                    InferredContext(
                        label="Intake slot quality",
                        value=request.slot_quality_summary,
                        confidence=0.78,
                    )
                ]
                if request.slot_quality_summary
                else []
            ),
            InferredContext(
                label="Human impact",
                value=str(variant["human_impact"]),
                confidence=0.84 if request.demo_variant == "blocked_crosswalk" else 0.78,
            ),
            InferredContext(
                label="Likely service category",
                value=service_context,
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
                    "Resident confirmed the exact location for this draft."
                    if location_confirmed
                    else "Resident must confirm the exact location before live submission."
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
            *(
                [
                    HumanReviewField(
                        field="remaining_uncertainty",
                        reason=(
                            "The live intake agent identified uncertainty that should "
                            "remain visible during resident review."
                        ),
                        current_value=request.remaining_uncertainty,
                    )
                ]
                if request.remaining_uncertainty
                else []
            ),
        ],
        evidence=[
            EvidenceItem(kind="text", summary=transcript),
            EvidenceItem(kind="image", summary=image_summary),
            EvidenceItem(kind="location", summary=location.label or "Approximate location"),
        ],
        questions_asked=variant.get(
            "questions",
            [
                "Is this the exact crossing where the flooding is happening?",
                "Is the water actively rising or blocking the full crosswalk?",
                "Is there a visible clogged catch basin or drain?",
            ],
        ),
        uncertainty=[
            UncertaintyItem(
                field="location",
                reason=(
                    "Resident confirmed the exact location for this draft."
                    if location_confirmed
                    else "Phone location is approximate until the resident confirms it."
                ),
                confidence=0.92 if location_confirmed else 0.68,
            ),
            UncertaintyItem(
                field="responsible_department",
                reason=(
                    str(
                        variant.get(
                            "routing_uncertainty",
                            "Sewer, street, and transportation safety routing can overlap; "
                            "historical 311 context is advisory.",
                        )
                    )
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
            *(
                [
                    UncertaintyItem(
                        field="intake_quality",
                        reason=request.remaining_uncertainty,
                        confidence=0.42,
                    )
                ]
                if request.remaining_uncertainty
                else []
            ),
        ],
        dtpr_chain=build_demo_dtpr_chain(civic_context),
    )
