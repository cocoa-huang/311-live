"use client";

import { useEffect, useRef, useState } from "react";
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
  liveWebSocketUrl,
  updateDraft,
  type DemoVariant,
  type ReportScenario,
  type ReportDraft,
  type ReportUpdateRequest,
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

interface LiveAgentEvent {
  type:
    | "session_started"
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
    confirmation: "I see standing water near a school crossing. Is that what you want to report?",
    followup: "Can you confirm the exact crossing before I draft the report?",
  },
  {
    id: "confirmed_location",
    scenario: "flooding_near_school_crossing",
    label: "Confirmed",
    state: "Location ready",
    candidate: "Flooding at a confirmed school crossing",
    confirmation: "I see flooding at the confirmed crossing. Should I prepare this as a 311 report?",
    followup: "Is the water actively rising or blocking the curb ramp?",
  },
  {
    id: "blocked_crosswalk",
    scenario: "flooding_near_school_crossing",
    label: "Blocked",
    state: "Higher safety signal",
    candidate: "Crosswalk access blocked by standing water",
    confirmation: "It looks like water may be forcing pedestrians toward traffic. Is that the issue?",
    followup: "Is the crosswalk fully blocked or still partly passable?",
  },
  {
    id: "visible_drain_obstruction",
    scenario: "flooding_near_school_crossing",
    label: "Drain",
    state: "Catch basin visible",
    candidate: "Possible clogged catch basin causing flooding",
    confirmation: "I see flooding and possible debris near a drain. Is that what you want to report?",
    followup: "Is the drain covered by leaves, trash, or another obstruction?",
  },
  {
    id: "street_trash_bags",
    scenario: "trash_bags_on_street",
    label: "Trash",
    state: "Works anywhere",
    candidate: "Trash bags on the street or sidewalk",
    confirmation: "I see bagged trash or loose refuse near your current location. Is that what you want to report?",
    followup: "Are the bags blocking the sidewalk, curb, bike lane, or street?",
  },
];

export default function CitizenApp() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const liveSocketRef = useRef<WebSocket | null>(null);
  const livePanelRef = useRef<HTMLElement | null>(null);
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
  const activeVariant = detectedVariant ?? inferIssueVariant(issueDescription);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [phase]);

  useEffect(() => {
    return () => {
      stopLiveInputs();
    };
  }, []);

  function stopLiveInputs() {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    liveSocketRef.current?.close();
    liveSocketRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setCameraStatus("idle");
    setMicrophoneStatus("idle");
    setLiveAgentStatus("offline");
  }

  function currentLocationPayload(confirmed = false) {
    return currentLocation
      ? {
          label: null,
          latitude: currentLocation.latitude,
          longitude: currentLocation.longitude,
          accuracy_meters: currentLocation.accuracy,
          street_address: null,
          intersection: null,
          neighborhood: null,
          borough: null,
          source: "browser geolocation",
          confirmed,
        }
      : undefined;
  }

  function locationLabel() {
    if (currentLocation) {
      return "Phone location captured";
    }
    if (locationStatus === "requesting") {
      return "Requesting";
    }
    if (locationStatus === "active") {
      return "Available";
    }
    if (locationStatus === "denied") {
      return "Needs permission";
    }
    return "Needs confirmation";
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
    setCurrentLocation(null);
    setLocationStatus("idle");
    setIssueDescription("");
    setDetectedVariant(null);
    setInterimTranscript("");
    setLiveAgentMessage(null);
    setCandidateFollowup(null);
    setLiveAgentStatus("offline");
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
      prepareSpeechRecognition();
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
    const url = liveWebSocketUrl();
    if (!url) {
      setLiveAgentStatus("fallback");
      return;
    }

    liveSocketRef.current?.close();
    setLiveAgentStatus("connecting");
    const socket = new WebSocket(url);
    liveSocketRef.current = socket;

    socket.onopen = () => {
      setLiveAgentStatus("ready");
      socket.send(
        JSON.stringify({
          type: "start",
          payload: { location: currentLocationPayload(false) },
        }),
      );
    };
    socket.onmessage = (event) => {
      const liveEvent = JSON.parse(event.data) as LiveAgentEvent;
      setLiveAgentMessage(liveEvent.message);
      if (liveEvent.type === "candidate_detected" && liveEvent.payload.demo_variant) {
        const nextVariant = demoVariants.find(
          (variant) => variant.id === liveEvent.payload.demo_variant,
        );
        if (nextVariant) {
          setDetectedVariant(nextVariant);
          setCandidateFollowup(liveEvent.payload.followup ?? null);
          setPhase("candidate");
        }
        setLiveAgentStatus("ready");
      } else if (liveEvent.type === "followup_required") {
        setPhase("followup");
        setLiveAgentStatus("ready");
      } else if (liveEvent.type === "location_confirmation_required") {
        setError(liveEvent.message);
        setLiveAgentStatus("ready");
      } else if (liveEvent.type === "draft_ready" && liveEvent.payload.report) {
        setDraft(liveEvent.payload.report);
        setPhase("draft");
        setLoading(false);
        stopLiveInputs();
      } else if (liveEvent.type === "error") {
        setError(liveEvent.message);
        setLoading(false);
        setLiveAgentStatus("fallback");
      } else if (liveEvent.type === "session_started") {
        setLiveAgentStatus("ready");
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
      }
      setCameraStatus("active");
    } catch (err) {
      setCameraStatus("denied");
      throw err;
    }
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
            image_summary: activeVariant.candidate,
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
          : activeVariant.candidate,
        imageFrame,
        currentLocationPayload(false),
      );
      const nextVariant = demoVariants.find(
        (variant) => variant.id === classified.demo_variant,
      );
      setDetectedVariant(nextVariant ?? inferIssueVariant(issueDescription));
      setLiveAgentMessage(classified.confirmation);
      setCandidateFollowup(classified.followup);
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

  function captureCameraFrame() {
    const video = videoRef.current;
    if (!video || cameraStatus !== "active" || video.videoWidth === 0) {
      return undefined;
    }

    const canvas = document.createElement("canvas");
    const maxWidth = 640;
    const scale = Math.min(1, maxWidth / video.videoWidth);
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    const context = canvas.getContext("2d");
    if (!context) {
      return undefined;
    }
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.72);
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
    setLiveAgentMessage(null);
    setCandidateFollowup(null);
    setLiveAgentStatus("offline");
  }

  return (
    <main className="min-h-screen bg-field">
      <div className="mx-auto flex min-h-screen w-full max-w-5xl flex-col px-4 py-5 sm:px-6 lg:px-8">
        <header className="flex items-center justify-between gap-4 border-b border-ink/10 pb-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wide text-signal">
              311 Live
            </p>
            <h1 className="text-3xl font-black text-ink sm:text-4xl">
              Show it. Say it. Solve it.
            </h1>
          </div>
          <button
            type="button"
            onClick={resetDemo}
            className="focus-ring flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-ink/10 bg-white text-ink shadow-sm transition hover:bg-ink hover:text-white"
            aria-label="Reset demo"
          >
            <RotateCcw size={18} />
          </button>
        </header>

        <div className="grid flex-1 grid-cols-1 gap-5 py-5 lg:grid-cols-[360px_1fr]">
          <aside className="order-2 space-y-4 lg:order-1">
            <section className="rounded-md border border-ink/10 bg-white p-4 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink/55">
                Live Intake
              </p>
              <h2 className="mt-1 text-xl font-bold text-ink">
                Report with camera, voice, and location
              </h2>
              <div className="mt-4 grid grid-cols-1 gap-2">
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

              <button
                type="button"
                onClick={startReport}
                disabled={loading || phase !== "ready"}
                className="focus-ring mt-5 flex min-h-12 w-full items-center justify-center gap-2 rounded-md bg-ink px-4 py-3 font-bold text-white transition hover:bg-civic disabled:cursor-wait disabled:bg-ink/45"
              >
                <Play size={18} aria-hidden="true" />
                Start Report
              </button>
            </section>

            <section className="rounded-md border border-ink/10 bg-white p-4 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink/55">
                Workflow
              </p>
              <ol className="mt-3 space-y-3 text-sm text-ink/72">
                {["Start", "Observe", "Confirm", "Draft", "Review"].map((item, index) => (
                  <li key={item} className="flex items-center gap-3">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-field text-xs font-bold text-civic">
                      {index + 1}
                    </span>
                    <span>{item}</span>
                    {index < 4 && <ArrowRight size={14} className="ml-auto text-ink/30" />}
                  </li>
                ))}
              </ol>
            </section>
          </aside>

          <div className="order-1 space-y-5 lg:order-2">
            {error && (
              <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm font-semibold text-red-800">
                {error}
              </div>
            )}

            {phase !== "draft" && phase !== "confirmed" ? (
              <section
                ref={livePanelRef}
                className="scroll-mt-4 rounded-md border border-ink/10 bg-white p-5 shadow-sm"
              >
                <p className="text-xs font-semibold uppercase tracking-wide text-ink/55">
                  {phase === "ready" ? "Ready" : "Live agent simulator"}
                </p>
                <h2 className="mt-1 text-2xl font-bold text-ink">
                  {phase === "ready"
                    ? "Start a live report"
                    : phase === "observing"
                      ? "Describe what you see"
                      : activeVariant.candidate}
                </h2>
                <div className="mt-4 overflow-hidden rounded-md bg-ink text-white">
                  <div className="relative aspect-[4/5] min-h-[300px] bg-black sm:aspect-video sm:min-h-[360px]">
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
                        className={`absolute inset-0 flex flex-col justify-between p-3 sm:p-4 ${
                        cameraStatus === "active" ? "bg-black/25" : ""
                      }`}
                    >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <Camera size={18} />
                        <span className="text-sm font-bold">Camera view</span>
                      </div>
                      <span className="rounded-sm bg-white/12 px-2 py-1 text-xs font-semibold">
                        {cameraStatus === "active"
                          ? "Live"
                          : phase === "ready"
                            ? "Inactive"
                            : "Waiting"}
                      </span>
                    </div>
                    <div>
                        <p className="text-xl font-black sm:text-2xl">
                        {cameraStatus !== "active"
                          ? "Point your camera at the issue."
                          : phase === "candidate" || phase === "followup"
                            ? activeVariant.candidate
                            : "Describe what you see."}
                      </p>
                      <p className="mt-3 max-w-xl text-sm leading-6 text-white/72">
                        {phase === "ready"
                          ? "The live agent will observe, listen, confirm intent, and draft only after reviewable context is available."
                          : phase === "observing"
                            ? "Tell me what you are seeing, then I will identify the likely 311 issue."
                            : activeVariant.confirmation}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2 text-xs font-semibold">
                      <span className="rounded-sm bg-white/12 px-2 py-1">Camera</span>
                      <span className="rounded-sm bg-white/12 px-2 py-1">Mic</span>
                      <span className="rounded-sm bg-white/12 px-2 py-1">Location</span>
                      <span className="rounded-sm bg-signal px-2 py-1">DTPR visible</span>
                    </div>
                    </div>
                  </div>
                </div>

                <div className="mt-3 rounded-md border border-ink/10 bg-field p-4">
                  <div className="flex items-start gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-white text-civic">
                      <Mic size={18} />
                    </div>
                    <div>
                      <p className="text-sm font-bold text-ink">Agent</p>
                      <p className="mt-1 text-sm leading-6 text-ink/72">
                        {phase === "ready" &&
                          "Tap Start Report when you are ready to capture the issue."}
                        {phase === "permissions" &&
                          "I will use camera, microphone, and location only for this report flow. Continue?"}
                        {phase === "observing" &&
                          (liveAgentMessage ||
                            "Tell me what you are seeing, then I will identify the likely 311 issue.")}
                        {phase === "candidate" &&
                          (liveAgentMessage || activeVariant.confirmation)}
                        {phase === "followup" && (liveAgentMessage || activeVariant.followup)}
                      </p>
                    </div>
                  </div>
                </div>

                {(phase === "observing" ||
                  phase === "candidate" ||
                  phase === "followup") && (
                  <div className="mt-3 rounded-md border border-ink/10 bg-white p-3">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-xs font-semibold uppercase tracking-wide text-ink/55">
                        Resident description
                      </span>
                      <div className="flex shrink-0 items-center gap-2">
                        {phase === "observing" && issueDescription && (
                          <button
                            type="button"
                            onClick={retryDescription}
                            className="focus-ring min-h-10 rounded-md border border-ink/15 bg-white px-3 py-2 text-sm font-bold text-ink transition hover:border-civic hover:text-civic"
                          >
                            Clear
                          </button>
                        )}
                        {(phase === "candidate" || phase === "followup") && (
                          <button
                            type="button"
                            onClick={correctCandidate}
                            className="focus-ring min-h-10 rounded-md border border-ink/15 bg-white px-3 py-2 text-sm font-bold text-ink transition hover:border-civic hover:text-civic"
                          >
                            Correct
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={startVoiceCapture}
                          disabled={microphoneStatus === "active"}
                          className="focus-ring flex min-h-10 items-center justify-center gap-2 rounded-md bg-civic px-3 py-2 text-sm font-bold text-white transition hover:bg-ink disabled:cursor-wait disabled:bg-ink/35"
                        >
                          <Mic size={16} aria-hidden="true" />
                          {microphoneStatus === "active" ? "Listening..." : "Speak"}
                        </button>
                      </div>
                    </div>
                    {(interimTranscript || issueDescription) && (
                      <div className="mt-2 rounded-md bg-field p-3 text-sm leading-6 text-ink/72">
                        {issueDescription}
                        {interimTranscript && (
                          <span className="text-ink/45"> {interimTranscript}</span>
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
                      className="focus-ring mt-2 w-full resize-none rounded-md border border-ink/15 bg-field px-3 py-2 text-base leading-6 text-ink"
                      placeholder="Voice fallback: There are trash bags blocking the sidewalk here."
                    />
                  </div>
                )}

                <div className="mt-5 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {phase === "permissions" && (
                    <button
                      type="button"
                      onClick={beginObserving}
                      disabled={captureLoading}
                      className="focus-ring flex min-h-12 items-center justify-center gap-2 rounded-md bg-ink px-4 py-3 font-bold text-white transition hover:bg-civic"
                    >
                      {captureLoading ? (
                        <Loader2 className="animate-spin" size={18} aria-hidden="true" />
                      ) : (
                        <CheckCircle2 size={18} aria-hidden="true" />
                      )}
                      {captureLoading ? "Starting Capture..." : "Allow Camera + Location"}
                    </button>
                  )}
                  {phase === "observing" && (
                    <button
                      type="button"
                      onClick={showCandidate}
                      disabled={!issueDescription.trim()}
                      className="focus-ring flex min-h-12 items-center justify-center gap-2 rounded-md bg-ink px-4 py-3 font-bold text-white transition hover:bg-civic"
                    >
                      <Camera size={18} aria-hidden="true" />
                      Detect Candidate
                    </button>
                  )}
                  {phase === "candidate" && (
                    <>
                      <button
                        type="button"
                        onClick={confirmIntent}
                        className="focus-ring flex min-h-12 items-center justify-center gap-2 rounded-md bg-ink px-4 py-3 font-bold text-white transition hover:bg-civic"
                      >
                        <CheckCircle2 size={18} aria-hidden="true" />
                        Yes, Report This
                      </button>
                      <button
                        type="button"
                        onClick={correctCandidate}
                        className="focus-ring flex min-h-12 items-center justify-center rounded-md border border-ink/15 bg-white px-4 py-3 font-bold text-ink transition hover:border-civic hover:text-civic"
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
                      className="focus-ring flex min-h-12 items-center justify-center gap-2 rounded-md bg-ink px-4 py-3 font-bold text-white transition hover:bg-civic disabled:cursor-wait disabled:bg-ink/45"
                    >
                      {loading ? (
                        <Loader2 className="animate-spin" size={18} aria-hidden="true" />
                      ) : (
                        <FileText size={18} aria-hidden="true" />
                      )}
                      {loading ? "Drafting..." : "Create Draft"}
                    </button>
                  )}
                </div>
              </section>
            ) : (
              <>
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
