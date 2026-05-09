"""
Gemini Live session manager for the 311 intake agent.

Wraps google-genai live_connect() with the 311 system prompt,
create_report_draft tool, audio/image input, and event streaming.
"""

import asyncio
from dataclasses import dataclass, field
from typing import AsyncGenerator
from uuid import uuid4

from backend.settings import Settings

SYSTEM_PROMPT = """\
You are a 311 live intake agent for New York City. You help residents report \
street-level civic issues.

You can observe the resident's camera feed and hear what they say in real time.

Your goals:
1. Identify the civic issue the resident wants to report (trash, flooding, \
blocked sidewalk, etc.).
2. Confirm what you observe in one brief sentence and ask if that is the issue.
3. Ask 1-2 targeted follow-up questions: exact street or intersection, \
severity, whether anything is blocked.
4. Once you have confirmed both the issue type AND a street location, call \
create_report_draft immediately.

Rules:
- Keep every response to 1-2 sentences. Be direct and civic-minded.
- Do not call create_report_draft until you have confirmed both the issue and \
an approximate street location.
- When you are ready to draft, call the tool without announcing it first.

Common NYC 311 issue types:
- Trash bags or loose garbage on street or sidewalk → DSNY
- Street flooding or standing water near a school crossing → DEP or DOT
- Blocked sidewalk, curb ramp, or crosswalk → DOT
- Illegal dumping → DSNY
"""


def _make_report_draft_tool():
    from google.genai.types import FunctionDeclaration, Schema, Tool

    return Tool(
        function_declarations=[
            FunctionDeclaration(
                name="create_report_draft",
                description=(
                    "Generate a structured NYC 311 service request draft after "
                    "the resident has confirmed both the issue type and location."
                ),
                parameters=Schema(
                    type="OBJECT",
                    properties={
                        "issue_description": Schema(
                            type="STRING",
                            description=(
                                "Brief description of the civic issue, e.g. "
                                "'trash bags blocking sidewalk' or "
                                "'street flooding near school crossing'."
                            ),
                        ),
                        "location_description": Schema(
                            type="STRING",
                            description=(
                                "Street address, intersection, or neighborhood "
                                "confirmed by the resident, e.g. "
                                "'East 7th St and Avenue A, East Village, Manhattan'."
                            ),
                        ),
                        "severity_details": Schema(
                            type="STRING",
                            description=(
                                "Additional details about severity, blockage, or "
                                "hazard, e.g. 'bags blocking bike lane and partial sidewalk'."
                            ),
                        ),
                    },
                    required=["issue_description", "location_description"],
                ),
            )
        ]
    )


# ---------------------------------------------------------------------------
# Event types yielded by GeminiLiveSessionManager.receive_events()
# ---------------------------------------------------------------------------


@dataclass
class SetupCompleteEvent:
    pass


@dataclass
class AudioChunkEvent:
    data: bytes


@dataclass
class TranscriptEvent:
    role: str  # "user" or "model"
    text: str
    finished: bool = False


@dataclass
class ToolCallEvent:
    call_id: str
    name: str
    args: dict = field(default_factory=dict)


@dataclass
class TurnCompleteEvent:
    pass


GeminiEvent = (
    SetupCompleteEvent
    | AudioChunkEvent
    | TranscriptEvent
    | ToolCallEvent
    | TurnCompleteEvent
)


# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------


class GeminiLiveSessionManager:
    """Async context manager that holds a single Gemini Live session."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session_id = f"gemini_{uuid4().hex[:10]}"
        self._client = None
        self._session_ctx = None
        self._session = None

    async def __aenter__(self) -> "GeminiLiveSessionManager":
        from google import genai
        from google.genai.types import (
            AudioTranscriptionConfig,
            LiveConnectConfig,
            PrebuiltVoiceConfig,
            SpeechConfig,
            VoiceConfig,
        )

        if self.settings.google_cloud_project:
            self._client = genai.Client(
                vertexai=True,
                project=self.settings.google_cloud_project,
                location=self.settings.gemini_live_location,
            )
        elif self.settings.gemini_api_key:
            self._client = genai.Client(api_key=self.settings.gemini_api_key)
        else:
            raise ValueError(
                "Gemini Live requires GOOGLE_CLOUD_PROJECT for Vertex AI "
                "or GEMINI_API_KEY for Google AI Studio."
            )
        config = LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=SYSTEM_PROMPT,
            tools=[_make_report_draft_tool()],
            input_audio_transcription=AudioTranscriptionConfig(),
            output_audio_transcription=AudioTranscriptionConfig(),
            speech_config=SpeechConfig(
                voice_config=VoiceConfig(
                    prebuilt_voice_config=PrebuiltVoiceConfig(voice_name="Aoede")
                )
            ),
        )
        self._session_ctx = self._client.aio.live.connect(
            model=self.settings.gemini_live_model,
            config=config,
        )
        self._session = await self._session_ctx.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._session_ctx:
            await self._session_ctx.__aexit__(*exc)

    async def send_audio(self, pcm_16khz: bytes) -> None:
        from google.genai.types import Blob

        await self._session.send_realtime_input(
            audio=Blob(data=pcm_16khz, mime_type="audio/pcm;rate=16000")
        )

    async def send_image(self, jpeg_bytes: bytes) -> None:
        from google.genai.types import Blob

        await self._session.send_realtime_input(
            video=Blob(data=jpeg_bytes, mime_type="image/jpeg")
        )

    async def send_text(self, text: str) -> None:
        await self._session.send_client_content(
            turns={"role": "user", "parts": [{"text": text}]},
            turn_complete=True,
        )

    async def respond_to_tool_call(
        self, call_id: str, name: str, result: dict
    ) -> None:
        from google.genai.types import FunctionResponse

        await self._session.send_tool_response(
            function_responses=FunctionResponse(
                id=call_id,
                name=name,
                response=result,
            )
        )

    async def receive_events(self) -> AsyncGenerator[GeminiEvent, None]:
        async for msg in self._session.receive():
            if msg.setup_complete:
                yield SetupCompleteEvent()

            if msg.tool_call:
                for fc in msg.tool_call.function_calls:
                    yield ToolCallEvent(
                        call_id=fc.id or "",
                        name=fc.name or "",
                        args=dict(fc.args) if fc.args else {},
                    )

            if msg.server_content:
                sc = msg.server_content

                if sc.input_transcription and sc.input_transcription.text:
                    yield TranscriptEvent(
                        role="user",
                        text=sc.input_transcription.text,
                        finished=bool(sc.input_transcription.finished),
                    )

                if sc.output_transcription and sc.output_transcription.text:
                    yield TranscriptEvent(
                        role="model",
                        text=sc.output_transcription.text,
                        finished=bool(sc.output_transcription.finished),
                    )

                if sc.model_turn:
                    for part in sc.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            yield AudioChunkEvent(data=part.inline_data.data)

                if sc.turn_complete:
                    yield TurnCompleteEvent()
