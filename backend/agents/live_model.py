import base64
import json
from typing import Any, Protocol

from pydantic import BaseModel

from backend.settings import Settings


class LiveModelConfigurationError(ValueError):
    """Raised when an explicitly selected live model mode is not configured."""


class LiveObservation(BaseModel):
    transcript: str
    image_summary: str | None = None
    image_frame: str | None = None


class LiveCandidate(BaseModel):
    scenario: str
    demo_variant: str
    candidate: str
    confirmation: str
    followup: str
    source: str = "deterministic"
    fallback_reason: str | None = None


class LiveModelAdapter(Protocol):
    """Adapter boundary for deterministic, ADK, or Gemini Live-backed agents."""

    async def detect_candidate(self, observation: LiveObservation) -> LiveCandidate:
        """Interpret the resident's live observation and return a candidate report path."""


class DeterministicLiveModelAdapter:
    """Credential-free adapter for tests, local demos, and fallback operation."""

    async def detect_candidate(self, observation: LiveObservation) -> LiveCandidate:
        scenario, demo_variant = infer_live_report_path(observation.transcript)
        candidate = candidate_for_variant(demo_variant)
        return LiveCandidate(
            scenario=scenario,
            demo_variant=demo_variant,
            candidate=candidate["candidate"],
            confirmation=candidate["confirmation"],
            followup=candidate["followup"],
            source="deterministic",
        )


class GeminiVertexLiveModelAdapter:
    """Vertex/Gemini adapter behind the stable live-agent contract.

    Candidate classification uses a text/multimodal Gemini model. The native-audio
    Live model is tracked separately for the upcoming spoken response path.
    """

    def __init__(
        self,
        project: str,
        text_location: str,
        text_model: str,
        live_location: str,
        live_model: str,
    ) -> None:
        self.project = project
        self.text_location = text_location
        self.text_model = text_model
        self.live_location = live_location
        self.live_model = live_model
        self._deterministic_fallback = DeterministicLiveModelAdapter()

    async def detect_candidate(self, observation: LiveObservation) -> LiveCandidate:
        prompt = build_candidate_prompt(observation)
        try:
            response_text = await self._generate_text_response(prompt, observation)
            return candidate_from_model_text(response_text, source="vertex-gemini-text")
        except Exception as exc:
            fallback = await self._deterministic_fallback.detect_candidate(observation)
            return fallback.model_copy(
                update={
                    "source": "deterministic-fallback",
                    "fallback_reason": str(exc),
                }
            )

    def connection_metadata(self) -> dict[str, str]:
        return {
            "provider": "vertex-ai",
            "project": self.project,
            "text_location": self.text_location,
            "text_model": self.text_model,
            "live_location": self.live_location,
            "live_model": self.live_model,
            "status": "configured",
        }

    async def _generate_text_response(
        self, prompt: str, observation: LiveObservation
    ) -> str:
        try:
            from google import genai
            from google.genai.types import (
                Content,
                GenerateContentConfig,
                HttpOptions,
                Part,
            )
        except ImportError as exc:
            raise LiveModelConfigurationError(
                "google-genai is required for LIVE_MODEL_MODE=vertex"
            ) from exc

        client = genai.Client(
            vertexai=True,
            project=self.project,
            location=self.text_location,
            http_options=HttpOptions(api_version="v1beta1"),
        )
        parts = [Part.from_text(text=prompt)]
        image_bytes = image_bytes_from_data_url(observation.image_frame)
        if image_bytes is not None:
            parts.append(Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

        response = await client.aio.models.generate_content(
            model=self.text_model,
            contents=Content(role="user", parts=parts),
            config=GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        return response.text or ""


def live_model_adapter_from_settings(settings: Settings) -> LiveModelAdapter:
    mode = settings.live_model_mode.strip().lower()
    if mode in {"", "deterministic", "fallback", "local"}:
        return DeterministicLiveModelAdapter()
    if mode in {"vertex", "gemini", "gemini-live"}:
        missing = []
        if not settings.google_cloud_project:
            missing.append("GOOGLE_CLOUD_PROJECT")
        if not settings.gemini_live_model:
            missing.append("GEMINI_LIVE_MODEL")
        if missing:
            raise LiveModelConfigurationError(
                "LIVE_MODEL_MODE=vertex requires " + ", ".join(missing)
            )
        return GeminiVertexLiveModelAdapter(
            project=settings.google_cloud_project,
            text_location=settings.gemini_text_location,
            text_model=settings.gemini_text_model,
            live_location=settings.gemini_live_location,
            live_model=settings.gemini_live_model,
        )
    raise LiveModelConfigurationError(
        "Unsupported LIVE_MODEL_MODE. Use deterministic or vertex."
    )


def build_candidate_prompt(observation: LiveObservation) -> str:
    image_context = observation.image_summary or "No frame summary is available yet."
    return (
        "You are a civic 311 live intake agent. Classify the resident observation "
        "into exactly one supported report path. Return only compact JSON with keys "
        "scenario, demo_variant, candidate, confirmation, followup. Supported paths: "
        "1) flooding_near_school_crossing/baseline, "
        "2) flooding_near_school_crossing/blocked_crosswalk, "
        "3) flooding_near_school_crossing/visible_drain_obstruction, "
        "4) trash_bags_on_street/street_trash_bags. "
        "Do not claim certainty from historical data or visual context that is not provided. "
        f"Resident transcript: {observation.transcript}\n"
        f"Frame summary: {image_context}"
    )


def image_bytes_from_data_url(value: str | None) -> bytes | None:
    if not value:
        return None
    prefix = "data:image/"
    if not value.startswith(prefix):
        raise ValueError("image_frame must be an image data URL")
    header, encoded = value.split(",", 1)
    if "jpeg" not in header and "jpg" not in header:
        raise ValueError("image_frame must be JPEG")
    return base64.b64decode(encoded, validate=True)


def candidate_from_model_text(text: str, source: str = "vertex-gemini-text") -> LiveCandidate:
    payload = _json_object_from_text(text)
    scenario = _normalize_scenario(str(payload.get("scenario") or ""))
    demo_variant = _normalize_demo_variant(str(payload.get("demo_variant") or ""))
    candidate_text = str(payload.get("candidate") or "")
    if not scenario or not demo_variant:
        path_scenario, path_variant = _path_from_text(candidate_text)
        scenario = scenario or path_scenario
        demo_variant = demo_variant or path_variant
    if demo_variant not in {
        "baseline",
        "blocked_crosswalk",
        "visible_drain_obstruction",
        "street_trash_bags",
    }:
        raise ValueError("Model returned an unsupported demo_variant")
    if scenario not in {"flooding_near_school_crossing", "trash_bags_on_street"}:
        raise ValueError("Model returned an unsupported scenario")

    fallback = candidate_for_variant(demo_variant)
    return LiveCandidate(
        scenario=scenario,
        demo_variant=demo_variant,
        candidate=candidate_text if "/" not in candidate_text else fallback["candidate"],
        confirmation=str(payload.get("confirmation") or fallback["confirmation"]),
        followup=str(payload.get("followup") or fallback["followup"]),
        source=source,
    )


def _json_object_from_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Model response did not include a JSON object")
    value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Model JSON response must be an object")
    return value


def _normalize_scenario(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    if "trash" in normalized:
        return "trash_bags_on_street"
    if "flood" in normalized or "crosswalk" in normalized or "drain" in normalized:
        return "flooding_near_school_crossing"
    return normalized


def _normalize_demo_variant(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    if "trash" in normalized or "garbage" in normalized or "refuse" in normalized:
        return "street_trash_bags"
    if "drain" in normalized or "catch_basin" in normalized or "clog" in normalized:
        return "visible_drain_obstruction"
    if "blocked" in normalized or "crosswalk" in normalized:
        return "blocked_crosswalk"
    return normalized


def _path_from_text(value: str) -> tuple[str, str]:
    normalized = value.strip().lower()
    if "/" in normalized:
        scenario, demo_variant = normalized.split("/", 1)
        return _normalize_scenario(scenario), _normalize_demo_variant(demo_variant)
    return _normalize_scenario(normalized), _normalize_demo_variant(normalized)


def infer_live_report_path(transcript: str) -> tuple[str, str]:
    normalized = transcript.lower()
    if any(
        word in normalized
        for word in ["trash", "garbage", "refuse", "rubbish", "bags", "bagged", "dumping"]
    ):
        return "trash_bags_on_street", "street_trash_bags"
    if any(word in normalized for word in ["drain", "catch basin", "sewer", "clogged"]):
        return "flooding_near_school_crossing", "visible_drain_obstruction"
    if any(word in normalized for word in ["crosswalk", "blocked", "blocking", "traffic lane"]):
        return "flooding_near_school_crossing", "blocked_crosswalk"
    return "flooding_near_school_crossing", "baseline"


def candidate_for_variant(demo_variant: str) -> dict[str, str]:
    candidates = {
        "baseline": {
            "candidate": "Flooding near a school crossing",
            "confirmation": (
                "I see standing water near a school crossing. Is that what you want to report?"
            ),
            "followup": "Can you confirm the exact crossing before I draft the report?",
        },
        "confirmed_location": {
            "candidate": "Flooding at a confirmed school crossing",
            "confirmation": (
                "I see flooding at the confirmed crossing. Should I prepare this as a 311 report?"
            ),
            "followup": "Is the water actively rising or blocking the curb ramp?",
        },
        "blocked_crosswalk": {
            "candidate": "Crosswalk access blocked by standing water",
            "confirmation": (
                "It looks like water may be forcing pedestrians toward traffic. Is that the issue?"
            ),
            "followup": "Is the crosswalk fully blocked or still partly passable?",
        },
        "visible_drain_obstruction": {
            "candidate": "Possible clogged catch basin causing flooding",
            "confirmation": (
                "I see flooding and possible debris near a drain. Is that what you want to report?"
            ),
            "followup": "Is the drain covered by leaves, trash, or another obstruction?",
        },
        "street_trash_bags": {
            "candidate": "Trash bags on the street or sidewalk",
            "confirmation": (
                "I see bagged trash or loose refuse near your current location. "
                "Is that what you want to report?"
            ),
            "followup": "Are the bags blocking the sidewalk, curb, bike lane, or street?",
        },
    }
    return candidates.get(demo_variant, candidates["baseline"])
