import asyncio
import base64
import json
import logging

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.agents.gemini_live_session import (
    AudioChunkEvent,
    GeminiLiveSessionManager,
    SetupCompleteEvent,
    ToolCallEvent,
    TranscriptEvent,
    TurnCompleteEvent,
)
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

logger = logging.getLogger("uvicorn.error")


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
        if settings.live_model_mode in {"vertex", "gemini", "gemini-live"}:
            await _run_gemini_live_session(
                websocket, settings, resolved_context_provider
            )
        else:
            await _run_deterministic_session(
                websocket, resolved_context_provider, resolved_live_model_adapter
            )

    return app


async def _run_deterministic_session(
    websocket: WebSocket,
    context_provider,
    live_model_adapter,
) -> None:
    session = LiveSession(context_provider, live_model_adapter)
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


async def _run_gemini_live_session(
    websocket: WebSocket,
    settings,
    context_provider,
) -> None:
    from backend.agents.live_model import infer_live_report_path
    from backend.agents.report_builder import build_report_draft
    from backend.schemas import Location, ReportDraftRequest

    logger.info("gemini-live: opening Gemini session")
    manager = GeminiLiveSessionManager(settings)
    try:
        async with asyncio.timeout(12):
            await manager.__aenter__()
    except TimeoutError:
        logger.error("gemini-live: setup timed out before session_ready")
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "message": "Gemini Live setup timed out. Use fallback intake.",
                }
            )
        )
        await websocket.close(code=1013)
        return
    except Exception as exc:
        logger.exception("gemini-live: setup failed")
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "message": f"Gemini Live setup failed: {type(exc).__name__}",
                }
            )
        )
        await websocket.close(code=1011)
        return

    try:
        logger.info("gemini-live: Gemini session context opened")
        ctx: dict = {"location_label": None}
        audio_frames = 0
        image_frames = 0
        pending_draft_ready: dict | None = None
        await websocket.send_text(
            json.dumps(
                {
                    "type": "session_ready",
                    "session_id": manager.session_id,
                }
            )
        )
        logger.info("gemini-live: session_ready sent to frontend")

        async def _recv_from_frontend() -> None:
            nonlocal audio_frames, image_frames
            try:
                while True:
                    msg = await websocket.receive()
                    if msg["type"] == "websocket.disconnect":
                        logger.info("gemini-live: frontend websocket disconnected")
                        return
                    if msg.get("bytes"):
                        audio_frames += 1
                        if audio_frames == 1 or audio_frames % 25 == 0:
                            logger.info(
                                "gemini-live: received audio frame #%s (%s bytes)",
                                audio_frames,
                                len(msg["bytes"]),
                            )
                        await manager.send_audio(msg["bytes"])
                    elif msg.get("text"):
                        data = json.loads(msg["text"])
                        msg_type = data.get("type")
                        logger.info("gemini-live: received frontend event %s", msg_type)
                        if msg_type == "text":
                            await manager.send_text(data.get("text", ""))
                        elif msg_type == "image_frame":
                            image_frames += 1
                            if image_frames == 1 or image_frames % 5 == 0:
                                logger.info(
                                    "gemini-live: received image frame #%s",
                                    image_frames,
                                )
                            raw = data.get("data", "")
                            if "," in raw:
                                raw = raw.split(",", 1)[1]
                            await manager.send_image(base64.b64decode(raw))
                        elif msg_type == "start":
                            loc = (data.get("payload") or {}).get("location") or {}
                            lat = loc.get("latitude")
                            lng = loc.get("longitude")
                            if lat is not None and lng is not None:
                                ctx["location_label"] = (
                                    f"{abs(lat):.4f}°{'N' if lat >= 0 else 'S'}, "
                                    f"{abs(lng):.4f}°{'E' if lng >= 0 else 'W'}"
                                )
            except (WebSocketDisconnect, RuntimeError):
                pass

        async def _recv_from_gemini() -> None:
            nonlocal pending_draft_ready
            try:
                while True:
                    received_any = False
                    async for event in manager.receive_events():
                        received_any = True
                        if isinstance(event, SetupCompleteEvent):
                            logger.info("gemini-live: setup_complete received")
                            await asyncio.sleep(0.15)
                            if ctx.get("location_label"):
                                await manager.send_text(
                                    f"[System: Reporter GPS is approximately {ctx['location_label']}. "
                                    f"Reference this when discussing location.]"
                                )
                        elif isinstance(event, AudioChunkEvent):
                            logger.info(
                                "gemini-live: sending audio chunk (%s bytes)",
                                len(event.data),
                            )
                            await websocket.send_bytes(event.data)
                        elif isinstance(event, TranscriptEvent):
                            logger.info(
                                "gemini-live: transcript role=%s finished=%s text=%r",
                                event.role,
                                event.finished,
                                event.text,
                            )
                            await websocket.send_text(
                                json.dumps(
                                    {
                                        "type": "transcript",
                                        "role": event.role,
                                        "text": event.text,
                                        "finished": event.finished,
                                    }
                                )
                            )
                        elif isinstance(event, ToolCallEvent):
                            logger.info("gemini-live: tool call %s", event.name)
                            if event.name == "create_report_draft":
                                args = event.args
                                issue_desc = args.get("issue_description", "")
                                loc_desc = args.get("location_description", "")
                                severity = args.get("severity_details", "")
                                resident_claim = args.get("resident_claim_summary", "")
                                visual_evidence = args.get("visual_evidence_summary", "")
                                accessibility_impact = args.get(
                                    "accessibility_impact", ""
                                )
                                recurrence = args.get("recurrence", "")
                                recommended_category = args.get(
                                    "recommended_category", ""
                                )
                                recommended_agency = args.get("recommended_agency", "")
                                slot_quality = args.get("slot_quality_summary", "")
                                remaining_uncertainty = args.get(
                                    "remaining_uncertainty", ""
                                )
                                scenario, demo_variant = infer_live_report_path(issue_desc)
                                transcript_parts = [
                                    issue_desc,
                                    severity,
                                    resident_claim,
                                    accessibility_impact,
                                    recurrence,
                                ]
                                full_transcript = ". ".join(
                                    part.strip(". ")
                                    for part in transcript_parts
                                    if part
                                )
                                request = ReportDraftRequest(
                                    scenario=scenario,  # type: ignore[arg-type]
                                    demo_variant=demo_variant,  # type: ignore[arg-type]
                                    transcript=full_transcript,
                                    image_summary=visual_evidence or None,
                                    location=Location(
                                        label=loc_desc,
                                        source="gemini-live-confirmed",
                                        confirmed=True,
                                    ),
                                    resident_claim_summary=resident_claim or None,
                                    visual_evidence_summary=visual_evidence or None,
                                    accessibility_impact=accessibility_impact or None,
                                    recurrence=recurrence or None,
                                    recommended_category=recommended_category or None,
                                    recommended_agency=recommended_agency or None,
                                    slot_quality_summary=slot_quality or None,
                                    remaining_uncertainty=remaining_uncertainty or None,
                                )
                                draft = build_report_draft(request, context_provider)
                                report_store.save(draft)
                                await manager.respond_to_tool_call(
                                    event.call_id,
                                    event.name,
                                    {"status": "success", "report_id": draft.id},
                                )
                                pending_draft_ready = {
                                    "type": "draft_ready",
                                    "payload": {
                                        "report_id": draft.id,
                                        "report": draft.model_dump(mode="json"),
                                    },
                                }
                                logger.info(
                                    "gemini-live: draft_ready queued until turn_complete"
                                )
                        elif isinstance(event, TurnCompleteEvent):
                            logger.info("gemini-live: turn_complete")
                            await websocket.send_text(json.dumps({"type": "turn_complete"}))
                            if pending_draft_ready:
                                await asyncio.sleep(2.0)
                                await websocket.send_text(json.dumps(pending_draft_ready))
                                logger.info("gemini-live: draft_ready sent to frontend")
                                pending_draft_ready = None
                    if received_any:
                        logger.info("gemini-live: receive stream ended; waiting for next turn")
                    await asyncio.sleep(0.05)
            except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
                pass

        fe_task = asyncio.create_task(_recv_from_frontend())
        gm_task = asyncio.create_task(_recv_from_gemini())

        done, pending = await asyncio.wait(
            [fe_task, gm_task], return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
    finally:
        await manager.__aexit__(None, None, None)


app = create_app()
