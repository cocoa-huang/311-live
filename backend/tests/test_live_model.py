import asyncio

import pytest

from backend.agents.live_model import (
    candidate_from_model_text,
    DeterministicLiveModelAdapter,
    GeminiVertexLiveModelAdapter,
    image_bytes_from_data_url,
    LiveModelConfigurationError,
    LiveObservation,
    live_model_adapter_from_settings,
)
from backend.settings import Settings


def test_deterministic_live_model_detects_trash_report_path() -> None:
    adapter = DeterministicLiveModelAdapter()

    candidate = asyncio.run(
        adapter.detect_candidate(
            LiveObservation(transcript="Trash bags are blocking the sidewalk here.")
        )
    )

    assert candidate.scenario == "trash_bags_on_street"
    assert candidate.demo_variant == "street_trash_bags"
    assert "trash" in candidate.candidate.lower()
    assert candidate.source == "deterministic"


def test_live_model_factory_defaults_to_deterministic_adapter() -> None:
    adapter = live_model_adapter_from_settings(Settings())

    assert isinstance(adapter, DeterministicLiveModelAdapter)


def test_live_model_factory_requires_vertex_configuration() -> None:
    settings = Settings(live_model_mode="vertex")

    with pytest.raises(LiveModelConfigurationError) as exc:
        live_model_adapter_from_settings(settings)

    assert "GOOGLE_CLOUD_PROJECT" in str(exc.value)
    assert "GEMINI_LIVE_MODEL" in str(exc.value)


def test_live_model_factory_builds_vertex_adapter_when_configured() -> None:
    settings = Settings(
        live_model_mode="vertex",
        google_cloud_project="test-project",
        google_cloud_location="us-central1",
        gemini_text_location="global",
        gemini_text_model="gemini-2.5-flash",
        gemini_live_location="us-central1",
        gemini_live_model="gemini-live-2.5-flash-preview-native-audio-09-2025",
    )

    adapter = live_model_adapter_from_settings(settings)

    assert isinstance(adapter, GeminiVertexLiveModelAdapter)
    assert adapter.connection_metadata() == {
        "provider": "vertex-ai",
        "project": "test-project",
        "text_location": "global",
        "text_model": "gemini-2.5-flash",
        "live_location": "us-central1",
        "live_model": "gemini-live-2.5-flash-preview-native-audio-09-2025",
        "status": "configured",
    }


def test_candidate_from_model_text_parses_supported_json() -> None:
    candidate = candidate_from_model_text(
        """
        ```json
        {
          "scenario": "flooding_near_school_crossing",
          "demo_variant": "visible_drain_obstruction",
          "candidate": "Possible clogged drain",
          "confirmation": "I see possible drain obstruction. Is that right?",
          "followup": "Is the catch basin covered by debris?"
        }
        ```
        """
    )

    assert candidate.scenario == "flooding_near_school_crossing"
    assert candidate.demo_variant == "visible_drain_obstruction"
    assert candidate.followup == "Is the catch basin covered by debris?"
    assert candidate.source == "vertex-gemini-text"


def test_candidate_from_model_text_rejects_unsupported_variant() -> None:
    with pytest.raises(ValueError):
        candidate_from_model_text(
            '{"scenario": "noise", "demo_variant": "loud_music"}'
        )


def test_candidate_from_model_text_normalizes_model_path_response() -> None:
    candidate = candidate_from_model_text(
        """
        {
          "scenario": "Trash bags on street",
          "demo_variant": "Trash bags blocking sidewalk",
          "candidate": "trash_bags_on_street/street_trash_bags",
          "confirmation": "Confirm the exact location.",
          "followup": "Are the bags blocking the sidewalk?"
        }
        """
    )

    assert candidate.scenario == "trash_bags_on_street"
    assert candidate.demo_variant == "street_trash_bags"
    assert candidate.candidate == "Trash bags on the street or sidewalk"


def test_image_bytes_from_data_url_accepts_jpeg_data_url() -> None:
    value = image_bytes_from_data_url("data:image/jpeg;base64,/9j/")

    assert value == b"\xff\xd8\xff"


def test_image_bytes_from_data_url_rejects_non_image_payload() -> None:
    with pytest.raises(ValueError):
        image_bytes_from_data_url("data:text/plain;base64,SGVsbG8=")
