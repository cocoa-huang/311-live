from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.agents.report_builder import build_report_draft
from backend.schemas import (
    HealthResponse,
    ReportConfirmRequest,
    ReportConfirmResponse,
    ReportDraft,
    ReportDraftRequest,
)
from backend.settings import get_settings
from backend.tools.report_store import report_store


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:3000",
            "http://localhost:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service=settings.app_name,
            environment=settings.environment,
        )

    @app.post("/api/report/draft", response_model=ReportDraft)
    def draft_report(request: ReportDraftRequest) -> ReportDraft:
        try:
            draft = build_report_draft(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return report_store.save(draft)

    @app.post("/api/report/confirm", response_model=ReportConfirmResponse)
    def confirm_report(request: ReportConfirmRequest) -> ReportConfirmResponse:
        report = report_store.confirm(request.report_id, request.correction)
        if report is None:
            raise HTTPException(status_code=404, detail="Report not found")

        message = (
            "Report confirmed for demo submission."
            if request.accepted
            else "Report marked reviewed but not submitted."
        )
        return ReportConfirmResponse(report=report, message=message)

    return app


app = create_app()
