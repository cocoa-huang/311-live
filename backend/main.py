from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.agents.live_model import (
    LiveModelAdapter,
    LiveObservation,
    live_model_adapter_from_settings,
)
from backend.agents.live_session import LiveSession
from backend.agents.model_context import build_model_context_packet
from backend.agents.report_builder import build_report_draft
from backend.schemas import (
    HealthResponse,
    LiveClassifyRequest,
    LiveClassifyResponse,
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


def create_app(
    context_provider: CivicContextProvider | None = None,
    live_model_adapter: LiveModelAdapter | None = None,
) -> FastAPI:
    settings = get_settings()
    resolved_context_provider = context_provider or provider_from_settings(settings)
    resolved_live_model_adapter = live_model_adapter or live_model_adapter_from_settings(
        settings
    )
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

    @app.post("/api/live/classify", response_model=LiveClassifyResponse)
    async def classify_live_observation(
        request: LiveClassifyRequest,
    ) -> LiveClassifyResponse:
        candidate = await resolved_live_model_adapter.detect_candidate(
            LiveObservation(
                transcript=request.transcript,
                image_summary=request.image_summary,
                image_frame=request.image_frame,
            )
        )
        return LiveClassifyResponse(
            scenario=candidate.scenario,  # type: ignore[arg-type]
            demo_variant=candidate.demo_variant,  # type: ignore[arg-type]
            candidate=candidate.candidate,
            confirmation=candidate.confirmation,
            followup=candidate.followup,
            model_source=candidate.source,
            fallback_reason=candidate.fallback_reason,
        )

    @app.websocket("/ws/live")
    async def live_agent(websocket: WebSocket) -> None:
        await websocket.accept()
        session = LiveSession(resolved_context_provider, resolved_live_model_adapter)
        try:
            while True:
                message = await websocket.receive_json()
                message_type = message.get("type")
                payload = message.get("payload") or {}
                if message_type == "start":
                    event = session.start(payload)
                elif message_type == "observation":
                    event = await session.observe(payload)
                elif message_type == "intent_confirmed":
                    event = session.confirm_intent()
                elif message_type == "location_confirmed":
                    event = session.confirm_location(payload)
                elif message_type == "create_draft":
                    event = session.create_draft()
                    if event.type == "draft_ready":
                        report_store.save(ReportDraft.model_validate(event.payload["report"]))
                else:
                    event = session._event("error", f"Unsupported live event: {message_type}")
                await websocket.send_json(event.model_dump(mode="json"))
        except WebSocketDisconnect:
            return

    return app


app = create_app()
