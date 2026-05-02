from typing import Dict, Optional

from backend.schemas import ReportDraft, ReportStatus


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


report_store = InMemoryReportStore()
