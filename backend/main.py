from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.agents.model_context import build_model_context_packet
from backend.agents.report_builder import build_report_draft
from backend.schemas import (
    HealthResponse,
    ModelContextPacket,
    ReportConfirmRequest,
    ReportConfirmResponse,
    ReportDraft,
    ReportDraftRequest,
    ReportUpdateRequest,
)
from backend.settings import get_settings
from backend.tools.nyc_311_context import CivicContextProvider, provider_from_settings
from backend.tools.report_store import report_store


def create_app(context_provider: CivicContextProvider | None = None) -> FastAPI:
    settings = get_settings()
    resolved_context_provider = context_provider or provider_from_settings(settings)
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
            draft = build_report_draft(request, resolved_context_provider)
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

    @app.patch("/api/report/{report_id}", response_model=ReportDraft)
    def update_report(
        report_id: str, request: ReportUpdateRequest
    ) -> ReportDraft:
        report = report_store.update(report_id, request)
        if report is None:
            raise HTTPException(status_code=404, detail="Report not found")
        return report

    @app.get("/api/report/{report_id}/model-context", response_model=ModelContextPacket)
    def model_context(report_id: str) -> ModelContextPacket:
        report = report_store.get(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Report not found")
        return build_model_context_packet(report)

    return app


app = create_app()
