from fastapi.testclient import TestClient

from backend.agents.live_model import LiveCandidate, LiveObservation
from backend.main import _decode_jpeg_frame, create_app
from backend.schemas import CivicContext, ReportDraftRequest
from backend.tools.nyc_311_context import ContextProviderError


class StubContextProvider:
    def context_for_report(self, request: ReportDraftRequest) -> CivicContext:
        return CivicContext(
            source="test 311 context provider",
            dataset="erm2-nwe9",
            query_summary="test matching flood records",
            matched_count=3,
            likely_agencies=["NYC DEP"],
            likely_problem_types=["Sewer"],
            likely_problem_details=["Catch Basin Clogged/Flooding"],
            evidence_summary="Three similar historical records commonly routed to NYC DEP.",
            confidence=0.81,
            used_live_data=True,
        )


class FailingContextProvider:
    def context_for_report(self, request: ReportDraftRequest) -> CivicContext:
        raise ContextProviderError("timeout")


class StubLiveModelAdapter:
    async def detect_candidate(self, observation: LiveObservation) -> LiveCandidate:
        assert "custom adapter" in observation.transcript
        return LiveCandidate(
            scenario="trash_bags_on_street",
            demo_variant="street_trash_bags",
            candidate="Adapter-selected trash report",
            confirmation="Adapter confirmation prompt.",
            followup="Adapter follow-up prompt.",
        )


def test_decode_jpeg_frame_accepts_valid_data_url() -> None:
    frame = _decode_jpeg_frame("data:image/jpeg;base64,/9j/AA==")

    assert frame == b"\xff\xd8\xff\x00"


def test_decode_jpeg_frame_rejects_invalid_base64() -> None:
    try:
        _decode_jpeg_frame("data:image/jpeg;base64,not valid")
    except ValueError as exc:
        assert "base64" in str(exc)
    else:
        raise AssertionError("Expected invalid base64 to be rejected")


def test_decode_jpeg_frame_rejects_non_jpeg_data_url() -> None:
    try:
        _decode_jpeg_frame("data:image/png;base64,/9j/AA==")
    except ValueError as exc:
        assert "JPEG" in str(exc)
    else:
        raise AssertionError("Expected non-JPEG data URL to be rejected")


def test_demo_draft_report_returns_story_routing_and_dtpr_chain() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/report/draft",
        json={"scenario": "flooding_near_school_crossing"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "draft"
    assert payload["category"] == "street_flooding"
    assert payload["subcategory"] == "near_school_crossing"
    assert "children" in payload["narrative"].lower()
    assert payload["routing"]["agency"] == "NYC DEP"
    assert payload["routing"]["source"] == "demo fallback route"
    assert payload["civic_context"]["source"] == "deterministic demo civic context"
    assert payload["civic_context"]["used_live_data"] is False
    assert len(payload["collected_inputs"]) >= 2
    assert len(payload["inferred_context"]) >= 4
    assert len(payload["human_review"]) >= 3
    assert [step["origin"] for step in payload["dtpr_chain"]] == [
        "collected",
        "collected",
        "inferred",
        "inferred",
        "selected",
        "review_required",
    ]


def test_demo_draft_can_use_injected_historical_311_context() -> None:
    client = TestClient(create_app(context_provider=StubContextProvider()))

    response = client.post(
        "/api/report/draft",
        json={"scenario": "flooding_near_school_crossing"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["civic_context"]["source"] == "test 311 context provider"
    assert payload["civic_context"]["matched_count"] == 3
    assert payload["civic_context"]["likely_agencies"] == ["NYC DEP"]
    assert payload["uncertainty"][1]["confidence"] == 0.81
    assert any(
        step["id"] == "civic-open-data-context"
        for step in payload["dtpr_chain"]
    )


def test_demo_draft_falls_back_when_historical_311_context_fails() -> None:
    client = TestClient(create_app(context_provider=FailingContextProvider()))

    response = client.post(
        "/api/report/draft",
        json={"scenario": "flooding_near_school_crossing"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["civic_context"]["used_live_data"] is False
    assert "timeout" in payload["civic_context"]["fallback_reason"]


def test_demo_draft_supports_confirmed_location_variant() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/report/draft",
        json={
            "scenario": "flooding_near_school_crossing",
            "demo_variant": "confirmed_location",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["location"]["confirmed"] is True
    assert payload["human_review"][0]["current_value"] == "True"
    assert payload["uncertainty"][0]["confidence"] == 0.92
    assert "confirmed" in payload["narrative"].lower()


def test_demo_draft_supports_blocked_crosswalk_variant() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/report/draft",
        json={
            "scenario": "flooding_near_school_crossing",
            "demo_variant": "blocked_crosswalk",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "traffic lane" in payload["description"].lower()
    assert any(
        item["label"] == "Human impact" and item["confidence"] == 0.84
        for item in payload["inferred_context"]
    )


def test_demo_draft_supports_street_trash_bags_scenario() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/report/draft",
        json={
            "scenario": "trash_bags_on_street",
            "demo_variant": "street_trash_bags",
            "location": {
                "latitude": 40.7282,
                "longitude": -73.9864,
                "accuracy_meters": 22,
                "confirmed": False,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["category"] == "street_cleanliness"
    assert payload["subcategory"] == "trash_bags_on_street"
    assert payload["priority"] == "medium"
    assert payload["routing"]["agency"] == "NYC DSNY"
    assert "trash" in payload["title"].lower()
    assert "sanitation" in payload["uncertainty"][1]["reason"].lower()
    assert payload["civic_context"]["likely_agencies"] == ["NYC DSNY", "NYC311"]
    assert payload["location"]["borough"] == "Manhattan"


def test_demo_draft_rejects_mismatched_scenario_and_variant() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/report/draft",
        json={
            "scenario": "trash_bags_on_street",
            "demo_variant": "blocked_crosswalk",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Demo variant does not match scenario"


def test_demo_draft_uses_request_provided_location() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/report/draft",
        json={
            "scenario": "flooding_near_school_crossing",
            "location": {
                "label": "Current phone location",
                "latitude": 40.7128,
                "longitude": -74.006,
                "confirmed": False,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["location"]["label"] == "Near City Hall Park, Civic Center, Manhattan"
    assert payload["location"]["latitude"] == 40.7128
    assert payload["location"]["longitude"] == -74.006
    assert payload["location"]["intersection"] == "Broadway and Park Row"
    assert payload["location"]["neighborhood"] == "Civic Center"
    assert payload["location"]["borough"] == "Manhattan"
    assert payload["collected_inputs"][1]["value"] == (
        "Near City Hall Park, Civic Center, Manhattan"
    )
    assert payload["evidence"][2]["summary"] == (
        "Near City Hall Park, Civic Center, Manhattan"
    )


def test_demo_draft_labels_unlabeled_phone_coordinates() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/report/draft",
        json={
            "scenario": "flooding_near_school_crossing",
            "location": {
                "latitude": 40.759,
                "longitude": -73.989,
                "accuracy_meters": 18,
                "confirmed": False,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["location"]["label"] == (
        "W 43rd St and 8th Ave school crossing, Theater District, Manhattan"
    )
    assert payload["location"]["accuracy_meters"] == 18
    assert payload["location"]["source"] == "deterministic demo geocoder"


def test_confirm_report_marks_existing_draft_confirmed() -> None:
    client = TestClient(create_app())
    draft_response = client.post(
        "/api/report/draft",
        json={"scenario": "flooding_near_school_crossing"},
    )
    report_id = draft_response.json()["id"]

    response = client.post(
        "/api/report/confirm",
        json={"report_id": report_id, "accepted": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["report"]["id"] == report_id
    assert payload["report"]["status"] == "confirmed"
    assert payload["message"] == "Report confirmed for demo submission."


def test_update_report_edits_structured_fields_before_confirmation() -> None:
    client = TestClient(create_app())
    draft_response = client.post(
        "/api/report/draft",
        json={"scenario": "flooding_near_school_crossing"},
    )
    report_id = draft_response.json()["id"]

    response = client.patch(
        f"/api/report/{report_id}",
        json={
            "title": "Flooded crosswalk at school pickup",
            "description": "Water covers the curb ramp and students are stepping around it.",
            "location": {
                "label": "W 43rd St and 8th Ave school crossing",
                "latitude": 40.7589,
                "longitude": -73.9891,
                "confirmed": True,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == report_id
    assert payload["title"] == "Flooded crosswalk at school pickup"
    assert payload["description"].startswith("Water covers the curb ramp")
    assert payload["location"]["confirmed"] is True
    assert payload["human_review"][0]["current_value"] == "True"
    assert payload["uncertainty"][0]["confidence"] == 0.92


def test_update_report_returns_404_for_unknown_report() -> None:
    client = TestClient(create_app())

    response = client.patch(
        "/api/report/missing",
        json={"title": "Updated title"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Report not found"


def test_model_context_packet_exposes_prompt_ready_report_context() -> None:
    client = TestClient(create_app(context_provider=StubContextProvider()))
    draft_response = client.post(
        "/api/report/draft",
        json={"scenario": "flooding_near_school_crossing"},
    )
    report_id = draft_response.json()["id"]

    response = client.get(f"/api/report/{report_id}/model-context")

    assert response.status_code == 200
    payload = response.json()
    assert payload["report_id"] == report_id
    assert payload["task"] == "draft_311_service_request"
    assert payload["civic_evidence"]["source"] == "test 311 context provider"
    assert payload["routing_context"]["agency"] == "NYC DEP"
    assert any("historical 311 records" in item for item in payload["guardrails"])
    assert "civic-open-data-context" in payload["dtpr_disclosures"]


def test_model_context_packet_returns_404_for_unknown_report() -> None:
    client = TestClient(create_app())

    response = client.get("/api/report/missing/model-context")

    assert response.status_code == 404
    assert response.json()["detail"] == "Report not found"


def test_live_websocket_detects_candidate_and_requires_location_confirmation() -> None:
    client = TestClient(create_app())

    with client.websocket_connect("/ws/live") as websocket:
        websocket.send_json({"type": "start", "payload": {}})
        started = websocket.receive_json()
        assert started["type"] == "session_started"

        websocket.send_json(
            {
                "type": "observation",
                "payload": {
                    "transcript": (
                        "There are trash bags blocking the sidewalk near my location."
                    ),
                    "location": {
                        "latitude": 40.7282,
                        "longitude": -73.9864,
                        "accuracy_meters": 22,
                        "confirmed": False,
                    },
                },
            }
        )
        candidate = websocket.receive_json()
        assert candidate["type"] == "candidate_detected"
        assert candidate["payload"]["scenario"] == "trash_bags_on_street"
        assert candidate["payload"]["demo_variant"] == "street_trash_bags"

        websocket.send_json({"type": "intent_confirmed", "payload": {}})
        followup = websocket.receive_json()
        assert followup["type"] == "followup_required"
        assert followup["payload"]["requires_location_confirmation"] is True

        websocket.send_json({"type": "create_draft", "payload": {}})
        blocked = websocket.receive_json()
        assert blocked["type"] == "location_confirmation_required"


def test_live_websocket_creates_reviewable_draft_after_location_confirmation() -> None:
    client = TestClient(create_app())

    with client.websocket_connect("/ws/live") as websocket:
        websocket.send_json(
            {
                "type": "start",
                "payload": {
                    "location": {
                        "latitude": 40.759,
                        "longitude": -73.989,
                        "accuracy_meters": 18,
                        "confirmed": False,
                    }
                },
            }
        )
        websocket.receive_json()
        websocket.send_json(
            {
                "type": "observation",
                "payload": {
                    "transcript": "The drain is clogged and water is blocking the crosswalk.",
                },
            }
        )
        candidate = websocket.receive_json()
        assert candidate["payload"]["demo_variant"] == "visible_drain_obstruction"

        websocket.send_json({"type": "intent_confirmed", "payload": {}})
        websocket.receive_json()
        websocket.send_json({"type": "location_confirmed", "payload": {}})
        location_confirmed = websocket.receive_json()
        assert location_confirmed["payload"]["requires_location_confirmation"] is False

        websocket.send_json({"type": "create_draft", "payload": {}})
        draft_ready = websocket.receive_json()
        assert draft_ready["type"] == "draft_ready"
        report = draft_ready["payload"]["report"]
        assert report["category"] == "street_flooding"
        assert report["subcategory"] == "near_school_crossing"
        assert report["location"]["confirmed"] is True
        assert report["status"] == "draft"

        context_response = client.get(f"/api/report/{report['id']}/model-context")
        assert context_response.status_code == 200


def test_live_websocket_uses_injected_model_adapter() -> None:
    client = TestClient(create_app(live_model_adapter=StubLiveModelAdapter()))

    with client.websocket_connect("/ws/live") as websocket:
        websocket.send_json({"type": "start", "payload": {}})
        websocket.receive_json()
        websocket.send_json(
            {
                "type": "observation",
                "payload": {"transcript": "custom adapter should classify this"},
            }
        )

        candidate = websocket.receive_json()
        assert candidate["type"] == "candidate_detected"
        assert candidate["message"] == "Adapter confirmation prompt."
        assert candidate["payload"]["candidate"] == "Adapter-selected trash report"
        assert candidate["payload"]["scenario"] == "trash_bags_on_street"


def test_live_classify_endpoint_uses_injected_model_adapter() -> None:
    client = TestClient(create_app(live_model_adapter=StubLiveModelAdapter()))

    response = client.post(
        "/api/live/classify",
        json={
            "transcript": "custom adapter should classify this",
            "image_summary": "Still frame captured from the resident camera.",
            "image_frame": "data:image/jpeg;base64,/9j/",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"] == "trash_bags_on_street"
    assert payload["demo_variant"] == "street_trash_bags"
    assert payload["candidate"] == "Adapter-selected trash report"
    assert payload["model_source"] == "deterministic"


def test_confirm_report_returns_404_for_unknown_report() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/report/confirm",
        json={"report_id": "missing"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Report not found"
