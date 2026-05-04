from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx

from backend.schemas import CivicContext, Location, ReportDraftRequest
from backend.settings import Settings


class ContextProviderError(RuntimeError):
    pass


class CivicContextProvider(Protocol):
    def context_for_report(self, request: ReportDraftRequest) -> CivicContext:
        pass


class Fallback311ContextProvider:
    def context_for_report(self, request: ReportDraftRequest) -> CivicContext:
        return fallback_311_context(
            "live Open Data context disabled", request.scenario
        )


class Socrata311ContextProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def context_for_report(self, request: ReportDraftRequest) -> CivicContext:
        location = request.location
        if request.scenario == "flooding_near_school_crossing" and location is None:
            location = Location(latitude=40.7589, longitude=-73.9891)

        params = self._build_params(location, request.scenario)
        headers = {}
        if self._settings.socrata_app_token:
            headers["X-App-Token"] = self._settings.socrata_app_token

        try:
            response = httpx.get(
                self._resource_url,
                params=params,
                headers=headers,
                timeout=self._settings.socrata_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ContextProviderError(str(exc)) from exc

        rows = response.json()
        if not isinstance(rows, list):
            raise ContextProviderError("Socrata returned an unexpected response shape")

        return summarize_311_rows(
            rows=rows,
            source="NYC Open Data Socrata API",
            dataset=self._settings.socrata_service_requests_dataset,
            query_summary=_query_summary_for_scenario(request.scenario),
            used_live_data=True,
        )

    @property
    def _resource_url(self) -> str:
        domain = self._settings.socrata_domain.removeprefix("https://")
        return (
            f"https://{domain}/resource/"
            f"{self._settings.socrata_service_requests_dataset}.json"
        )

    def _build_params(
        self, location: Location | None, scenario: str | None
    ) -> dict[str, str | int]:
        since = datetime.now(timezone.utc) - timedelta(days=365)
        terms = _terms_for_scenario(scenario)
        where_parts = [f"created_date >= '{since.date().isoformat()}T00:00:00'"]

        if location and location.latitude is not None and location.longitude is not None:
            lat = location.latitude
            lon = location.longitude
            where_parts.append(
                f"latitude between {lat - 0.03:.6f} and {lat + 0.03:.6f}"
            )
            where_parts.append(
                f"longitude between {lon - 0.03:.6f} and {lon + 0.03:.6f}"
            )

        where_parts.append(f"({' OR '.join(terms)})")

        return {
            "$select": (
                "created_date,agency,complaint_type,descriptor,status,"
                "borough,incident_zip,latitude,longitude"
            ),
            "$where": " AND ".join(where_parts),
            "$order": "created_date DESC",
            "$limit": 25,
        }


def provider_from_settings(settings: Settings) -> CivicContextProvider:
    if settings.civic_context_mode.lower() == "live":
        return Socrata311ContextProvider(settings)
    return Fallback311ContextProvider()


def fallback_311_context(reason: str, scenario: str | None = None) -> CivicContext:
    if scenario == "trash_bags_on_street":
        return CivicContext(
            source="deterministic demo civic context",
            dataset="NYC Open Data 311 Service Requests 2020-present reference",
            query_summary="fallback context for street trash, missed collection, and sanitation obstruction reports",
            matched_count=0,
            likely_agencies=["NYC DSNY", "NYC311"],
            likely_problem_types=[
                "Dirty Condition",
                "Missed Collection",
                "Sanitation Condition",
            ],
            likely_problem_details=[
                "Trash bags or loose refuse on the sidewalk or curb",
                "Possible missed collection or set-out timing issue",
            ],
            evidence_summary=(
                "Historical 311 patterns are represented by a deterministic fallback: "
                "street trash and bagged refuse conditions commonly route toward DSNY, "
                "while sidewalk blockage and exact location should remain explicit for "
                "human review."
            ),
            confidence=0.56,
            used_live_data=False,
            fallback_reason=reason,
        )

    return CivicContext(
        source="deterministic demo civic context",
        dataset="NYC Open Data 311 Service Requests 2020-present reference",
        query_summary="fallback context for flooding near a school crossing",
        matched_count=0,
        likely_agencies=["NYC DEP", "NYC DOT", "NYC311"],
        likely_problem_types=["Sewer", "Street Flooding", "Street Condition"],
        likely_problem_details=[
            "Catch basin or sewer flooding",
            "Standing water affecting pedestrian access",
        ],
        evidence_summary=(
            "Historical 311 patterns are represented by a deterministic fallback: "
            "street flooding and catch-basin issues commonly route toward DEP, while "
            "pedestrian access near a school should remain explicit for human review."
        ),
        confidence=0.58,
        used_live_data=False,
        fallback_reason=reason,
    )


def summarize_311_rows(
    rows: list[dict[str, object]],
    source: str,
    dataset: str,
    query_summary: str,
    used_live_data: bool,
) -> CivicContext:
    if not rows:
        return fallback_311_context("Open Data query returned no matching rows")

    agencies = _top_values(rows, "agency")
    problem_types = _top_values(rows, "complaint_type")
    problem_details = _top_values(rows, "descriptor")
    confidence = min(0.86, 0.52 + min(len(rows), 25) * 0.012)

    agency_text = ", ".join(agencies) if agencies else "no dominant agency"
    problem_text = ", ".join(problem_types) if problem_types else "similar issues"
    evidence_summary = (
        f"Found {len(rows)} recent similar 311 records. Common agencies: "
        f"{agency_text}. Common problem types: {problem_text}. These records can "
        "inform routing and wording, but they do not verify the resident's current issue."
    )

    return CivicContext(
        source=source,
        dataset=dataset,
        query_summary=query_summary,
        matched_count=len(rows),
        likely_agencies=agencies,
        likely_problem_types=problem_types,
        likely_problem_details=problem_details,
        evidence_summary=evidence_summary,
        confidence=confidence,
        used_live_data=used_live_data,
    )


def _top_values(rows: list[dict[str, object]], field: str) -> list[str]:
    values = [
        str(row[field]).strip()
        for row in rows
        if row.get(field) not in (None, "")
    ]
    return [value for value, _count in Counter(values).most_common(3)]


def _terms_for_scenario(scenario: str | None) -> list[str]:
    if scenario == "trash_bags_on_street":
        return [
            "complaint_type like '%Dirty%'",
            "complaint_type like '%Sanitation%'",
            "complaint_type like '%Missed Collection%'",
            "complaint_type like '%Derelict%'",
            "descriptor like '%Trash%'",
            "descriptor like '%Garbage%'",
            "descriptor like '%Refuse%'",
            "descriptor like '%Sidewalk%'",
        ]

    return [
        "complaint_type like '%Flood%'",
        "complaint_type like '%Sewer%'",
        "complaint_type like '%Catch Basin%'",
        "descriptor like '%Flood%'",
        "descriptor like '%Catch Basin%'",
        "descriptor like '%Crosswalk%'",
        "descriptor like '%School%'",
    ]


def _query_summary_for_scenario(scenario: str | None) -> str:
    if scenario == "trash_bags_on_street":
        return (
            "recent similar 311 requests for dirty conditions, sanitation, "
            "missed collection, trash, garbage, refuse, and sidewalk language"
        )
    return (
        "recent similar 311 requests for flooding, sewer, catch basin, "
        "crosswalk, and school-safety language"
    )
