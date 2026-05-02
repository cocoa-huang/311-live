from fastapi.testclient import TestClient

from backend.main import create_app


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
    assert len(payload["collected_inputs"]) >= 2
    assert len(payload["inferred_context"]) >= 3
    assert len(payload["human_review"]) >= 2
    assert [step["origin"] for step in payload["dtpr_chain"]] == [
        "collected",
        "collected",
        "inferred",
        "selected",
        "review_required",
    ]


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


def test_confirm_report_returns_404_for_unknown_report() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/report/confirm",
        json={"report_id": "missing"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Report not found"
