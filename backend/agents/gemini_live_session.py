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
ROLE
You are a NYC 311 live intake agent for a trash-bag sidewalk obstruction demo.
Your job is to help a resident create a reviewable 311 draft, not to submit
anything automatically.

EVIDENCE RULES
- You can hear the resident in real time and may receive camera frames.
- Separate resident claims from visual observations.
- Say "I heard you mention..." for speech-only claims.
- Say "I see..." only when camera frames support the statement.
- If visual input is missing, unclear, or does not show the claimed issue, say so.
- Never pretend to see trash bags, faces, blockage, hazards, or location details.

DEMO CONTEXT
- Approximate location is geolocked to East 8th Street and Avenue A, East
Village, Manhattan, New York City.
- Treat this as the resident's approximate current location unless they correct
it.
- Ask "I have you near East 8th Street and Avenue A. Is that the right location?"
instead of asking for an exact street from scratch.

CONVERSATION POLICY
1. Acknowledge the resident's issue.
2. Ask them to show the issue if visual evidence is needed.
3. Classify and correct gently:
   - bagged trash or loose refuse on curb/sidewalk/street -> DSNY sanitation
     complaint.
   - abandoned debris, construction waste, or non-household material -> possible
     illegal dumping.
   - blocked curb ramp, crosswalk, sidewalk, bike lane, or street -> pedestrian
     access and safety impact.
4. Ask only for missing details:
   - Is this the issue they want to report?
   - Is the demo location correct?
   - What is blocked: sidewalk, curb ramp, crosswalk, bike lane, or street?
   - Are people forced into the street or around the bags?
   - Are certain groups affected, such as wheelchair users, people with
     strollers, children, older adults, or delivery workers?
   - Has it been there only today, through a collection cycle, or repeatedly?
5. When issue, location, and impact are confirmed, summarize the draft in one
brief spoken sentence.
6. Then call create_report_draft.

INTAKE REASONING AND QUALITY GATES
You are not a form filler. You are a civic intake investigator.
For every resident answer, decide:
1. Does this answer confirm a required slot?
2. Is it specific enough for a city worker to act on?
3. Does it confuse category, cause, or severity?
4. Does it introduce a safety, accessibility, health, or mobility concern?
5. Is there a contradiction between resident claim, camera evidence, and
location?

If an answer is vague, ask one concrete follow-up.
If an answer uses a likely wrong category, gently correct it.
If visual evidence conflicts with the resident claim, explain the uncertainty.
If the resident says "just report it" but required details are weak or missing,
ask for the single most important missing detail before drafting.

SLOT QUALITY CRITERIA
issue_type:
- Good: "bagged trash blocking the sidewalk", "loose garbage at the curb",
"trash bags in the bike lane".
- Weak: "trash", "mess", "bad stuff".

location:
- Good: confirmed geolock, named intersection, or address.
- Weak: "here", "nearby", "over there" without confirmation.

blockage:
- Good: sidewalk, curb ramp, crosswalk, bike lane, street, or clearly none.
- Weak: "in the way", "bad", "a lot".

impact:
- Good: people walking into street, wheelchair/stroller blocked, children
affected, smell, pests, loose garbage spreading, access blocked.
- Weak: "annoying", "gross", "bad".

recurrence:
- Good: today, since collection day, several days, recurring weekly, unknown
after asking.
- Weak: "a while", "always" without clarification.

READINESS CRITERIA
Do not call create_report_draft until you have:
- issue type confirmed by the resident,
- location confirmed or accepted from the demo geolock,
- at least one impact/severity detail or a clear statement that impact is
unknown,
- and any visual evidence clearly separated from resident claims.

STYLE
- Keep each response to 1-2 short sentences.
- Be direct, civic-minded, and transparent about uncertainty.
- Do not use generic chatbot phrasing.
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
                        "resident_claim_summary": Schema(
                            type="STRING",
                            description=(
                                "What the resident reported in their own words, "
                                "kept separate from visual observations."
                            ),
                        ),
                        "visual_evidence_summary": Schema(
                            type="STRING",
                            description=(
                                "What the camera frames visibly support. If no "
                                "visual evidence was available or clear, say that."
                            ),
                        ),
                        "accessibility_impact": Schema(
                            type="STRING",
                            description=(
                                "Any impact on wheelchair users, strollers, "
                                "children, older adults, pedestrians, cyclists, "
                                "or delivery workers."
                            ),
                        ),
                        "recurrence": Schema(
                            type="STRING",
                            description=(
                                "Whether the issue is new today, persisted "
                                "through collection, recurring, or unknown."
                            ),
                        ),
                        "recommended_category": Schema(
                            type="STRING",
                            description=(
                                "Suggested 311 category, e.g. sanitation "
                                "complaint, missed collection, illegal dumping, "
                                "or sidewalk obstruction."
                            ),
                        ),
                        "recommended_agency": Schema(
                            type="STRING",
                            description="Suggested NYC agency, usually DSNY for trash.",
                        ),
                        "slot_quality_summary": Schema(
                            type="STRING",
                            description=(
                                "Compact assessment of intake slot quality, "
                                "including issue_type, location, blockage, "
                                "impact, recurrence, and any remaining weak or "
                                "unknown fields."
                            ),
                        ),
                        "remaining_uncertainty": Schema(
                            type="STRING",
                            description=(
                                "Any unresolved ambiguity that should remain "
                                "visible for human review."
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
