import { Building2, CheckCircle2, HelpCircle, MapPin } from "lucide-react";
import type { ReportDraft } from "@/lib/api";

interface ReportReviewProps {
  report: ReportDraft;
  onConfirm: () => void;
  confirming: boolean;
}

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function ReportReview({ report, onConfirm, confirming }: ReportReviewProps) {
  const confirmed = report.status === "confirmed";

  return (
    <section className="space-y-4" aria-labelledby="draft-heading">
      <div className="rounded-md border border-ink/10 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-ink/55">
              Draft Report
            </p>
            <h2 id="draft-heading" className="mt-1 text-2xl font-bold text-ink">
              {report.title}
            </h2>
          </div>
          <span className="rounded-md bg-caution/12 px-3 py-1 text-sm font-bold capitalize text-caution">
            {report.priority}
          </span>
        </div>

        <p className="mt-4 text-base leading-7 text-ink/75">{report.narrative}</p>

        <div className="mt-5 grid grid-cols-1 gap-3">
          <div className="flex gap-3 rounded-md bg-field p-3">
            <MapPin className="mt-0.5 shrink-0 text-civic" size={18} />
            <div>
              <p className="text-sm font-bold text-ink">Location</p>
              <p className="text-sm leading-6 text-ink/70">
                {report.location.label ?? "Location not labeled"}
              </p>
            </div>
          </div>
          {report.routing && (
            <div className="flex gap-3 rounded-md bg-field p-3">
              <Building2 className="mt-0.5 shrink-0 text-civic" size={18} />
              <div>
                <p className="text-sm font-bold text-ink">
                  {report.routing.agency ?? report.routing.department}
                </p>
                <p className="text-sm leading-6 text-ink/70">
                  {report.routing.service} · {percent(report.routing.confidence)} confidence
                </p>
              </div>
            </div>
          )}
        </div>

        <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-ink/55">
              Collected
            </p>
            <ul className="mt-2 space-y-2">
              {report.collected_inputs.map((item) => (
                <li key={`${item.kind}-${item.value}`} className="text-sm text-ink/72">
                  <span className="font-semibold capitalize text-ink">{item.kind}:</span>{" "}
                  {item.value}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-ink/55">
              Inferred
            </p>
            <ul className="mt-2 space-y-2">
              {report.inferred_context.map((item) => (
                <li key={item.label} className="text-sm text-ink/72">
                  <span className="font-semibold text-ink">{item.label}:</span>{" "}
                  {item.value}
                </li>
              ))}
            </ul>
          </div>
        </div>

        {report.human_review.length > 0 && (
          <div className="mt-5 rounded-md border border-caution/30 bg-caution/8 p-3">
            <div className="flex items-center gap-2">
              <HelpCircle size={17} className="text-caution" />
              <p className="text-sm font-bold text-ink">Needs review</p>
            </div>
            <ul className="mt-2 space-y-1">
              {report.human_review.map((item) => (
                <li key={item.field} className="text-sm leading-6 text-ink/72">
                  {item.reason}
                </li>
              ))}
            </ul>
          </div>
        )}

        <button
          type="button"
          onClick={onConfirm}
          disabled={confirming || confirmed}
          className="focus-ring mt-5 flex min-h-12 w-full items-center justify-center gap-2 rounded-md bg-signal px-4 py-3 font-bold text-white transition hover:bg-signal/90 disabled:cursor-not-allowed disabled:bg-ink/35"
        >
          <CheckCircle2 size={18} aria-hidden="true" />
          {confirmed ? "Confirmed" : confirming ? "Confirming..." : "Confirm Report"}
        </button>
      </div>
    </section>
  );
}
