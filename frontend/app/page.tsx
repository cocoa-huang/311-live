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
  SlidersHorizontal,
} from "lucide-react";
import { DtprChain } from "@/components/DtprChain";
import { ReportReview } from "@/components/ReportReview";
import { StatusPill } from "@/components/StatusPill";
import {
  confirmDraft,
  createDemoDraft,
  updateDraft,
  type DemoVariant,
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

const demoVariants: Array<{
  id: DemoVariant;
  label: string;
  state: string;
  candidate: string;
  confirmation: string;
  followup: string;
}> = [
  {
    id: "baseline",
    label: "Baseline",
    state: "Needs exact location",
    candidate: "Flooding near a school crossing",
    confirmation: "I see standing water near a school crossing. Is that what you want to report?",
    followup: "Can you confirm the exact crossing before I draft the report?",
  },
  {
    id: "confirmed_location",
    label: "Confirmed",
    state: "Location ready",
    candidate: "Flooding at a confirmed school crossing",
    confirmation: "I see flooding at the confirmed crossing. Should I prepare this as a 311 report?",
    followup: "Is the water actively rising or blocking the curb ramp?",
  },
  {
    id: "blocked_crosswalk",
    label: "Blocked",
    state: "Higher safety signal",
    candidate: "Crosswalk access blocked by standing water",
    confirmation: "It looks like water may be forcing pedestrians toward traffic. Is that the issue?",
    followup: "Is the crosswalk fully blocked or still partly passable?",
  },
  {
    id: "visible_drain_obstruction",
    label: "Drain",
    state: "Catch basin visible",
    candidate: "Possible clogged catch basin causing flooding",
    confirmation: "I see flooding and possible debris near a drain. Is that what you want to report?",
    followup: "Is the drain covered by leaves, trash, or another obstruction?",
  },
];

export default function CitizenApp() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const livePanelRef = useRef<HTMLElement | null>(null);
  const [mounted, setMounted] = useState(false);
  const [phase, setPhase] = useState<Phase>("ready");
  const [draft, setDraft] = useState<ReportDraft | null>(null);
  const [demoVariant, setDemoVariant] = useState<DemoVariant>("baseline");
  const [cameraStatus, setCameraStatus] = useState<CaptureStatus>("idle");
  const [locationStatus, setLocationStatus] = useState<CaptureStatus>("idle");
  const [currentLocation, setCurrentLocation] = useState<GeolocationCoordinates | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [captureLoading, setCaptureLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeVariant = demoVariants.find((variant) => variant.id === demoVariant) ?? demoVariants[0];

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
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setCameraStatus("idle");
  }

  function locationLabel() {
    if (currentLocation) {
      return `${currentLocation.latitude.toFixed(5)}, ${currentLocation.longitude.toFixed(5)}`;
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
    return demoVariant === "confirmed_location"
      ? "Confirmed crossing"
      : "Needs confirmation";
  }

  function startReport() {
    setDraft(null);
    setError(null);
    setCurrentLocation(null);
    setLocationStatus("idle");
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

  function showCandidate() {
    setPhase("candidate");
  }

  function confirmIntent() {
    setPhase("followup");
  }

  async function generateDraft() {
    setLoading(true);
    setError(null);
    try {
      const report = await createDemoDraft(
        demoVariant,
        currentLocation
          ? {
              label: "Current phone location",
              latitude: currentLocation.latitude,
              longitude: currentLocation.longitude,
              confirmed: false,
            }
          : undefined,
      );
      setDraft(report);
      setPhase("draft");
      stopLiveInputs();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create report draft.");
    } finally {
      setLoading(false);
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
              <p className="mt-3 text-sm leading-6 text-ink/70">
                This simulator models the live agent flow before browser media and
                Gemini Live are wired.
              </p>

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
                  state={phase === "ready" ? "Ready on start" : "Voice simulated"}
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
              </div>

              <div className="mt-5">
                <div className="flex items-center gap-2">
                  <SlidersHorizontal size={16} className="text-civic" />
                  <p className="text-xs font-semibold uppercase tracking-wide text-ink/55">
                    Demo controls
                  </p>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  {demoVariants.map((variant) => {
                    const selected = demoVariant === variant.id;
                    return (
                      <button
                        key={variant.id}
                        type="button"
                        onClick={() => setDemoVariant(variant.id)}
                        disabled={loading}
                        className={`focus-ring min-h-16 rounded-md border px-3 py-2 text-left transition ${
                          selected
                            ? "border-civic bg-civic text-white"
                            : "border-ink/10 bg-field text-ink hover:border-civic"
                        }`}
                      >
                        <span className="block text-sm font-bold">{variant.label}</span>
                        <span
                          className={`mt-1 block text-xs leading-4 ${
                            selected ? "text-white/78" : "text-ink/60"
                          }`}
                        >
                          {variant.state}
                        </span>
                      </button>
                    );
                  })}
                </div>
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
                        {cameraStatus === "active"
                          ? activeVariant.candidate
                          : "Point your camera at the issue."}
                      </p>
                      <p className="mt-3 max-w-xl text-sm leading-6 text-white/72">
                        {phase === "ready"
                          ? "The live agent will observe, listen, confirm intent, and draft only after reviewable context is available."
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
                          "I am looking for the issue and listening for your description."}
                        {phase === "candidate" && activeVariant.confirmation}
                        {phase === "followup" && activeVariant.followup}
                      </p>
                    </div>
                  </div>
                </div>

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
                      className="focus-ring flex min-h-12 items-center justify-center gap-2 rounded-md bg-ink px-4 py-3 font-bold text-white transition hover:bg-civic"
                    >
                      <Camera size={18} aria-hidden="true" />
                      Detect Candidate
                    </button>
                  )}
                  {phase === "candidate" && (
                    <button
                      type="button"
                      onClick={confirmIntent}
                      className="focus-ring flex min-h-12 items-center justify-center gap-2 rounded-md bg-ink px-4 py-3 font-bold text-white transition hover:bg-civic"
                    >
                      <CheckCircle2 size={18} aria-hidden="true" />
                      Yes, Report This
                    </button>
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
