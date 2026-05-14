"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Camera,
  CheckCircle2,
  FileText,
  Loader2,
  Mic,
  Play,
  RotateCcw,
} from "lucide-react";
import { DtprChain } from "@/components/DtprChain";
import { ReportReview } from "@/components/ReportReview";
import { StatusPill } from "@/components/StatusPill";
import {
  classifyLiveObservation,
  confirmDraft,
  createDemoDraft,
  getStoredLiveAccessCode,
  liveWebSocketUrl,
  storeLiveAccessCode,
  updateDraft,
  type DemoVariant,
  type ReportScenario,
  type ReportDraft,
  type ReportUpdateRequest,
  type IntakeState,
} from "@/lib/api";

type Phase =
  | "ready"
  | "permissions"
  | "observing"
  | "candidate"
  | "followup"
  | "draft"
  | "confirmed";

type CaptureStatus = "idle" | "requesting" | "active" | "denied" | "unavailable";
type LiveAgentStatus = "offline" | "connecting" | "ready" | "thinking" | "fallback";

interface SpeechRecognitionAlternativeLike {
  transcript: string;
}

interface SpeechRecognitionResultLike {
  isFinal: boolean;
  0: SpeechRecognitionAlternativeLike;
}

interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: {
    length: number;
    [index: number]: SpeechRecognitionResultLike;
  };
}

interface SpeechRecognitionErrorEventLike {
  error: string;
}

interface BrowserSpeechRecognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

type SpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

interface CapturedCameraFrame {
  dataUrl: string;
  width: number;
  height: number;
}

interface LiveAgentEvent {
  type:
    | "session_started"
    | "camera_closed"
    | "candidate_detected"
    | "followup_required"
    | "location_confirmation_required"
    | "draft_ready"
    | "error";
  session_id: string;
  message: string;
  payload: {
    scenario?: ReportScenario;
    demo_variant?: DemoVariant;
    candidate?: string;
    confirmation?: string;
    followup?: string;
    requires_location_confirmation?: boolean;
    report?: ReportDraft;
    intake_state?: IntakeState;
  };
}

const demoVariants: Array<{
  id: DemoVariant;
  scenario: ReportScenario;
  label: string;
  state: string;
  candidate: string;
  confirmation: string;
  followup: string;
}> = [
  {
    id: "baseline",
    scenario: "flooding_near_school_crossing",
    label: "Baseline",
    state: "Needs exact location",
    candidate: "Flooding near a school crossing",
    confirmation: "You described standing water near a school crossing. Is that what you want to report?",
    followup: "Can you confirm the exact crossing? And is this near a school entrance or transit stop where it could affect students or commuters?",
  },
  {
    id: "confirmed_location",
    scenario: "flooding_near_school_crossing",
    label: "Confirmed",
    state: "Location ready",
    candidate: "Flooding at a confirmed school crossing",
    confirmation: "You confirmed flooding at this crossing. Should I prepare this as a 311 report?",
    followup: "Is the water actively rising or blocking the curb ramp? Is this near a school entrance or transit stop?",
  },
  {
    id: "blocked_crosswalk",
    scenario: "flooding_near_school_crossing",
    label: "Blocked",
    state: "Higher safety signal",
    candidate: "Crosswalk access blocked by standing water",
    confirmation: "It sounds like water may be forcing pedestrians toward traffic. Is that the issue?",
    followup: "Is the crosswalk fully blocked or still partly passable? Is this near a school or transit stop — are students or commuters affected?",
  },
  {
    id: "visible_drain_obstruction",
    scenario: "flooding_near_school_crossing",
    label: "Drain",
    state: "Catch basin visible",
    candidate: "Possible clogged catch basin causing flooding",
    confirmation: "It sounds like there is flooding with possible debris near a drain. Is that what you want to report?",
    followup: "Is the drain covered by leaves, trash, or another obstruction? Is this near a school or transit stop?",
  },
  {
    id: "street_trash_bags",
    scenario: "trash_bags_on_street",
    label: "Trash",
    state: "Works anywhere",
    candidate: "Trash bags on the street or sidewalk",
    confirmation: "It sounds like there is bagged trash or loose refuse near your location. Is that what you want to report?",
    followup: "Are the bags blocking the sidewalk, curb, bike lane, or street? Is this near a school or transit stop where it could affect students or commuters?",
  },
];

const demoGeolockLocation = {
  label: "East 8th Street and Avenue A, East Village, Manhattan",
  latitude: 40.7271,
  longitude: -73.9837,
  accuracy_meters: 12,
  street_address: null,
  intersection: "East 8th Street and Avenue A",
  neighborhood: "East Village",
  borough: "Manhattan",
  source: "demo geolock",
};

const realLocationMode = process.env.NEXT_PUBLIC_REAL_LOCATION_MODE === "true";

export default function CitizenApp() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const liveSocketRef = useRef<WebSocket | null>(null);
  const livePanelRef = useRef<HTMLElement | null>(null);
  const audioInContextRef = useRef<AudioContext | null>(null);
  const audioInWorkletRef = useRef<AudioWorkletNode | null>(null);
  const playbackContextRef = useRef<AudioContext | null>(null);
  const playbackCursorRef = useRef<number>(0);
  const draftTransitionTimeoutRef = useRef<number | null>(null);
  const cameraFrameIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const subtitleQueueRef = useRef<string[]>([]);
  const subtitleTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const modelTurnActiveRef = useRef(false);
  const currentLocationRef = useRef<GeolocationCoordinates | null>(null);
  const [mounted, setMounted] = useState(false);
  const [phase, setPhase] = useState<Phase>("ready");
  const [draft, setDraft] = useState<ReportDraft | null>(null);
  const [issueDescription, setIssueDescription] = useState("");
  const [detectedVariant, setDetectedVariant] = useState<
    (typeof demoVariants)[number] | null
  >(null);
  const [cameraStatus, setCameraStatus] = useState<CaptureStatus>("idle");
  const [microphoneStatus, setMicrophoneStatus] = useState<CaptureStatus>("idle");
  const [locationStatus, setLocationStatus] = useState<CaptureStatus>("idle");
  const [currentLocation, setCurrentLocation] = useState<GeolocationCoordinates | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [captureLoading, setCaptureLoading] = useState(false);
  const [interimTranscript, setInterimTranscript] = useState("");
  const [liveAgentStatus, setLiveAgentStatus] = useState<LiveAgentStatus>("offline");
  const [liveAgentMessage, setLiveAgentMessage] = useState<string | null>(null);
  const [candidateFollowup, setCandidateFollowup] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmationNotice, setConfirmationNotice] = useState<string | null>(null);
  const [userSpeaking, setUserSpeaking] = useState<string>("");
  const [cameraFramesSent, setCameraFramesSent] = useState(0);
  const [intakeState, setIntakeState] = useState<IntakeState | null>(null);
  const [liveAccessCode, setLiveAccessCode] = useState("");

  const geminiLiveMode = !!liveWebSocketUrl();
  const activeVariant = detectedVariant ?? inferIssueVariant(issueDescription);

  useEffect(() => {
    setMounted(true);
    setLiveAccessCode(getStoredLiveAccessCode());
  }, []);

  useEffect(() => {
    if (videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [phase]);

  const stopLiveInputs = useCallback(() => {
    if (draftTransitionTimeoutRef.current !== null) {
      window.clearTimeout(draftTransitionTimeoutRef.current);
      draftTransitionTimeoutRef.current = null;
    }
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    liveSocketRef.current?.close();
    liveSocketRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    micStreamRef.current?.getTracks().forEach((track) => track.stop());
    micStreamRef.current = null;
    if (cameraFrameIntervalRef.current !== null) {
      clearInterval(cameraFrameIntervalRef.current);
      cameraFrameIntervalRef.current = null;
    }
    stopSubtitleStream();
    audioInWorkletRef.current = null;
    audioInContextRef.current?.close().catch(() => {});
    audioInContextRef.current = null;
    playbackContextRef.current?.close().catch(() => {});
    playbackContextRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setCameraStatus("idle");
    setMicrophoneStatus("idle");
    setLiveAgentStatus("offline");
    setLiveAgentMessage(null);
    setUserSpeaking("");
    setCameraFramesSent(0);
    setIntakeState(null);
    currentLocationRef.current = null;
  }, []);

  function scheduleDraftTransition(report: ReportDraft, nextIntakeState?: IntakeState) {
    const playbackContext = playbackContextRef.current;
    const remainingPlaybackSeconds = playbackContext
      ? Math.max(0, playbackCursorRef.current - playbackContext.currentTime)
      : 0;
    const transitionDelayMs = Math.ceil((remainingPlaybackSeconds + 0.35) * 1000);

    if (draftTransitionTimeoutRef.current !== null) {
      window.clearTimeout(draftTransitionTimeoutRef.current);
    }

    setIntakeState(nextIntakeState ?? null);
    setDraft(report);
    setLoading(false);
    setLiveAgentMessage(
      remainingPlaybackSeconds > 0.1
        ? "Finishing the agent's summary before opening the report."
        : null,
    );

    draftTransitionTimeoutRef.current = window.setTimeout(() => {
      draftTransitionTimeoutRef.current = null;
      setPhase("draft");
      stopLiveInputs();
    }, transitionDelayMs);
  }

  useEffect(() => {
    return () => {
      stopLiveInputs();
    };
  }, [stopLiveInputs]);

  function stopSubtitleStream() {
    if (subtitleTimerRef.current !== null) {
      clearInterval(subtitleTimerRef.current);
      subtitleTimerRef.current = null;
    }
    subtitleQueueRef.current = [];
    modelTurnActiveRef.current = false;
  }

  function enqueueModelSubtitle(text: string) {
    const tokens = text.trim().split(/\s+/).filter(Boolean);
    if (tokens.length === 0) return;

    if (!modelTurnActiveRef.current) {
      modelTurnActiveRef.current = true;
      subtitleQueueRef.current = [];
      setLiveAgentMessage("");
    }

    subtitleQueueRef.current.push(...tokens);
    if (subtitleTimerRef.current !== null) return;

    subtitleTimerRef.current = setInterval(() => {
      const next = subtitleQueueRef.current.shift();
      if (!next) {
        if (subtitleTimerRef.current !== null) {
          clearInterval(subtitleTimerRef.current);
          subtitleTimerRef.current = null;
        }
        return;
      }
      setLiveAgentMessage((current) => {
        if (!current) return next;
        const separator = /^[,.;:!?)]/.test(next) ? "" : " ";
        return `${current}${separator}${next}`;
      });
    }, 145);
  }

  function currentLocationPayload(confirmed = false) {
    const location = currentLocationRef.current ?? currentLocation;
    if (location && (!geminiLiveMode || realLocationMode)) {
      return {
        label: null,
        latitude: location.latitude,
        longitude: location.longitude,
        accuracy_meters: location.accuracy,
        street_address: null,
        intersection: null,
        neighborhood: null,
        borough: null,
        source: "browser geolocation",
        confirmed,
      };
    }
    if (geminiLiveMode && realLocationMode) {
      return undefined;
    }
    if (geminiLiveMode) {
      return {
        ...demoGeolockLocation,
        confirmed,
      };
    }
    return undefined;
  }

  function locationLabel() {
    if (currentLocation) {
      return realLocationMode ? "Phone location shared" : "Phone location captured";
    }
    if (locationStatus === "requesting") {
      return "Requesting location";
    }
    if (locationStatus === "active") {
      return "Available";
    }
    if (locationStatus === "denied") {
      return "Permission needed";
    }
    return "Enter location manually";
  }

  function inferIssueVariant(description: string) {
    const normalized = description.toLowerCase();
    if (
      /\b(trash|garbage|refuse|rubbish|bags?|bagged|sanitation|dumping)\b/.test(
        normalized,
      )
    ) {
      return demoVariants.find((variant) => variant.id === "street_trash_bags")!;
    }
    if (/\b(drain|catch basin|sewer|clogged|leaves)\b/.test(normalized)) {
      return demoVariants.find((variant) => variant.id === "visible_drain_obstruction")!;
    }
    if (/\b(crosswalk|sidewalk|blocked|blocking|traffic lane)\b/.test(normalized)) {
      return demoVariants.find((variant) => variant.id === "blocked_crosswalk")!;
    }
    return demoVariants[0];
  }

  function startReport() {
    setDraft(null);
    setError(null);
    currentLocationRef.current = null;
    setCurrentLocation(null);
    setLocationStatus("idle");
    setIssueDescription("");
    setDetectedVariant(null);
    setInterimTranscript("");
    stopSubtitleStream();
    setLiveAgentMessage(null);
    setCandidateFollowup(null);
    setLiveAgentStatus("offline");
    setIntakeState(null);
    setPhase("permissions");
    requestAnimationFrame(() => {
      livePanelRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
  }

  async function beginObserving() {
    setCaptureLoading(true);
    setError(null);
    try {
      await requestCamera();
      await requestLocation();
      if (geminiLiveMode) {
        await requestMicrophone();
      } else {
        prepareSpeechRecognition();
      }
      setCameraFramesSent(0);
      connectLiveAgent();
      setPhase("observing");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not access camera for live capture.",
      );
    } finally {
      setCaptureLoading(false);
    }
  }

  function connectLiveAgent() {
    const url = liveWebSocketUrl(liveAccessCode);
    if (!url) {
      setLiveAgentStatus("fallback");
      return;
    }

    liveSocketRef.current?.close();
    setLiveAgentStatus("connecting");
    const socket = new WebSocket(url);
    socket.binaryType = "arraybuffer";
    liveSocketRef.current = socket;

    socket.onopen = () => {
      socket.send(
        JSON.stringify({
          type: "start",
          payload: { location: currentLocationPayload(false) },
        }),
      );
    };

    socket.onmessage = async (event) => {
      // Binary frame = PCM audio from Gemini
      if (event.data instanceof ArrayBuffer) {
        playAudioChunk(event.data);
        return;
      }

      const data = JSON.parse(event.data as string) as Record<string, unknown>;
      const eventType = data.type as string;

      // Gemini Live events
      if (eventType === "session_ready") {
        const payload = data.payload as LiveAgentEvent["payload"];
        setIntakeState(payload?.intake_state ?? null);
        setLiveAgentStatus("ready");
        startCameraFrameCapture(socket);
        if (geminiLiveMode) {
          try {
            await startAudioCapture(socket);
          } catch {
            setMicrophoneStatus("denied");
            setError("Could not start microphone capture.");
          }
        }
      } else if (eventType === "transcript") {
        const role = data.role as string;
        const text = data.text as string;
        const finished = data.finished as boolean;
        if (role === "model") {
          enqueueModelSubtitle(text);
          setLiveAgentStatus("thinking");
        } else if (role === "user" && finished) {
          setUserSpeaking(text);
        }
      } else if (eventType === "turn_complete") {
        modelTurnActiveRef.current = false;
        setLiveAgentStatus("ready");
      } else if (eventType === "intake_state_updated") {
        const payload = data.payload as LiveAgentEvent["payload"];
        setIntakeState(payload?.intake_state ?? null);
      } else if (eventType === "camera_closed") {
        const payload = data.payload as LiveAgentEvent["payload"];
        setIntakeState(payload?.intake_state ?? null);
      } else if (eventType === "draft_ready") {
        const payload = data.payload as {
          report?: ReportDraft;
          report_id?: string;
          intake_state?: IntakeState;
        };
        if (payload?.report) {
          scheduleDraftTransition(payload.report, payload.intake_state);
        }
      // Legacy deterministic events
      } else if (eventType === "session_started") {
        const payload = data.payload as LiveAgentEvent["payload"];
        setIntakeState(payload?.intake_state ?? null);
        setLiveAgentStatus("ready");
      } else if (eventType === "candidate_detected") {
        const payload = data.payload as LiveAgentEvent["payload"];
        setIntakeState(payload?.intake_state ?? null);
        if (payload?.demo_variant) {
          const nextVariant = demoVariants.find((v) => v.id === payload.demo_variant);
          if (nextVariant) {
            setDetectedVariant(nextVariant);
            setCandidateFollowup(payload.followup ?? null);
            setPhase("candidate");
          }
        }
        setLiveAgentStatus("ready");
      } else if (eventType === "followup_required") {
        const payload = data.payload as LiveAgentEvent["payload"];
        if (payload?.intake_state) {
          setIntakeState(payload.intake_state);
        }
        setPhase("followup");
        setLiveAgentStatus("ready");
      } else if (eventType === "location_confirmation_required") {
        const msg = (data as { message?: string }).message ?? "Confirm location.";
        setError(msg);
        setLiveAgentStatus("ready");
      } else if (eventType === "error") {
        const msg = (data as { message?: string }).message ?? "Live agent error.";
        setError(msg);
        setLoading(false);
        setLiveAgentStatus("fallback");
      }
    };

    socket.onerror = () => {
      setLoading(false);
      setLiveAgentStatus("fallback");
    };
    socket.onclose = () => {
      setLiveAgentStatus((current) =>
        current === "connecting" || current === "ready" ? "fallback" : current,
      );
    };
  }

  async function requestCamera() {
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraStatus("unavailable");
      throw new Error("Camera capture is not available in this browser.");
    }

    setCameraStatus("requesting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }
      setCameraStatus("active");
    } catch (err) {
      setCameraStatus("denied");
      throw err;
    }
  }

  async function requestMicrophone() {
    if (!navigator.mediaDevices?.getUserMedia) {
      setMicrophoneStatus("unavailable");
      return;
    }
    setMicrophoneStatus("requesting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      micStreamRef.current = stream;
      setMicrophoneStatus("idle");
    } catch {
      setMicrophoneStatus("denied");
    }
  }

  async function startAudioCapture(socket: WebSocket) {
    if (audioInContextRef.current) return;
    if (!micStreamRef.current) return;

    const AudioContextClass =
      window.AudioContext ?? (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextClass) return;

    // 16 kHz capture context — browser resamples mic stream automatically
    const inCtx = new AudioContextClass({ sampleRate: 16000 });
    audioInContextRef.current = inCtx;

    // Playback context at 24 kHz, created here while close to a user gesture
    const outCtx = new AudioContextClass({ sampleRate: 24000 });
    playbackContextRef.current = outCtx;
    playbackCursorRef.current = 0;

    // AudioWorklet via Blob URL — batches 100ms of 16kHz PCM before sending
    // 128 samples/chunk at 16kHz ≈ 8ms; 1600 samples ≈ 100ms → ~10 msg/sec instead of 125
    const workletCode = `
      class PcmCapture extends AudioWorkletProcessor {
        constructor() { super(); this._buf = []; this._size = 0; this._target = 1600; }
        process(inputs) {
          const ch = inputs[0]?.[0];
          if (ch) {
            this._buf.push(new Float32Array(ch));
            this._size += ch.length;
            if (this._size >= this._target) {
              const out = new Int16Array(this._size);
              let off = 0;
              for (const f of this._buf) {
                for (let i = 0; i < f.length; i++) {
                  out[off++] = Math.max(-32768, Math.min(32767, f[i] * 32768));
                }
              }
              this.port.postMessage(out.buffer, [out.buffer]);
              this._buf = []; this._size = 0;
            }
          }
          return true;
        }
      }
      registerProcessor('pcm-capture', PcmCapture);
    `;
    const blob = new Blob([workletCode], { type: "application/javascript" });
    const workletUrl = URL.createObjectURL(blob);
    await inCtx.audioWorklet.addModule(workletUrl);
    URL.revokeObjectURL(workletUrl);

    const source = inCtx.createMediaStreamSource(micStreamRef.current);
    const workletNode = new AudioWorkletNode(inCtx, "pcm-capture");
    audioInWorkletRef.current = workletNode;

    workletNode.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(e.data);
      }
    };
    source.connect(workletNode);
    setMicrophoneStatus("active");
  }

  async function startCameraFrameCapture(socket: WebSocket) {
    if (cameraFrameIntervalRef.current !== null) return;

    const sendCameraFrame = () => {
      if (socket.readyState !== WebSocket.OPEN || !streamRef.current) return;
      const frame = captureCameraFrame();
      if (!frame) return;
      socket.send(
        JSON.stringify({
          type: "image_frame",
          data: frame.dataUrl,
          width: frame.width,
          height: frame.height,
          captured_at: new Date().toISOString(),
        }),
      );
      setCameraFramesSent((count) => count + 1);
    };

    await waitForCameraFrame();
    // Prime Gemini with visual context before or alongside the first audio turn.
    sendCameraFrame();
    window.setTimeout(sendCameraFrame, 200);
    window.setTimeout(sendCameraFrame, 500);
    cameraFrameIntervalRef.current = setInterval(sendCameraFrame, 1000);
  }

  function continueByVoiceOnly() {
    if (cameraFrameIntervalRef.current !== null) {
      clearInterval(cameraFrameIntervalRef.current);
      cameraFrameIntervalRef.current = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setCameraStatus("idle");
    setLiveAgentMessage("Visual context captured. Keep speaking; camera is off.");
    setIntakeState((current) =>
      current
        ? { ...current, camera_lifecycle: "camera_closed_by_user" }
        : current,
    );
    if (liveSocketRef.current?.readyState === WebSocket.OPEN) {
      liveSocketRef.current.send(JSON.stringify({ type: "camera_closed", payload: {} }));
    }
  }

  function playAudioChunk(buffer: ArrayBuffer) {
    const ctx = playbackContextRef.current;
    if (!ctx) return;

    const int16 = new Int16Array(buffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768;
    }

    const audioBuffer = ctx.createBuffer(1, float32.length, 24000);
    audioBuffer.copyToChannel(float32, 0);

    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(ctx.destination);

    const startAt = Math.max(ctx.currentTime, playbackCursorRef.current);
    source.start(startAt);
    playbackCursorRef.current = startAt + audioBuffer.duration;
  }

  async function requestLocation() {
    if (!navigator.geolocation) {
      setLocationStatus("unavailable");
      return;
    }

    setLocationStatus("requesting");
    await new Promise<void>((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          currentLocationRef.current = position.coords;
          setCurrentLocation(position.coords);
          setLocationStatus("active");
          resolve();
        },
        () => {
          setLocationStatus("denied");
          resolve();
        },
        {
          enableHighAccuracy: true,
          timeout: 8000,
          maximumAge: 30000,
        },
      );
    });
  }

  function speechRecognitionConstructor() {
    if (typeof window === "undefined") {
      return null;
    }

    const speechWindow = window as Window & {
      SpeechRecognition?: SpeechRecognitionConstructor;
      webkitSpeechRecognition?: SpeechRecognitionConstructor;
    };

    return speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition ?? null;
  }

  function prepareSpeechRecognition() {
    if (!speechRecognitionConstructor()) {
      setMicrophoneStatus("unavailable");
      return;
    }

    setMicrophoneStatus("idle");
  }

  function startVoiceCapture() {
    const SpeechRecognition = speechRecognitionConstructor();
    if (!SpeechRecognition) {
      setMicrophoneStatus("unavailable");
      setError(
        "Voice transcription is not available in this browser. Type the description below.",
      );
      return;
    }

    setError(null);
    setInterimTranscript("");
    if (phase === "observing") {
      setIssueDescription("");
      setDetectedVariant(null);
    }
    setMicrophoneStatus("requesting");

    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    recognition.onresult = (event) => {
      let finalText = "";
      let interimText = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result.isFinal) {
          finalText += result[0].transcript;
        } else {
          interimText += result[0].transcript;
        }
      }

      if (finalText.trim()) {
        setIssueDescription((current) =>
          phase === "observing"
            ? finalText.trim()
            : `${current ? `${current.trim()} ` : ""}${finalText.trim()}`,
        );
      }
      setInterimTranscript(interimText.trim());
      setMicrophoneStatus("active");
    };
    recognition.onerror = (event) => {
      setMicrophoneStatus(event.error === "not-allowed" ? "denied" : "unavailable");
      setError("Voice transcription stopped. You can type the description below.");
    };
    recognition.onend = () => {
      setInterimTranscript("");
      setMicrophoneStatus((current) => (current === "active" ? "idle" : current));
    };

    recognitionRef.current = recognition;
    recognition.start();
  }

  async function showCandidate() {
    if (!issueDescription.trim()) {
      setError("Tell the agent what you are seeing before detecting the issue.");
      return;
    }
    setError(null);
    if (liveSocketRef.current?.readyState === WebSocket.OPEN) {
      setLiveAgentStatus("thinking");
      liveSocketRef.current.send(
        JSON.stringify({
          type: "observation",
          payload: {
            transcript: issueDescription.trim(),
            location: currentLocationPayload(false),
          },
        }),
      );
      return;
    }
    setLiveAgentStatus("thinking");
    const imageFrame = captureCameraFrame();
    try {
      const classified = await classifyLiveObservation(
        issueDescription.trim(),
        imageFrame
          ? "Still frame captured from the resident's active camera preview."
          : undefined,
        imageFrame?.dataUrl,
        currentLocationPayload(false),
        liveAccessCode,
      );
      const nextVariant = demoVariants.find(
        (variant) => variant.id === classified.demo_variant,
      );
      setDetectedVariant(nextVariant ?? inferIssueVariant(issueDescription));
      setLiveAgentMessage(classified.confirmation);
      setCandidateFollowup(classified.followup);
      setIntakeState(classified.intake_state);
      setPhase("candidate");
      setLiveAgentStatus(
        classified.model_source === "deterministic-fallback" ? "fallback" : "ready",
      );
    } catch {
      setDetectedVariant(inferIssueVariant(issueDescription));
      setPhase("candidate");
      setLiveAgentStatus("fallback");
    }
  }

  function captureCameraFrame(): CapturedCameraFrame | undefined {
    const video = videoRef.current;
    if (!video || video.videoWidth === 0 || video.videoHeight === 0) {
      video?.play().catch(() => {});
      return undefined;
    }

    const canvas = document.createElement("canvas");
    const maxLongEdge = 960;
    const longEdge = Math.max(video.videoWidth, video.videoHeight);
    const scale = Math.min(1, maxLongEdge / longEdge);
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    const context = canvas.getContext("2d");
    if (!context) {
      return undefined;
    }
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    return {
      dataUrl: canvas.toDataURL("image/jpeg", 0.84),
      width: canvas.width,
      height: canvas.height,
    };
  }

  async function waitForCameraFrame() {
    const video = videoRef.current;
    if (!video) return;
    if (video.videoWidth > 0 && video.videoHeight > 0) return;
    await new Promise<void>((resolve) => {
      const timeout = window.setTimeout(resolve, 1200);
      const finish = () => {
        window.clearTimeout(timeout);
        resolve();
      };
      video.addEventListener("loadedmetadata", finish, { once: true });
      video.addEventListener("canplay", finish, { once: true });
      video.play().catch(() => finish());
    });
  }

  function retryDescription() {
    setIssueDescription("");
    setInterimTranscript("");
    setDetectedVariant(null);
    setLiveAgentMessage(null);
    setCandidateFollowup(null);
    setPhase("observing");
    setError(null);
  }

  function correctCandidate() {
    setDetectedVariant(null);
    setInterimTranscript("");
    setLiveAgentMessage(null);
    setCandidateFollowup(null);
    setPhase("observing");
    setError(null);
  }

  function confirmIntent() {
    if (liveSocketRef.current?.readyState === WebSocket.OPEN) {
      setLiveAgentStatus("thinking");
      liveSocketRef.current.send(
        JSON.stringify({ type: "intent_confirmed", payload: {} }),
      );
      return;
    }
    setLiveAgentMessage(candidateFollowup || activeVariant.followup);
    setPhase("followup");
  }

  async function generateDraft() {
    setLoading(true);
    setError(null);
    try {
      if (liveSocketRef.current?.readyState === WebSocket.OPEN) {
        liveSocketRef.current.send(
          JSON.stringify({
            type: "location_confirmed",
            payload: { location: currentLocationPayload(true) },
          }),
        );
        liveSocketRef.current.send(
          JSON.stringify({ type: "create_draft", payload: {} }),
        );
        return;
      }
      const report = await createDemoDraft(
        activeVariant.scenario,
        activeVariant.id,
        currentLocationPayload(false),
        issueDescription.trim() || undefined,
      );
      setDraft(report);
      setPhase("draft");
      stopLiveInputs();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create report draft.");
    } finally {
      if (liveSocketRef.current?.readyState !== WebSocket.OPEN) {
        setLoading(false);
      }
    }
  }

  async function handleConfirm() {
    if (!draft) {
      return;
    }

    setConfirming(true);
    setError(null);
    try {
      const response = await confirmDraft(draft.id);
      setDraft(response.report);
      setConfirmationNotice(
        `${response.message} Ticket updates will appear here when live submission is connected.`,
      );
      setPhase("confirmed");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not confirm report.");
    } finally {
      setConfirming(false);
    }
  }

  async function handleSaveEdits(updates: ReportUpdateRequest) {
    if (!draft) {
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const updated = await updateDraft(draft.id, updates);
      setDraft(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save report edits.");
    } finally {
      setSaving(false);
    }
  }

  function resetDemo() {
    stopLiveInputs();
    setDraft(null);
    setPhase("ready");
    setError(null);
    setCurrentLocation(null);
    setLocationStatus("idle");
    setIssueDescription("");
    setDetectedVariant(null);
    setInterimTranscript("");
    setConfirmationNotice(null);
    setLiveAgentMessage(null);
    setCandidateFollowup(null);
    setLiveAgentStatus("offline");
    setIntakeState(null);
  }

  function handleLiveAccessCodeChange(value: string) {
    setLiveAccessCode(value);
    storeLiveAccessCode(value);
  }

  // Derived step index for the workflow tracker
  const activeStep =
    phase === "ready" || phase === "permissions" ? 0
    : phase === "observing" ? 1
    : phase === "candidate" || phase === "followup" ? 2
    : phase === "draft" ? 3
    : 4;

  const liveProgress =
    phase === "ready" || phase === "permissions"
      ? { step: 1, label: "Getting capture ready" }
      : intakeState?.draft_ready
        ? { step: 4, label: "Preparing the report" }
        : intakeState?.location_confirmed
          ? { step: 3, label: "Checking impact" }
          : intakeState?.resident_confirmed_intent
            ? { step: 2, label: "Confirming location" }
            : phase === "candidate"
              ? { step: 2, label: "Confirming the issue" }
              : phase === "followup"
                ? { step: 3, label: "Checking impact" }
                : { step: 1, label: "Understanding the issue" };

  return (
    <main className="min-h-screen bg-field font-sans">
      {/* NYC 311 brand bar */}
      <div className="h-[3px] w-full bg-brand" />

      {/* Sticky header */}
      <header className="sticky top-0 z-20 bg-white shadow-[0_1px_0_0_rgba(0,0,0,0.1)]">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            {/* NYC 311 badge — black box, yellow border */}
            <div className="flex h-11 w-11 shrink-0 items-center justify-center border-[2.5px] border-brand bg-ink">
              <div className="text-center">
                <span className="block text-[8px] font-black uppercase leading-none tracking-[0.2em] text-brand">
                  NYC
                </span>
                <span className="block text-[15px] font-black leading-none text-white">
                  311
                </span>
              </div>
            </div>
            <div>
              <p className="text-[10px] font-black uppercase tracking-[0.2em] text-ink/35">
                Live Report
              </p>
              <h1 className="text-lg font-black leading-tight text-ink sm:text-xl">
                Show it. Say it. Solve it.
              </h1>
            </div>
          </div>
          <button
            type="button"
            onClick={resetDemo}
            className="focus-ring flex h-9 w-9 shrink-0 items-center justify-center border border-ink/15 bg-white text-ink/45 transition hover:border-ink hover:bg-ink hover:text-white"
            aria-label="Reset demo"
          >
            <RotateCcw size={15} />
          </button>
        </div>
      </header>

      {/* Page content */}
      <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[340px_1fr]">

          {/* ── Sidebar ── */}
          <aside className="order-2 space-y-4 lg:order-1">

            {/* Intake controls card */}
            <section className="bg-white shadow-card">
              <div className="border-l-[3px] border-brand px-5 py-4">
                <p className="text-[9px] font-black uppercase tracking-[0.25em] text-ink/35">
                  Live Intake
                </p>
                <h2 className="mt-0.5 text-base font-black text-ink">
                  Camera · Voice · Location
                </h2>
              </div>
              <div className="space-y-1.5 border-t border-ink/8 px-4 pb-4 pt-3">
                <StatusPill
                  kind="camera"
                  label="Camera"
                  state={
                    cameraStatus === "active"
                      ? "Live preview"
                      : phase === "ready"
                        ? "Ready on start"
                        : "Needs permission"
                  }
                />
                <StatusPill
                  kind="microphone"
                  label="Microphone"
                  state={
                    microphoneStatus === "active"
                      ? "Listening"
                      : microphoneStatus === "requesting"
                        ? "Requesting"
                        : microphoneStatus === "unavailable"
                          ? "Type fallback"
                          : phase === "ready"
                            ? "Ready on start"
                            : "Ready"
                  }
                />
                <StatusPill
                  kind="location"
                  label="Location"
                  state={locationLabel()}
                />
                <StatusPill
                  kind={phase === "confirmed" ? "confirmed" : "dtpr"}
                  label="Data chain"
                  state={phase === "ready" ? "Generated after draft" : "Visible"}
                />
                <StatusPill
                  kind="dtpr"
                  label="Live agent"
                  state={
                    liveAgentStatus === "ready"
                      ? "WebSocket ready"
                      : liveAgentStatus === "thinking"
                        ? "Processing"
                        : liveAgentStatus === "fallback"
                          ? "Local simulator"
                          : liveAgentStatus === "connecting"
                            ? "Connecting"
                            : "Offline"
                  }
                />
              </div>
              <div className="space-y-3 border-t border-ink/8 px-4 pb-4 pt-3">
                {geminiLiveMode && (
                  <label className="block">
                    <span className="mb-1.5 block text-[10px] font-black uppercase tracking-[0.2em] text-ink/45">
                      Live AI access code
                    </span>
                    <input
                      type="password"
                      value={liveAccessCode}
                      onChange={(event) => handleLiveAccessCodeChange(event.target.value)}
                      placeholder="Enter demo code"
                      className="focus-ring h-11 w-full border border-ink/15 bg-field px-3 text-sm font-bold text-ink placeholder:text-ink/30"
                      autoComplete="one-time-code"
                    />
                  </label>
                )}
                <button
                  type="button"
                  onClick={startReport}
                  disabled={loading || phase !== "ready"}
                  className="focus-ring flex min-h-12 w-full items-center justify-center gap-2 bg-brand px-4 py-3 font-black text-ink shadow-sm transition hover:bg-brand/80 active:scale-[0.98] disabled:cursor-wait disabled:bg-ink/12 disabled:text-ink/35 disabled:shadow-none"
                >
                  <Play size={17} aria-hidden="true" />
                  Start Report
                </button>
                <div className="flex items-start gap-2 border border-red-200 bg-red-50 px-3 py-2.5">
                  <span className="mt-px shrink-0 text-xs font-black text-red-600">!</span>
                  <p className="text-xs leading-5 text-red-700">
                    For non-emergency city reports only.{" "}
                    <strong className="font-black">Call 911</strong> for immediate danger.
                  </p>
                </div>
              </div>
            </section>

            {/* Workflow tracker */}
            <section className="bg-white shadow-card">
              <div className="border-l-[3px] border-brand px-5 py-4">
                <p className="text-[9px] font-black uppercase tracking-[0.25em] text-ink/35">
                  Workflow
                </p>
              </div>
              <div className="border-t border-ink/8 px-4 py-3">
                <ol className="space-y-0.5">
                  {(["Start", "Observe", "Confirm", "Draft", "Review"] as const).map(
                    (item, index) => {
                      const isActive = activeStep === index;
                      const isDone = activeStep > index;
                      return (
                        <li
                          key={item}
                          className={`flex items-center gap-3 px-3 py-2.5 transition-colors ${
                            isActive ? "bg-brand/12" : ""
                          }`}
                        >
                          <span
                            className={`flex h-7 w-7 shrink-0 items-center justify-center text-xs font-black transition-all ${
                              isActive
                                ? "bg-brand text-ink"
                                : isDone
                                  ? "bg-signal/12 text-signal"
                                  : "bg-field text-ink/30"
                            }`}
                          >
                            {isDone ? "✓" : index + 1}
                          </span>
                          <span
                            className={`text-sm font-bold ${
                              isActive
                                ? "text-ink"
                                : isDone
                                  ? "text-signal"
                                  : "text-ink/35"
                            }`}
                          >
                            {item}
                          </span>
                          {isActive && (
                            <span className="ml-auto text-[9px] font-black uppercase tracking-widest text-ink/40">
                              Now
                            </span>
                          )}
                          {!isActive && index < 4 && (
                            <ArrowRight
                              size={12}
                              className="ml-auto text-ink/15"
                              aria-hidden="true"
                            />
                          )}
                        </li>
                      );
                    },
                  )}
                </ol>
              </div>
            </section>
          </aside>

          {/* ── Main content ── */}
          <div className="order-1 space-y-5 lg:order-2">
            {error && (
              <div className="border border-red-200 bg-red-50 px-4 py-3 text-sm font-bold text-red-700">
                {error}
              </div>
            )}

            {phase !== "draft" && phase !== "confirmed" ? (
              <section
                ref={livePanelRef}
                className="scroll-mt-4 overflow-hidden bg-white shadow-card"
              >
                {/* Panel header */}
                <div className="border-l-[3px] border-brand px-5 py-4">
                  <p className="text-[9px] font-black uppercase tracking-[0.25em] text-ink/35">
                    {phase === "ready" ? "Ready" : "Live Agent"}
                  </p>
                  <h2 className="mt-0.5 text-lg font-black text-ink">
                    {phase === "ready"
                      ? "Start a live 311 report"
                      : phase === "observing"
                        ? "Describe what you see"
                        : activeVariant.candidate}
                  </h2>
                </div>

                <div className="flex items-center justify-between gap-3 border-t border-ink/8 bg-field px-4 py-2.5 text-[11px] font-black uppercase tracking-[0.18em] text-ink/55">
                  <span>
                    Step {liveProgress.step} of 4
                  </span>
                  <span className="truncate text-right text-ink">
                    {liveProgress.label}
                  </span>
                </div>

                {/* Camera view */}
                <div className="relative bg-ink">
                  <div className="relative aspect-[4/5] min-h-[280px] bg-[#0a0c10] sm:aspect-video sm:min-h-[320px]">
                    {mounted && (
                      <video
                        ref={videoRef}
                        autoPlay
                        muted
                        playsInline
                        className={`h-full w-full object-cover ${
                          cameraStatus === "active" ? "block" : "hidden"
                        }`}
                      />
                    )}
                    <div
                      className={`absolute inset-0 flex flex-col justify-between p-4 ${
                        cameraStatus === "active"
                          ? "bg-gradient-to-b from-black/55 via-transparent to-black/65"
                          : "bg-[#0a0c10]"
                      }`}
                    >
                      {/* HUD top row */}
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Camera size={14} className="text-brand" />
                          <span className="text-[11px] font-black uppercase tracking-widest text-white/70">
                            Camera
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          {cameraFramesSent > 0 && (
                            <span className="bg-white/10 px-2 py-0.5 font-mono text-[10px] font-bold text-brand/90 backdrop-blur-sm">
                              FRAMES {cameraFramesSent}
                            </span>
                          )}
                          <span
                            className={`px-2 py-0.5 text-[10px] font-black uppercase tracking-widest backdrop-blur-sm ${
                              cameraStatus === "active"
                                ? "animate-blink-live bg-brand text-ink"
                                : "bg-white/10 text-white/50"
                            }`}
                          >
                            {cameraStatus === "active"
                              ? "● LIVE"
                              : phase === "ready"
                                ? "INACTIVE"
                                : "WAITING"}
                          </span>
                        </div>
                      </div>

                      {/* HUD bottom — DTPR chips */}
                      <div className="flex flex-wrap gap-1.5">
                        {[
                          "Camera",
                          "Mic",
                          realLocationMode ? "Phone location" : "Demo location",
                        ].map((chip) => (
                          <span
                            key={chip}
                            className="bg-white/10 px-2 py-1 text-[10px] font-bold text-white/75 backdrop-blur-sm"
                          >
                            {chip}
                          </span>
                        ))}
                        <span className="bg-signal/80 px-2 py-1 text-[10px] font-bold text-white backdrop-blur-sm">
                          DTPR visible
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Intake state chips */}
                {intakeState && (
                  <div className="flex flex-wrap gap-2 border-b border-ink/8 bg-field px-4 py-2.5">
                    <span
                      className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-bold ${
                        intakeState.candidate_provenance === "camera_observed"
                          ? "bg-signal/10 text-signal"
                          : intakeState.candidate_provenance === "visual_unclear"
                            ? "bg-caution/10 text-caution"
                            : "bg-ink/6 text-ink/45"
                      }`}
                    >
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${
                          intakeState.candidate_provenance === "camera_observed"
                            ? "bg-signal"
                            : intakeState.candidate_provenance === "visual_unclear"
                              ? "bg-caution"
                              : "bg-ink/25"
                        }`}
                      />
                      {intakeState.candidate_provenance === "camera_observed"
                        ? "Camera-observed candidate"
                        : intakeState.candidate_provenance === "visual_unclear"
                          ? "Visual evidence unclear"
                          : "Resident-reported only"}
                    </span>
                    <span
                      className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-bold ${
                        intakeState.resident_confirmed_intent
                          ? "bg-signal/10 text-signal"
                          : "bg-ink/6 text-ink/45"
                      }`}
                    >
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${
                          intakeState.resident_confirmed_intent ? "bg-signal" : "bg-ink/25"
                        }`}
                      />
                      {intakeState.resident_confirmed_intent
                        ? "Intent confirmed"
                        : "Intent pending"}
                    </span>
                    <span
                      className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-bold ${
                        intakeState.location_confirmed
                          ? "bg-signal/10 text-signal"
                          : "bg-ink/6 text-ink/45"
                      }`}
                    >
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${
                          intakeState.location_confirmed ? "bg-signal" : "bg-ink/25"
                        }`}
                      />
                      {intakeState.location_confirmed
                        ? "Location confirmed"
                        : "Location pending"}
                    </span>
                    <span className="inline-flex items-center gap-1.5 bg-ink/6 px-2.5 py-1 text-[11px] font-bold text-ink/55">
                      {intakeState.camera_lifecycle === "camera_closed_by_user"
                        ? "Camera off · voice only"
                        : intakeState.camera_lifecycle === "evidence_captured"
                          ? "Visual context captured"
                          : intakeState.camera_lifecycle === "camera_streaming"
                            ? "Camera streaming"
                            : "Camera unavailable"}
                    </span>
                  </div>
                )}

                {/* Agent message + controls */}
                <div className="space-y-3 p-4">
                  {/* Agent bubble */}
                  <div className="border border-ink/10 bg-field p-4">
                    <div className="flex items-start gap-3">
                      <div
                        className={`flex h-9 w-9 shrink-0 items-center justify-center transition-all ${
                          liveAgentStatus === "thinking"
                            ? "animate-pulse-speaking bg-brand text-ink"
                            : "bg-ink text-brand"
                        }`}
                      >
                        <Mic size={16} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-[9px] font-black uppercase tracking-[0.25em] text-ink/35">
                          {liveAgentStatus === "thinking"
                            ? "Agent — speaking"
                            : "NYC 311 Agent"}
                        </p>
                        <p className="mt-1.5 text-sm leading-6 text-ink/70">
                          {phase === "ready" &&
                            "Tap Start Report when you are ready to capture the issue."}
                          {phase === "permissions" &&
                            "I will use camera, microphone, and location only for this report flow. 311 is for non-emergency reports; call 911 for immediate danger. Continue?"}
                          {phase === "observing" &&
                            (liveAgentMessage ||
                              (geminiLiveMode
                                ? cameraFramesSent > 0
                                  ? "Session ready. I have location and camera context. Say what you want to report when you are ready."
                                  : "Session ready. I have location context; waiting for camera frames."
                                : "Tell me what you are seeing, then I will identify the likely 311 issue."))}
                          {phase === "candidate" &&
                            (liveAgentMessage || activeVariant.confirmation)}
                          {phase === "followup" &&
                            (liveAgentMessage || activeVariant.followup)}
                        </p>
                        {geminiLiveMode && phase === "observing" && userSpeaking && (
                          <div className="mt-2.5 border border-ink/10 bg-white px-3 py-2 text-xs text-ink/55">
                            <span className="font-black text-ink/60">You: </span>
                            {userSpeaking}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  {intakeState?.camera_lifecycle === "evidence_captured" &&
                    cameraStatus === "active" && (
                      <button
                        type="button"
                        onClick={continueByVoiceOnly}
                        className="focus-ring flex min-h-11 w-full items-center justify-center border border-ink/15 bg-white px-4 py-2.5 text-sm font-black text-ink transition hover:border-ink/35 hover:bg-field"
                      >
                        Continue by voice only
                      </button>
                    )}

                  {/* Resident description input */}
                  {(phase === "observing" ||
                    phase === "candidate" ||
                    phase === "followup") &&
                    !(
                      geminiLiveMode &&
                      phase === "observing" &&
                      liveAgentStatus !== "fallback"
                    ) && (
                      <div className="border border-ink/10 bg-white p-4">
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-[9px] font-black uppercase tracking-[0.25em] text-ink/35">
                            Your description
                          </span>
                          <div className="flex shrink-0 items-center gap-2">
                            {phase === "observing" && issueDescription && (
                              <button
                                type="button"
                                onClick={retryDescription}
                                className="focus-ring min-h-9 border border-ink/15 bg-white px-3 py-1.5 text-sm font-bold text-ink/55 transition hover:border-ink/30 hover:text-ink"
                              >
                                Clear
                              </button>
                            )}
                            {(phase === "candidate" || phase === "followup") && (
                              <button
                                type="button"
                                onClick={correctCandidate}
                                className="focus-ring min-h-9 border border-ink/15 bg-white px-3 py-1.5 text-sm font-bold text-ink/55 transition hover:border-ink/30 hover:text-ink"
                              >
                                Correct
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={startVoiceCapture}
                              disabled={microphoneStatus === "active"}
                              className="focus-ring flex min-h-9 items-center gap-1.5 bg-brand px-3 py-1.5 text-sm font-black text-ink transition hover:bg-brand/80 disabled:cursor-wait disabled:bg-ink/12 disabled:text-ink/35"
                            >
                              <Mic size={14} aria-hidden="true" />
                              {microphoneStatus === "active" ? "Listening…" : "Speak"}
                            </button>
                          </div>
                        </div>
                        {(interimTranscript || issueDescription) && (
                          <div className="mt-3 bg-field px-3 py-2.5 text-sm leading-6 text-ink/65">
                            {issueDescription}
                            {interimTranscript && (
                              <span className="text-ink/35"> {interimTranscript}</span>
                            )}
                          </div>
                        )}
                        <textarea
                          value={issueDescription}
                          onChange={(event) => {
                            setIssueDescription(event.target.value);
                            if (phase === "observing") {
                              setDetectedVariant(null);
                            }
                          }}
                          rows={2}
                          className="focus-ring mt-3 w-full resize-none border border-ink/15 bg-field px-3 py-2.5 text-sm leading-6 text-ink placeholder:text-ink/30"
                          placeholder="Voice fallback: There are trash bags blocking the sidewalk here."
                        />
                      </div>
                    )}

                  {/* Action buttons */}
                  <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                    {phase === "permissions" && (
                      <button
                        type="button"
                        onClick={beginObserving}
                        disabled={captureLoading}
                        className="focus-ring col-span-full flex min-h-12 items-center justify-center gap-2 bg-brand px-4 py-3 font-black text-ink shadow-sm transition hover:bg-brand/80 active:scale-[0.98]"
                      >
                        {captureLoading ? (
                          <Loader2 className="animate-spin" size={18} aria-hidden="true" />
                        ) : (
                          <CheckCircle2 size={18} aria-hidden="true" />
                        )}
                        {captureLoading ? "Starting Capture…" : "Allow Camera + Location"}
                      </button>
                    )}
                    {phase === "observing" &&
                      (!geminiLiveMode || liveAgentStatus === "fallback") && (
                        <button
                          type="button"
                          onClick={showCandidate}
                          disabled={!issueDescription.trim()}
                          className="focus-ring flex min-h-12 items-center justify-center gap-2 bg-ink px-4 py-3 font-black text-white transition hover:bg-ink/80 active:scale-[0.98] disabled:cursor-not-allowed disabled:bg-ink/15 disabled:text-ink/35"
                        >
                          <Camera size={18} aria-hidden="true" />
                          Detect Candidate
                        </button>
                      )}
                    {phase === "observing" && geminiLiveMode && (
                      <div className="flex min-h-12 items-center gap-2.5 border border-ink/12 bg-field px-4 py-3 text-sm">
                        <Loader2
                          size={15}
                          className={
                            liveAgentStatus === "ready" || liveAgentStatus === "thinking"
                              ? "animate-spin text-brand"
                              : "text-ink/20"
                          }
                          aria-hidden="true"
                        />
                        <span className="font-bold text-ink/55">
                          {liveAgentStatus === "connecting"
                            ? "Connecting to agent…"
                            : liveAgentStatus === "ready"
                              ? "Listening — speak to report"
                              : liveAgentStatus === "thinking"
                                ? "Agent is speaking…"
                                : liveAgentStatus === "fallback"
                                  ? "Live session unavailable"
                                  : "Starting…"}
                        </span>
                      </div>
                    )}
                    {phase === "candidate" && (
                      <>
                        <button
                          type="button"
                          onClick={confirmIntent}
                          className="focus-ring flex min-h-12 items-center justify-center gap-2 bg-brand px-4 py-3 font-black text-ink shadow-sm transition hover:bg-brand/80 active:scale-[0.98]"
                        >
                          <CheckCircle2 size={18} aria-hidden="true" />
                          Yes, Report This
                        </button>
                        <button
                          type="button"
                          onClick={correctCandidate}
                          className="focus-ring flex min-h-12 items-center justify-center border border-ink/20 bg-white px-4 py-3 font-black text-ink transition hover:border-ink/40 hover:bg-field"
                        >
                          No, Correct Issue
                        </button>
                      </>
                    )}
                    {phase === "followup" && (
                      <button
                        type="button"
                        onClick={generateDraft}
                        disabled={loading}
                        className="focus-ring flex min-h-12 items-center justify-center gap-2 bg-brand px-4 py-3 font-black text-ink shadow-sm transition hover:bg-brand/80 active:scale-[0.98] disabled:cursor-wait disabled:bg-ink/12 disabled:shadow-none"
                      >
                        {loading ? (
                          <Loader2 className="animate-spin" size={18} aria-hidden="true" />
                        ) : (
                          <FileText size={18} aria-hidden="true" />
                        )}
                        {loading ? "Drafting…" : "Create Draft"}
                      </button>
                    )}
                  </div>
                </div>
              </section>
            ) : (
              <>
                {phase === "confirmed" && confirmationNotice && (
                  <div
                    role="status"
                    aria-live="polite"
                    className="border border-signal/25 bg-signal/8 px-4 py-4 shadow-card"
                  >
                    <div className="flex items-start gap-3">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center bg-signal text-white">
                        <CheckCircle2 size={18} aria-hidden="true" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-black text-ink">Report confirmed</p>
                        <p className="mt-1 text-sm leading-6 text-ink/65">
                          {confirmationNotice}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setConfirmationNotice(null)}
                        className="focus-ring shrink-0 border border-ink/15 bg-white px-3 py-1.5 text-xs font-black text-ink/60 hover:bg-field"
                      >
                        Dismiss
                      </button>
                    </div>
                  </div>
                )}
                {draft && (
                  <>
                    <ReportReview
                      report={draft}
                      onConfirm={handleConfirm}
                      onSaveEdits={handleSaveEdits}
                      confirming={confirming}
                      saving={saving}
                    />
                    <DtprChain steps={draft.dtpr_chain} />
                  </>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
