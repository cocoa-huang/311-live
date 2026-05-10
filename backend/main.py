import asyncio
import base64
import binascii
import json
import logging
import time

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
MAX_IMAGE_FRAME_BYTES = 2_000_000


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


def _decode_jpeg_frame(raw: str) -> bytes:
    if not raw:
        raise ValueError("empty image frame")

    payload = raw
    if "," in raw:
        header, payload = raw.split(",", 1)
        if "image/jpeg" not in header and "image/jpg" not in header:
            raise ValueError("image frame must be a JPEG data URL")

    try:
        frame = base64.b64decode(payload, validate=True)
    except binascii.Error as exc:
        raise ValueError("invalid image frame base64") from exc

    if len(frame) > MAX_IMAGE_FRAME_BYTES:
        raise ValueError("image frame exceeds size limit")
    if not frame.startswith(b"\xff\xd8"):
        raise ValueError("image frame is not JPEG encoded")
    return frame


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
        dropped_image_frames = 0
        last_image_at: float | None = None
        setup_complete = False
        location_nudge_sent = False
        visual_nudge_sent = False
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

        async def _send_location_nudge_if_ready() -> None:
            nonlocal location_nudge_sent
            if not setup_complete or location_nudge_sent or not ctx.get("location_label"):
                return
            await manager.send_text(
                "[System state update; do not answer this packet directly. "
                f"Reporter GPS is approximately {ctx['location_label']}. "
                "Use it as approximate location context and ask the resident to confirm.]"
            )
            location_nudge_sent = True

        async def _send_visual_nudge_if_ready() -> None:
            nonlocal visual_nudge_sent
            if visual_nudge_sent or image_frames == 0:
                return
            await manager.send_text(
                "[System state update; do not answer this packet directly. "
                "A camera frame has been received. Ground visual statements only "
                "in visible contents. If the frame is unclear, say it is unclear "
                "and keep resident claims separate from camera evidence.]"
            )
            visual_nudge_sent = True

        async def _recv_from_frontend() -> None:
            nonlocal audio_frames, image_frames, dropped_image_frames, last_image_at
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
                            raw = data.get("data", "")
                            try:
                                jpeg_bytes = _decode_jpeg_frame(raw)
                            except ValueError as exc:
                                dropped_image_frames += 1
                                logger.warning(
                                    "gemini-live: dropped image frame #%s (%s)",
                                    dropped_image_frames,
                                    exc,
                                )
                                continue

                            image_frames += 1
                            last_image_at = time.monotonic()
                            width = data.get("width")
                            height = data.get("height")
                            if image_frames == 1 or image_frames % 5 == 0:
                                logger.info(
                                    "gemini-live: received image frame #%s (%s bytes, %sx%s)",
                                    image_frames,
                                    len(jpeg_bytes),
                                    width or "?",
                                    height or "?",
                                )
                            await manager.send_image(jpeg_bytes)
                            if image_frames == 1:
                                await _send_visual_nudge_if_ready()
                        elif msg_type == "start":
                            loc = (data.get("payload") or {}).get("location") or {}
                            lat = loc.get("latitude")
                            lng = loc.get("longitude")
                            if lat is not None and lng is not None:
                                ctx["location_label"] = (
                                    f"{abs(lat):.4f}°{'N' if lat >= 0 else 'S'}, "
                                    f"{abs(lng):.4f}°{'E' if lng >= 0 else 'W'}"
                                )
                                await _send_location_nudge_if_ready()
            except (WebSocketDisconnect, RuntimeError):
                pass

        async def _recv_from_gemini() -> None:
            nonlocal pending_draft_ready, setup_complete
            try:
                while True:
                    received_any = False
                    async for event in manager.receive_events():
                        received_any = True
                        if isinstance(event, SetupCompleteEvent):
                            logger.info("gemini-live: setup_complete received")
                            setup_complete = True
                            await _send_location_nudge_if_ready()
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
                                visual_status = args.get("visual_status", "")
                                readiness_status = args.get("readiness_status", "")
                                missing_detail = args.get("missing_required_detail", "")
                                image_age = (
                                    time.monotonic() - last_image_at
                                    if last_image_at is not None
                                    else None
                                )
                                logger.info(
                                    "gemini-live: draft tool state images=%s dropped=%s age=%s visual_status=%r readiness=%r",
                                    image_frames,
                                    dropped_image_frames,
                                    f"{image_age:.2f}s" if image_age is not None else "none",
                                    visual_status,
                                    readiness_status,
                                )
                                missing_fields = [
                                    field
                                    for field, value in {
                                        "issue_description": issue_desc,
                                        "location_description": loc_desc,
                                        "resident_claim_summary": resident_claim,
                                        "visual_evidence_summary": visual_evidence,
                                        "slot_quality_summary": slot_quality,
                                    }.items()
                                    if not str(value or "").strip()
                                ]
                                if readiness_status == "needs_followup" or missing_fields:
                                    await manager.respond_to_tool_call(
                                        event.call_id,
                                        event.name,
                                        {
                                            "status": "needs_followup",
                                            "missing_fields": missing_fields
                                            or [missing_detail or "required intake detail"],
                                            "message": (
                                                "Ask one concrete follow-up, then call "
                                                "create_report_draft only when the intake "
                                                "slots are ready."
                                            ),
                                        },
                                    )
                                    logger.info(
                                        "gemini-live: rejected premature draft tool call"
                                    )
                                    continue
                                if visual_status == "supports_claim" and image_frames == 0:
                                    await manager.respond_to_tool_call(
                                        event.call_id,
                                        event.name,
                                        {
                                            "status": "needs_correction",
                                            "message": (
                                                "No camera frames reached the backend. "
                                                "Downgrade visual_status and separate "
                                                "resident claims from visual evidence."
                                            ),
                                        },
                                    )
                                    logger.info(
                                        "gemini-live: rejected visually unsupported draft tool call"
                                    )
                                    continue
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
                                    slot_quality_summary=(
                                        "; ".join(
                                            part
                                            for part in [
                                                slot_quality,
                                                f"visual_status={visual_status}"
                                                if visual_status
                                                else "",
                                                f"location_status={args.get('location_status', '')}"
                                                if args.get("location_status")
                                                else "",
                                                f"blocked_path={args.get('blocked_path', '')}"
                                                if args.get("blocked_path")
                                                else "",
                                            ]
                                            if part
                                        )
                                        or None
                                    ),
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
