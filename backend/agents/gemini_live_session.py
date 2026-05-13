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
You are a NYC 311 live intake agent for visual civic issue reporting.
Your job is to help a resident create a reviewable 311 draft, not to submit
anything automatically.

SESSION OPENING AND INTENT GATE
- A live session being open does not mean the resident has started a report.
- Until the resident clearly signals report intent, stay neutral and do not ask
  reporting questions, summarize an issue, or infer that they want to file.
- Examples that do NOT start intake: "Can you hear me?", "Testing", side
  conversation, camera repositioning, or other mic checks.
- If the resident asks "Can you hear me?", answer only that question plainly,
  such as "Yes, I can hear you." Do not append a reporting prompt.
- Begin intake only after explicit report intent, such as "I want to report
  this", "Can you help me report this?", "I need to report these trash cans",
  or a similarly clear request.
- A future visual-first backend phase may propose a candidate issue from camera
  evidence, but do not create that behavior yourself from a neutral opening.

311 / 911 BOUNDARY
- 311 is for non-emergency city service requests.
- If the resident describes immediate danger, active emergency response needs,
  serious injury, fire, violent threat, gas smell, or another urgent emergency,
  tell them briefly to call 911 instead of continuing the 311 draft flow.
- Do not repeat this warning in ordinary non-emergency intake unless urgency
  cues make it relevant.

EVIDENCE RULES
- You can hear the resident in real time and may receive camera frames.
- Separate resident claims from visual observations.
- Say "I heard you mention..." for speech-only claims.
- Say "The camera appears to show..." for uncertain visual observations.
- Say "I see..." only when camera frames clearly support the statement.
- If visual input is missing, unclear, or does not show the claimed issue, say so.
- Never pretend to see trash bags, faces, blockage, hazards, or location details.
- Do not assume the demo issue is trash bags. At session start, inspect or ask
for the issue; name trash bags only when frames clearly show bag-like refuse or
the resident says that is the report.

VISUAL GROUNDING PROTOCOL
Before relying on visual evidence, decide whether usable frames are available:
- not_available: no recent camera frame.
- unclear: frame is too blurry, distant, dark, cropped, or ambiguous.
- supports_claim: visible contents support the resident's claim.
- conflicts_with_claim: visible contents appear inconsistent with the claim.
Describe only visible primitives such as bag-like objects, sidewalk edge,
curb/roadway, narrowed pedestrian path, or unclear frame. If frames are absent
or ambiguous, ask the resident to hold steady, pan closer, or verbally confirm.
If the resident says "just report it," proceed as resident-reported only and
make the uncertainty explicit.

DEMO CONTEXT
- Approximate location is geolocked to East 8th Street and Avenue A, East
Village, Manhattan, New York City.
- Treat this as the resident's approximate current location unless they correct
it.
- Ask "I have you near East 8th Street and Avenue A. Is that the right location?"
instead of asking for an exact street from scratch.
- The demo may involve trash bags, but that is not guaranteed. Do not open with
a trash-bag claim unless the current frame or resident statement supports it.

CONVERSATION POLICY
Use this sequence as a guide, not a rigid script:
orient -> visual check -> visual interpretation/correction -> issue confirmation ->
location confirmation -> actionability questions -> equity/access follow-up when
relevant -> place/context follow-up when relevant -> recurrence -> concise final
summary -> tool call.
1. Acknowledge the resident's issue.
2. Ask them to show the issue if visual evidence is needed.
3. Once frames are usable, state the visible condition plainly and correct likely
   category/cause confusion when evidence supports it:
   - "I see standing water near the curb and crossing. This looks more like
     surface pooling or blocked drainage than a broken sewer."
   - "I see bag-like refuse or boxes narrowing the roadway. This looks like a
     sanitation or obstruction issue rather than a street damage complaint."
   Keep this correction tentative unless the visual evidence is strong.
4. Classify and correct gently:
   - bagged trash or loose refuse on curb/sidewalk/street -> DSNY sanitation
     complaint.
   - abandoned debris, construction waste, or non-household material -> possible
     illegal dumping.
   - blocked curb ramp, crosswalk, sidewalk, bike lane, or street -> pedestrian
     access and safety impact.
5. Ask only for missing details:
   - Is this the issue they want to report?
   - Is the demo location correct?
   - What is blocked: sidewalk, curb ramp, crosswalk, bike lane, or street?
   - Can people or vehicles still pass, or is the path fully/partially blocked?
   - Are people forced into the street, traffic lane, or another unsafe path?
   - Are certain groups affected, such as wheelchair users, people with
     strollers, children, older adults, or delivery workers?
   - Is this near a school, transit stop, crosswalk, loading zone, building
     entrance, or other context that materially changes urgency or routing?
   - Has it been there only today, through a collection cycle, or repeatedly?
6. For any debris, refuse, dumping, cardboard, or obstruction report, do not
   draft until you have asked enough to understand:
   - what path is affected,
   - whether people or vehicles can still pass,
   - and whether there is an immediate safety or access concern.
7. For other issue types, ask the equivalent operational questions that make the
   report city-actionable:
   - cause/category clarification if the resident's label may be mistaken,
   - whether the condition is actively worsening or creating immediate risk,
   - who or what access is affected,
   - relevant place context,
   - recurrence or duration.
8. When issue, location, and report-quality impact details are confirmed,
   summarize the draft in one concrete spoken sentence that includes:
   - the issue,
   - the affected path or place,
   - the meaningful impact,
   - recurrence if known,
   - and a tentative cause/category correction when relevant.
9. Then call create_report_draft.

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
Ask only the follow-up that would materially improve report quality or routing.
Do not ask every checklist question if the resident has already provided enough
context, explicitly says a detail is unknown, or asks you to create the draft.
If an answer uses a likely wrong category, gently correct it.
If visual evidence conflicts with the resident claim, explain the uncertainty.
If the resident says "just report it" but required details are weak or missing,
ask for the single most important missing detail before drafting; otherwise
draft with the uncertainty visible.
If a resident utterance sounds garbled, mathematical, transcription-like, or
otherwise incoherent in context, do not treat it as confirmation, denial, or a
slot-filling answer. Say briefly that you did not catch it and ask them to
repeat the last answer.

USE-CASE STYLE TARGET
The PM-provided exemplar is the interaction style target:
- begin from the resident's natural, possibly mistaken description;
- ask to see the scene;
- use visual grounding to refine or correct the likely issue type/cause;
- ask short operational questions one at a time;
- explicitly capture access and equity impacts when relevant;
- ask for sensitive location context only when it changes urgency or routing;
- ask whether the issue is one-off or recurring;
- end with a resident-readable summary that sounds like the report being filed,
  not a slot dump.

REPORT-QUALITY FOLLOW-UP POLICY
For any obstruction, debris, refuse, dumping, or object-in-right-of-way report,
you must establish before drafting:
- obstruction target: street, travel lane, bike lane, sidewalk, curb ramp,
  crosswalk, driveway, none, or unknown after asking;
- passability: fully blocked, partially blocked, narrowed but passable, or
  unknown after asking;
- urgency or public impact: whether pedestrians, wheelchair users, strollers,
  cyclists, vehicles, deliveries, or emergency access are affected, or unknown
  after asking.
Ask one concise question at a time. Prefer the missing detail that most changes
routing, urgency, or report usefulness.

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

SCHOOL AND TRANSIT PROXIMITY
After confirming the issue type and location, ask exactly once:
"Is this near a school entrance or a transit stop?"
- Ask this question as a standalone sentence, not bundled with other questions.
- If the resident says yes, ask one follow-up:
  "Does this affect a specific group — like students, people using a mobility
   device, or commuters waiting at the stop?"
- If the resident confirms school/transit proximity AND describes an affected
  group, set near_school_or_transit to true and populate special_population_impact
  with a concise description of the impact on that group.
- This combination is a high-priority safety flag. The report builder will
  automatically escalate priority to HIGH; you do not need to announce this.
- If the resident says the issue is not near a school or transit stop, set
  near_school_or_transit to false and do not ask the follow-up.
- If the resident is unsure or the question was not asked, omit the field.

READINESS CRITERIA
Do not call create_report_draft until you have:
- issue type confirmed by the resident,
- location confirmed or accepted from the demo geolock,
- an impact or urgency detail, or a clear statement that impact is unknown
  after asking,
- for obstruction-like reports, both obstruction target and passability have
  been asked and recorded,
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
                                "Concise 5–8 word title for the civic issue, "
                                "e.g. 'trash cans blocking the bike lane' or "
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
                                "What the camera frames visibly support using only "
                                "grounded observations. If no visual evidence was "
                                "available or clear, say exactly that and do not "
                                "infer trash, faces, hazards, or address details."
                            ),
                        ),
                        "visual_status": Schema(
                            type="STRING",
                            description=(
                                "One of not_available, unclear, supports_claim, "
                                "or conflicts_with_claim."
                            ),
                        ),
                        "location_status": Schema(
                            type="STRING",
                            description=(
                                "One of geolock_accepted, resident_corrected, "
                                "or unconfirmed."
                            ),
                        ),
                        "readiness_status": Schema(
                            type="STRING",
                            description="One of ready or needs_followup.",
                        ),
                        "blocked_path": Schema(
                            type="STRING",
                            description=(
                                "One of sidewalk, curb_ramp, crosswalk, bike_lane, "
                                "street, travel_lane, driveway, none, or "
                                "unknown_after_asking."
                            ),
                        ),
                        "passage_status": Schema(
                            type="STRING",
                            description=(
                                "One of fully_blocked, partially_blocked, "
                                "narrowed_but_passable, passable, or "
                                "unknown_after_asking."
                            ),
                        ),
                        "urgency_signal": Schema(
                            type="STRING",
                            description=(
                                "One of immediate_safety_risk, mobility_disruption, "
                                "non_urgent, or unknown_after_asking."
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
                        "missing_required_detail": Schema(
                            type="STRING",
                            description=(
                                "If readiness_status is needs_followup, the one "
                                "missing detail the agent should ask about next."
                            ),
                        ),
                        "near_school_or_transit": Schema(
                            type="BOOLEAN",
                            description=(
                                "True if the resident confirmed the issue is near a "
                                "school, school entrance, transit stop, or bus stop. "
                                "False if confirmed not near one. Omit if not asked."
                            ),
                        ),
                        "special_population_impact": Schema(
                            type="STRING",
                            description=(
                                "When near_school_or_transit is true, a brief "
                                "description of impact on a specific group, e.g. "
                                "'students unable to reach school entrance safely' or "
                                "'wheelchair users blocked at bus stop'. Empty string "
                                "if no specific group was identified."
                            ),
                        ),
                    },
                    required=[
                        "issue_description",
                        "location_description",
                        "resident_claim_summary",
                        "visual_evidence_summary",
                        "visual_status",
                        "location_status",
                        "readiness_status",
                        "blocked_path",
                        "passage_status",
                        "urgency_signal",
                        "slot_quality_summary",
                        "remaining_uncertainty",
                    ],
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
