from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import BaseModel, Field

from backend.agents.live_model import (
    DeterministicLiveModelAdapter,
    LiveModelAdapter,
    LiveObservation,
    candidate_for_variant,
)
from backend.agents.report_builder import build_report_draft
from backend.schemas import IntakeState, Location, ReportDraft, ReportDraftRequest
from backend.tools.nyc_311_context import CivicContextProvider


LiveEventType = Literal[
    "session_started",
    "candidate_detected",
    "followup_required",
    "location_confirmation_required",
    "draft_ready",
    "error",
]


class LiveEvent(BaseModel):
    type: LiveEventType
    session_id: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)


ReportScenarioName = Literal["flooding_near_school_crossing", "trash_bags_on_street"]
ReportDemoVariantName = Literal[
    "baseline",
    "confirmed_location",
    "blocked_crosswalk",
    "visible_drain_obstruction",
    "street_trash_bags",
]


class LiveSession:
    """Stateful live intake orchestrator with a replaceable model adapter."""

    def __init__(
        self,
        context_provider: CivicContextProvider | None = None,
        model_adapter: LiveModelAdapter | None = None,
    ) -> None:
        self.session_id = f"live_{uuid4().hex[:10]}"
        self.context_provider = context_provider
        self.model_adapter = model_adapter or DeterministicLiveModelAdapter()
        self.transcript: str | None = None
        self.image_summary: str | None = None
        self.location: Location | None = None
        self.scenario = "flooding_near_school_crossing"
        self.demo_variant = "baseline"
        self.candidate_confirmed = False
        self.location_confirmed = False
        self.intake_state = IntakeState()

    def start(self, payload: dict[str, Any]) -> LiveEvent:
        self.location = _location_from_payload(payload.get("location"))
        if self.location and self.location.confirmed:
            self.location_confirmed = True
            self.intake_state = self.intake_state.model_copy(
                update={"location_confirmed": True}
            )
        return self._event(
            "session_started",
            "Live reporting session is ready.",
            {
                "requires": ["transcript", "location_confirmation"],
                "media": {
                    "audio_input": "browser transcript bridge",
                    "video_input": "browser camera preview",
                    "future_live_model": "Gemini Live through Vertex AI",
                },
                "intake_state": self.intake_state.model_dump(mode="json"),
            },
        )

    async def observe(self, payload: dict[str, Any]) -> LiveEvent:
        transcript = str(payload.get("transcript") or "").strip()
        if not transcript:
            return self._event("error", "Transcript is required before candidate detection.")

        self.transcript = transcript
        self.image_summary = str(payload.get("image_summary") or "").strip() or None
        self.location = _location_from_payload(payload.get("location")) or self.location
        if self.location and self.location.confirmed:
            self.location_confirmed = True

        candidate = await self.model_adapter.detect_candidate(
            LiveObservation(transcript=transcript, image_summary=self.image_summary)
        )
        self.scenario = candidate.scenario
        self.demo_variant = candidate.demo_variant
        self.intake_state = candidate.intake_state.model_copy(
            update={"location_confirmed": self.location_confirmed}
        )
        return self._event(
            "candidate_detected",
            candidate.confirmation,
            {
                "scenario": self.scenario,
                "demo_variant": self.demo_variant,
                "candidate": candidate.candidate,
                "confirmation": candidate.confirmation,
                "followup": candidate.followup,
                "location_confirmed": self.location_confirmed,
                "model_source": candidate.source,
                "fallback_reason": candidate.fallback_reason,
                "intake_state": self.intake_state.model_dump(mode="json"),
            },
        )

    def confirm_intent(self) -> LiveEvent:
        self.candidate_confirmed = True
        self.intake_state = self.intake_state.model_copy(
            update={"resident_confirmed_intent": True}
        )
        candidate = candidate_for_variant(self.demo_variant)
        return self._event(
            "followup_required",
            candidate["followup"],
            {
                "requires_location_confirmation": not self.location_confirmed,
                "location": self.location.model_dump() if self.location else None,
                "intake_state": self.intake_state.model_dump(mode="json"),
            },
        )

    def confirm_location(self, payload: dict[str, Any]) -> LiveEvent:
        location = _location_from_payload(payload.get("location"))
        if location is not None:
            self.location = location.model_copy(update={"confirmed": True})
        elif self.location is not None:
            self.location = self.location.model_copy(update={"confirmed": True})
        else:
            self.location = Location(
                label="Resident-confirmed current reporting location",
                source="live agent confirmation",
                confirmed=True,
            )
        self.location_confirmed = True
        self.intake_state = self.intake_state.model_copy(
            update={"location_confirmed": True}
        )
        return self._event(
            "followup_required",
            "Location confirmed. I can create the draft for resident review.",
            {
                "requires_location_confirmation": False,
                "intake_state": self.intake_state.model_dump(mode="json"),
            },
        )

    def create_draft(self) -> LiveEvent:
        if not self.candidate_confirmed:
            return self._event("error", "Confirm the candidate issue before drafting.")
        if not self.location_confirmed:
            return self._event(
                "location_confirmation_required",
                "Confirm the exact location before I create the draft.",
                {"location": self.location.model_dump() if self.location else None},
            )

        request = ReportDraftRequest(
            scenario=cast(ReportScenarioName, self.scenario),
            demo_variant=cast(ReportDemoVariantName, self.demo_variant),
            transcript=self.transcript,
            image_summary=self.image_summary,
            location=self.location,
            candidate_provenance=self.intake_state.candidate_provenance,
        )
        draft = build_report_draft(request, self.context_provider)
        self.intake_state = self.intake_state.model_copy(update={"draft_ready": True})
        return self._draft_event(draft)

    def _draft_event(self, draft: ReportDraft) -> LiveEvent:
        return self._event(
            "draft_ready",
            "Draft report is ready for resident review.",
            {
                "report": draft.model_dump(mode="json"),
                "intake_state": self.intake_state.model_dump(mode="json"),
            },
        )

    def _event(
        self, event_type: LiveEventType, message: str, payload: dict[str, Any] | None = None
    ) -> LiveEvent:
        return LiveEvent(
            type=event_type,
            session_id=self.session_id,
            message=message,
            payload=payload or {},
        )


def _location_from_payload(value: Any) -> Location | None:
    if value is None:
        return None
    if isinstance(value, Location):
        return value
    if isinstance(value, dict):
        return Location.model_validate(value)
    return None
