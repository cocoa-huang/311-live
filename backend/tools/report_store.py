from typing import Dict, Optional

from backend.schemas import (
    HumanReviewField,
    ReportDraft,
    ReportStatus,
    ReportUpdateRequest,
    UncertaintyItem,
)


class InMemoryReportStore:
    def __init__(self) -> None:
        self._reports: Dict[str, ReportDraft] = {}

    def save(self, report: ReportDraft) -> ReportDraft:
        self._reports[report.id] = report
        return report

    def get(self, report_id: str) -> Optional[ReportDraft]:
        return self._reports.get(report_id)

    def confirm(
        self, report_id: str, correction: Optional[str] = None
    ) -> Optional[ReportDraft]:
        report = self.get(report_id)
        if report is None:
            return None

        updated = report.model_copy(
            update={
                "status": ReportStatus.CONFIRMED,
                "description": (
                    f"{report.description}\n\nResident correction: {correction}"
                    if correction
                    else report.description
                ),
            }
        )
        self._reports[report_id] = updated
        return updated

    def update(
        self, report_id: str, request: ReportUpdateRequest
    ) -> Optional[ReportDraft]:
        report = self.get(report_id)
        if report is None:
            return None

        changes = {
            field_name: getattr(request, field_name)
            for field_name in request.model_fields_set
        }
        if not changes:
            return report

        updated = self._refresh_review_state(report.model_copy(update=changes))
        self._reports[report_id] = updated
        return updated

    def _refresh_review_state(self, report: ReportDraft) -> ReportDraft:
        human_review = [
            self._refresh_human_review_field(item, report)
            for item in report.human_review
        ]
        uncertainty = [
            self._refresh_uncertainty_item(item, report)
            for item in report.uncertainty
        ]
        return report.model_copy(
            update={"human_review": human_review, "uncertainty": uncertainty}
        )

    def _refresh_human_review_field(
        self, item: HumanReviewField, report: ReportDraft
    ) -> HumanReviewField:
        if item.field != "location.confirmed":
            return item

        return item.model_copy(
            update={
                "reason": (
                    "Resident confirmed the exact crossing for this draft."
                    if report.location.confirmed
                    else "Resident must confirm the exact crossing before live submission."
                ),
                "current_value": str(report.location.confirmed),
            }
        )

    def _refresh_uncertainty_item(
        self, item: UncertaintyItem, report: ReportDraft
    ) -> UncertaintyItem:
        if item.field != "location":
            return item

        return item.model_copy(
            update={
                "reason": (
                    "Resident confirmed the exact crossing for this draft."
                    if report.location.confirmed
                    else "Demo location is approximate until the resident confirms it."
                ),
                "confidence": 0.92 if report.location.confirmed else 0.68,
            }
        )


report_store = InMemoryReportStore()
