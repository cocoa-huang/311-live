import asyncio
import base64
import binascii
import json
import logging
import time
from hmac import compare_digest

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
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
    IntakeState,
    LiveClassifyRequest,
    LiveClassifyResponse,
    Location,
    ModelContextPacket,
    ReportConfirmRequest,
    ReportConfirmResponse,
    ReportDraft,
    ReportDraftRequest,
    ReportUpdateRequest,
)
from backend.settings import get_settings
from backend.tools.location_labeler import label_location, reverse_geocoder_from_settings
from backend.tools.nyc_311_context import CivicContextProvider, provider_from_settings
from backend.tools.report_store import report_store

logger = logging.getLogger("uvicorn.error")
MAX_IMAGE_FRAME_BYTES = 2_000_000
LIVE_ACCESS_HEADER = "x-live-access-code"
ACCEPTED_LOCATION_STATUSES = {"geolock_accepted", "correction_confirmed"}
UNCONFIRMED_LOCATION_STATUSES = {
    "resident_corrected",
    "correction_pending_confirmation",
    "unconfirmed",
}


def _looks_like_corrupted_transcript(value: str) -> bool:
    text = value.strip()
    if not text:
        return True

    letters = sum(char.isalpha() for char in text)
    digits = sum(char.isdigit() for char in text)
    symbolic = sum(char in "^=+*/<>%$#@" for char in text)
    words = [part for part in text.replace("'", " ").split() if part]
    alpha_words = [word for word in words if any(char.isalpha() for char in word)]

    if symbolic >= 2 and digits >= 1:
        return True
    if digits >= 2 and letters <= 2:
        return True
    if symbolic >= 1 and digits >= 1 and len(alpha_words) <= 1:
        return True
    return False


def _live_access_required(settings) -> bool:
    return bool(settings.live_access_code) and settings.live_model_mode in {
        "vertex",
        "gemini",
        "gemini-live",
    }


def _live_access_allowed(settings, provided_code: str | None) -> bool:
    if not _live_access_required(settings):
        return True
    if not provided_code or not settings.live_access_code:
        return False
    return compare_digest(provided_code, settings.live_access_code)


def _location_from_payload(value: object) -> Location | None:
    if not isinstance(value, dict):
        return None
    return Location.model_validate(value)


def _location_prompt_label(location: Location) -> str:
    coordinate_label = ""
    if location.latitude is not None and location.longitude is not None:
        coordinate_label = (
            f"{abs(location.latitude):.4f}°{'N' if location.latitude >= 0 else 'S'}, "
            f"{abs(location.longitude):.4f}°{'E' if location.longitude >= 0 else 'W'}"
        )
    parts = [
        location.label,
        f"GPS {coordinate_label}" if coordinate_label else None,
        f"accuracy about {round(location.accuracy_meters)}m"
        if location.accuracy_meters
        else None,
        location.source,
    ]
    return "; ".join(part for part in parts if part)


def _location_log_payload(location: Location | None) -> dict[str, object | None]:
    if location is None:
        return {"present": False}
    return {
        "present": True,
        "label": location.label,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "accuracy_meters": location.accuracy_meters,
        "street_address": location.street_address,
        "intersection": location.intersection,
        "neighborhood": location.neighborhood,
        "borough": location.borough,
        "source": location.source,
        "confirmed": location.confirmed,
    }


def _looks_like_complete_location_correction(value: str | None) -> bool:
    text = " ".join(str(value or "").strip().split())
    if len(text) < 8:
        return False

    normalized = text.lower().strip(" .")
    incomplete_endings = (
        " and east",
        " and west",
        " and north",
        " and south",
        " and e",
        " and w",
        " and n",
        " and s",
        " ave",
        " avenue",
    )
    if normalized.endswith(incomplete_endings):
        return False

    has_street_word = any(
        token in normalized
        for token in [
            " st",
            " street",
            " ave",
            " avenue",
            " road",
            " rd",
            " place",
            " pl",
            " boulevard",
            " blvd",
            " drive",
            " dr",
        ]
    )
    has_intersection = " and " in normalized or " & " in normalized or " at " in normalized
    has_address_number = any(char.isdigit() for char in normalized)
    return has_street_word and (has_intersection or has_address_number)


def _looks_like_explicit_location_confirmation(value: str | None) -> bool:
    text = str(value or "").strip().lower()
    if len(text) < 3:
        return False
    words = {
        part.strip(".,!?;:")
        for part in text.replace("'", " ").replace("-", " ").split()
    }
    if words.intersection({"yes", "confirmed", "confirm"}):
        return True
    confirmation_phrases = [
        " correct ",
        " that's right",
        " that is right",
        " right location",
        " exact location",
        " resident confirmed",
    ]
    padded = f" {text} "
    return any(token in padded for token in confirmation_phrases)


def create_app(
    context_provider: CivicContextProvider | None = None,
    live_model_adapter: LiveModelAdapter | None = None,
) -> FastAPI:
    settings = get_settings()
    resolved_context_provider = context_provider or provider_from_settings(settings)
    reverse_geocoder = reverse_geocoder_from_settings(settings)
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
            draft = build_report_draft(
                request,
                resolved_context_provider,
                reverse_geocoder,
            )
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
        live_access_code: str | None = Header(default=None, alias=LIVE_ACCESS_HEADER),
    ) -> LiveClassifyResponse:
        if not _live_access_allowed(settings, live_access_code):
            raise HTTPException(status_code=401, detail="Live AI access code required")
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
            intake_state=candidate.intake_state,
        )

    @app.websocket("/ws/live")
    async def live_agent(websocket: WebSocket) -> None:
        provided_code = websocket.query_params.get("access_code")
        if not _live_access_allowed(settings, provided_code):
            await websocket.close(code=1008, reason="Live AI access code required")
            return
        await websocket.accept()
        if settings.live_model_mode in {"vertex", "gemini", "gemini-live"}:
            await _run_gemini_live_session(
                websocket,
                settings,
                resolved_context_provider,
                reverse_geocoder,
            )
        else:
            await _run_deterministic_session(
                websocket,
                resolved_context_provider,
                resolved_live_model_adapter,
                reverse_geocoder,
            )

    return app


async def _run_deterministic_session(
    websocket: WebSocket,
    context_provider,
    live_model_adapter,
    reverse_geocoder,
) -> None:
    session = LiveSession(context_provider, live_model_adapter, reverse_geocoder)
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
            elif message_type == "camera_closed":
                event = session.close_camera()
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
    reverse_geocoder,
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
        ctx: dict = {
            "location_label": None,
            "location": None,
            "intake_state": IntakeState(camera_lifecycle="camera_streaming"),
        }
        audio_frames = 0
        image_frames = 0
        dropped_image_frames = 0
        last_image_at: float | None = None
        setup_complete = False
        location_nudge_sent = False
        visual_nudge_sent = False
        await websocket.send_text(
            json.dumps(
                {
                    "type": "session_ready",
                    "session_id": manager.session_id,
                    "payload": {
                        "intake_state": ctx["intake_state"].model_dump(mode="json")
                    },
                }
            )
        )
        logger.info("gemini-live: session_ready sent to frontend")

        async def _send_location_nudge_if_ready() -> None:
            nonlocal location_nudge_sent
            if not setup_complete or location_nudge_sent or not ctx.get("location_label"):
                return
            backend_location = ctx.get("location")
            logger.info(
                "gemini-live: sending backend location candidate to Gemini label=%r payload=%s",
                ctx["location_label"],
                json.dumps(
                    _location_log_payload(
                        backend_location if isinstance(backend_location, Location) else None
                    ),
                    sort_keys=True,
                ),
            )
            await manager.send_text(
                "[System context update; do not answer this packet directly. "
                f"Backend-resolved reporter location candidate: {ctx['location_label']}. "
                "Store this as the authoritative location candidate for the session. "
                "When the resident has clearly started a report and location confirmation "
                "is appropriate, ask them to confirm this exact candidate. Do not invent "
                "or substitute any other address, borough, neighborhood, or intersection.]"
            )
            location_nudge_sent = True

        async def _send_visual_nudge_if_ready() -> None:
            nonlocal visual_nudge_sent
            if visual_nudge_sent or image_frames == 0:
                return
            # Do not send a text turn here. Live API client-content state nudges
            # can cause Gemini to speak before the resident has framed the issue.
            # A future visual-first state should request one explicit candidate.
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
                        elif msg_type == "camera_closed":
                            ctx["intake_state"] = ctx["intake_state"].model_copy(
                                update={"camera_lifecycle": "camera_closed_by_user"}
                            )
                            await manager.send_text(
                                "[System context update; do not answer this packet "
                                "directly. The resident intentionally stopped camera "
                                "capture after the live intake session began. Continue "
                                "the conversation by voice only. Reuse any visual "
                                "evidence already collected, keep it distinct from new "
                                "resident speech, and do not ask to reopen the camera "
                                "unless one missing report-critical detail truly "
                                "requires new visual confirmation.]"
                            )
                            await websocket.send_text(
                                json.dumps(
                                    {
                                        "type": "camera_closed",
                                        "payload": {
                                            "intake_state": ctx[
                                                "intake_state"
                                            ].model_dump(mode="json")
                                        },
                                    }
                                )
                            )
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
                                ctx["intake_state"] = ctx["intake_state"].model_copy(
                                    update={
                                        "frame_status": "available",
                                        "camera_lifecycle": "evidence_captured",
                                        "candidate_provenance": "visual_unclear",
                                    }
                                )
                                await websocket.send_text(
                                    json.dumps(
                                        {
                                            "type": "intake_state_updated",
                                            "payload": {
                                                "intake_state": ctx[
                                                    "intake_state"
                                                ].model_dump(mode="json")
                                            },
                                        }
                                    )
                                )
                                await _send_visual_nudge_if_ready()
                        elif msg_type == "start":
                            loc = (data.get("payload") or {}).get("location") or {}
                            location = _location_from_payload(loc)
                            logger.info(
                                "gemini-live: start location payload %s",
                                json.dumps(_location_log_payload(location), sort_keys=True),
                            )
                            if (
                                location
                                and location.latitude is not None
                                and location.longitude is not None
                            ):
                                geocode_started_at = time.monotonic()
                                labeled_location = await asyncio.to_thread(
                                    label_location,
                                    location,
                                    reverse_geocoder,
                                )
                                logger.info(
                                    "gemini-live: labeled start location latency=%.3fs payload=%s",
                                    time.monotonic() - geocode_started_at,
                                    json.dumps(
                                        _location_log_payload(labeled_location),
                                        sort_keys=True,
                                    ),
                                )
                                ctx["location"] = labeled_location
                                ctx["location_label"] = _location_prompt_label(
                                    labeled_location
                                )
                                await _send_location_nudge_if_ready()
                            else:
                                logger.info(
                                    "gemini-live: no usable start location coordinates"
                                )
            except (WebSocketDisconnect, RuntimeError):
                pass

        async def _recv_from_gemini() -> None:
            nonlocal setup_complete
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
                            if (
                                event.role == "user"
                                and event.finished
                                and _looks_like_corrupted_transcript(event.text)
                            ):
                                logger.warning(
                                    "gemini-live: likely corrupted user transcript %r",
                                    event.text,
                                )
                                await manager.send_text(
                                    "[System recovery instruction; do not answer this "
                                    "packet directly. The immediately preceding resident "
                                    f"utterance looked corrupted or non-semantic: {event.text!r}. "
                                    "Do not treat it as confirmation, denial, or a usable "
                                    "answer. Briefly say you did not catch that and ask the "
                                    "resident to repeat their last answer.]"
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
                                location_status = args.get("location_status", "")
                                location_confirmation_evidence = args.get(
                                    "location_confirmation_evidence", ""
                                )
                                missing_detail = args.get("missing_required_detail", "")
                                blocked_path = args.get("blocked_path", "")
                                passage_status = args.get("passage_status", "")
                                urgency_signal = args.get("urgency_signal", "")
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
                                logger.info(
                                    "gemini-live: draft tool location args status=%r description=%r confirmation_evidence=%r remaining_uncertainty=%r slot_quality=%r",
                                    location_status,
                                    loc_desc,
                                    location_confirmation_evidence,
                                    remaining_uncertainty,
                                    slot_quality,
                                )
                                missing_fields = [
                                    field
                                    for field, value in {
                                        "issue_description": issue_desc,
                                        "location_description": loc_desc,
                                        "location_status": location_status,
                                        "resident_claim_summary": resident_claim,
                                        "visual_evidence_summary": visual_evidence,
                                        "slot_quality_summary": slot_quality,
                                    }.items()
                                    if not str(value or "").strip()
                                ]
                                obstruction_like = any(
                                    token in " ".join(
                                        part
                                        for part in [
                                            issue_desc,
                                            severity,
                                            resident_claim,
                                            recommended_category,
                                        ]
                                        if part
                                    ).lower()
                                    for token in [
                                        "block",
                                        "obstruction",
                                        "street",
                                        "sidewalk",
                                        "lane",
                                        "boxes",
                                        "cardboard",
                                        "trash",
                                        "debris",
                                        "dumping",
                                    ]
                                )
                                if obstruction_like:
                                    for field, value in {
                                        "blocked_path": blocked_path,
                                        "passage_status": passage_status,
                                        "urgency_signal": urgency_signal,
                                    }.items():
                                        if not str(value or "").strip():
                                            missing_fields.append(field)
                                if (
                                    location_status
                                    and location_status not in ACCEPTED_LOCATION_STATUSES
                                    and location_status not in UNCONFIRMED_LOCATION_STATUSES
                                ):
                                    missing_fields.append("location_status")
                                if (
                                    location_status == "geolock_accepted"
                                    and not _looks_like_explicit_location_confirmation(
                                        location_confirmation_evidence
                                    )
                                ):
                                    missing_fields.append("location_confirmation_evidence")
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
                                if location_status in UNCONFIRMED_LOCATION_STATUSES:
                                    await manager.respond_to_tool_call(
                                        event.call_id,
                                        event.name,
                                        {
                                            "status": "needs_followup",
                                            "missing_fields": ["confirmed_report_location"],
                                            "message": (
                                                "The resident corrected, rejected, or has "
                                                "not confirmed the report location. Repeat "
                                                "the best-heard location back and ask one "
                                                "explicit confirmation question before "
                                                "drafting."
                                            ),
                                        },
                                    )
                                    logger.info(
                                        "gemini-live: rejected draft because location is not locked status=%r description=%r",
                                        location_status,
                                        loc_desc,
                                    )
                                    continue
                                if (
                                    location_status == "geolock_accepted"
                                    and not isinstance(ctx.get("location"), Location)
                                ):
                                    await manager.respond_to_tool_call(
                                        event.call_id,
                                        event.name,
                                        {
                                            "status": "needs_followup",
                                            "missing_fields": ["backend_location_candidate"],
                                            "message": (
                                                "No backend location candidate is available. "
                                                "Ask the resident for a concrete address, "
                                                "intersection, or place name before drafting."
                                            ),
                                        },
                                    )
                                    logger.info(
                                        "gemini-live: rejected geolock acceptance without backend location"
                                    )
                                    continue
                                if location_status == "correction_confirmed":
                                    if not _looks_like_complete_location_correction(
                                        loc_desc
                                    ) or not _looks_like_explicit_location_confirmation(
                                        location_confirmation_evidence
                                    ):
                                        await manager.respond_to_tool_call(
                                            event.call_id,
                                            event.name,
                                            {
                                                "status": "needs_followup",
                                                "missing_fields": [
                                                    "confirmed_corrected_location"
                                                ],
                                                "message": (
                                                    "The corrected location is not complete "
                                                    "or lacks explicit resident confirmation. "
                                                    "Repeat the corrected address or "
                                                    "intersection back and ask whether that "
                                                    "is the exact report location before "
                                                    "drafting."
                                                ),
                                            },
                                        )
                                        logger.info(
                                            "gemini-live: rejected corrected location status=%r description=%r evidence=%r",
                                            location_status,
                                            loc_desc,
                                            location_confirmation_evidence,
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
                                candidate_provenance = (
                                    "camera_observed"
                                    if visual_status == "supports_claim"
                                    and image_frames > 0
                                    else "visual_unclear"
                                    if image_frames > 0
                                    else "resident_reported_only"
                                )
                                scenario, demo_variant = infer_live_report_path(
                                    ". ".join(
                                        part
                                        for part in [
                                            issue_desc,
                                            severity,
                                            resident_claim,
                                            accessibility_impact,
                                            recommended_category,
                                            recommended_agency,
                                            args.get("blocked_path", ""),
                                        ]
                                        if part
                                    )
                                )
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
                                base_location = ctx.get("location")
                                if isinstance(base_location, Location):
                                    resident_corrected = (
                                        location_status == "correction_confirmed"
                                        and str(loc_desc or "").strip()
                                    )
                                    if resident_corrected:
                                        draft_location = Location(
                                            label=str(loc_desc).strip(),
                                            source=(
                                                "resident correction during Gemini live intake"
                                            ),
                                            confirmed=True,
                                        )
                                    else:
                                        draft_location = base_location.model_copy(
                                            update={"confirmed": True}
                                        )
                                else:
                                    draft_location = Location(
                                        label=loc_desc,
                                        source=(
                                            "resident correction during Gemini live intake"
                                            if location_status == "correction_confirmed"
                                            else "gemini-live-confirmed"
                                        ),
                                        confirmed=True,
                                    )
                                logger.info(
                                    "gemini-live: final draft location source=%r status=%r payload=%s",
                                    "resident_correction"
                                    if location_status == "correction_confirmed"
                                    else "backend_candidate",
                                    location_status,
                                    json.dumps(
                                        _location_log_payload(draft_location),
                                        sort_keys=True,
                                    ),
                                )

                                request = ReportDraftRequest(
                                    scenario=scenario,  # type: ignore[arg-type]
                                    demo_variant=demo_variant,  # type: ignore[arg-type]
                                    issue_description=issue_desc or None,
                                    transcript=full_transcript,
                                    image_summary=visual_evidence or None,
                                    location=draft_location,
                                    resident_claim_summary=resident_claim or None,
                                    visual_evidence_summary=visual_evidence or None,
                                    accessibility_impact=accessibility_impact or None,
                                    recurrence=recurrence or None,
                                    blocked_path=blocked_path or None,
                                    passage_status=passage_status or None,
                                    urgency_signal=urgency_signal or None,
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
                                                if blocked_path
                                                else "",
                                                f"passage_status={passage_status}"
                                                if passage_status
                                                else "",
                                                f"urgency_signal={urgency_signal}"
                                                if urgency_signal
                                                else "",
                                            ]
                                            if part
                                        )
                                        or None
                                    ),
                                    remaining_uncertainty=remaining_uncertainty or None,
                                    candidate_provenance=candidate_provenance,
                                )
                                draft = await asyncio.to_thread(
                                    build_report_draft,
                                    request,
                                    context_provider,
                                    reverse_geocoder,
                                )
                                report_store.save(draft)
                                ctx["intake_state"] = ctx["intake_state"].model_copy(
                                    update={
                                        "candidate_provenance": candidate_provenance,
                                        "resident_confirmed_intent": True,
                                        "location_confirmed": True,
                                        "draft_ready": True,
                                    }
                                )
                                await manager.respond_to_tool_call(
                                    event.call_id,
                                    event.name,
                                    {"status": "success", "report_id": draft.id},
                                )
                                draft_ready_event = {
                                    "type": "draft_ready",
                                    "payload": {
                                        "report_id": draft.id,
                                        "report": draft.model_dump(mode="json"),
                                        "intake_state": ctx[
                                            "intake_state"
                                        ].model_dump(mode="json"),
                                    },
                                }
                                await websocket.send_text(json.dumps(draft_ready_event))
                                logger.info(
                                    "gemini-live: draft_ready sent to frontend immediately after tool success"
                                )
                        elif isinstance(event, TurnCompleteEvent):
                            logger.info("gemini-live: turn_complete")
                            await websocket.send_text(json.dumps({"type": "turn_complete"}))
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
