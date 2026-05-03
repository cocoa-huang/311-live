from fastapi.testclient import TestClient

from backend.main import create_app
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
    assert payload["location"]["label"] == "Current phone location"
    assert payload["location"]["latitude"] == 40.7128
    assert payload["location"]["longitude"] == -74.006
    assert payload["collected_inputs"][1]["value"] == "Current phone location"
    assert payload["evidence"][2]["summary"] == "Current phone location"


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


def test_confirm_report_returns_404_for_unknown_report() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/report/confirm",
        json={"report_id": "missing"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Report not found"
