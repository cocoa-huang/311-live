"use client";

import { useState } from "react";
import { ArrowRight, FileText, Loader2, RotateCcw } from "lucide-react";
import { DtprChain } from "@/components/DtprChain";
import { ReportReview } from "@/components/ReportReview";
import { StatusPill } from "@/components/StatusPill";
import { confirmDraft, createDemoDraft, type ReportDraft } from "@/lib/api";

type Phase = "ready" | "draft" | "confirmed";

export default function CitizenApp() {
  const [phase, setPhase] = useState<Phase>("ready");
  const [draft, setDraft] = useState<ReportDraft | null>(null);
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generateDraft() {
    setLoading(true);
    setError(null);
    try {
      const report = await createDemoDraft();
      setDraft(report);
      setPhase("draft");
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

  function resetDemo() {
    setDraft(null);
    setPhase("ready");
    setError(null);
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
          <aside className="space-y-4">
            <section className="rounded-md border border-ink/10 bg-white p-4 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink/55">
                Intake
              </p>
              <h2 className="mt-1 text-xl font-bold text-ink">
                Flooding near a school crossing
              </h2>
              <p className="mt-3 text-sm leading-6 text-ink/70">
                This sprint uses a deterministic backend fixture so we can test the
                product workflow before wiring live camera, microphone, and Gemini.
              </p>

              <div className="mt-4 grid grid-cols-1 gap-2">
                <StatusPill kind="camera" label="Camera" state="Placeholder ready" />
                <StatusPill
                  kind="microphone"
                  label="Microphone"
                  state="Transcript fixture"
                />
                <StatusPill
                  kind="location"
                  label="Location"
                  state="Demo crossing"
                />
                <StatusPill
                  kind={phase === "confirmed" ? "confirmed" : "dtpr"}
                  label="Data chain"
                  state={phase === "ready" ? "Generated after draft" : "Visible"}
                />
              </div>

              <button
                type="button"
                onClick={generateDraft}
                disabled={loading}
                className="focus-ring mt-5 flex min-h-12 w-full items-center justify-center gap-2 rounded-md bg-ink px-4 py-3 font-bold text-white transition hover:bg-civic disabled:cursor-wait disabled:bg-ink/45"
              >
                {loading ? (
                  <Loader2 className="animate-spin" size={18} aria-hidden="true" />
                ) : (
                  <FileText size={18} aria-hidden="true" />
                )}
                {loading ? "Generating Draft..." : "Generate Demo Draft"}
              </button>
            </section>

            <section className="rounded-md border border-ink/10 bg-white p-4 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink/55">
                Workflow
              </p>
              <ol className="mt-3 space-y-3 text-sm text-ink/72">
                {["Collect", "Infer", "Route", "Review", "Confirm"].map((item, index) => (
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

          <div className="space-y-5">
            {error && (
              <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm font-semibold text-red-800">
                {error}
              </div>
            )}

            {!draft ? (
              <section className="flex min-h-[420px] items-center justify-center rounded-md border border-dashed border-ink/20 bg-white p-6 text-center">
                <div className="max-w-md">
                  <p className="text-xs font-semibold uppercase tracking-wide text-ink/55">
                    Ready
                  </p>
                  <h2 className="mt-2 text-2xl font-bold text-ink">
                    Create the first report draft
                  </h2>
                  <p className="mt-3 text-sm leading-6 text-ink/70">
                    The frontend will call the FastAPI workflow contract and render the
                    returned narrative, routing, review fields, and DTPR data chain.
                  </p>
                </div>
              </section>
            ) : (
              <>
                <ReportReview
                  report={draft}
                  onConfirm={handleConfirm}
                  confirming={confirming}
                />
                <DtprChain steps={draft.dtpr_chain} />
              </>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
