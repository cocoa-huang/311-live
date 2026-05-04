import { useEffect, useMemo, useState } from "react";
import {
  Building2,
  CheckCircle2,
  HelpCircle,
  Loader2,
  MapPin,
  Save,
  SearchCheck,
} from "lucide-react";
import type { ReportDraft, ReportUpdateRequest } from "@/lib/api";

interface ReportReviewProps {
  report: ReportDraft;
  onConfirm: () => void;
  onSaveEdits: (updates: ReportUpdateRequest) => Promise<void>;
  confirming: boolean;
  saving: boolean;
}

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function locationDetail(report: ReportDraft) {
  const details = [
    report.location.intersection,
    report.location.street_address,
    report.location.neighborhood,
    report.location.borough,
  ].filter(Boolean);

  return Array.from(new Set(details)).join(" · ");
}

export function ReportReview({
  report,
  onConfirm,
  onSaveEdits,
  confirming,
  saving,
}: ReportReviewProps) {
  const confirmed = report.status === "confirmed";
  const [title, setTitle] = useState(report.title);
  const [description, setDescription] = useState(report.description);
  const [locationLabel, setLocationLabel] = useState(report.location.label ?? "");
  const [locationConfirmed, setLocationConfirmed] = useState(report.location.confirmed);
  const [priority, setPriority] = useState(report.priority);
  const detail = locationDetail(report);

  useEffect(() => {
    setTitle(report.title);
    setDescription(report.description);
    setLocationLabel(report.location.label ?? "");
    setLocationConfirmed(report.location.confirmed);
    setPriority(report.priority);
  }, [report]);

  const hasChanges = useMemo(
    () =>
      title !== report.title ||
      description !== report.description ||
      locationLabel !== (report.location.label ?? "") ||
      locationConfirmed !== report.location.confirmed ||
      priority !== report.priority,
    [description, locationConfirmed, locationLabel, priority, report, title],
  );

  async function handleSave() {
    await onSaveEdits({
      title,
      description,
      priority,
      location: {
        ...report.location,
        label: locationLabel || null,
        confirmed: locationConfirmed,
      },
    });
  }

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
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wide text-ink/55">
              Title
            </span>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              disabled={confirmed}
              className="focus-ring mt-1 min-h-11 w-full rounded-md border border-ink/15 bg-white px-3 py-2 text-sm font-semibold text-ink disabled:bg-field disabled:text-ink/65"
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wide text-ink/55">
              Description
            </span>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              disabled={confirmed}
              rows={4}
              className="focus-ring mt-1 w-full resize-none rounded-md border border-ink/15 bg-white px-3 py-2 text-sm leading-6 text-ink disabled:bg-field disabled:text-ink/65"
            />
          </label>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-3">
          <div className="flex gap-3 rounded-md bg-field p-3">
            <MapPin className="mt-0.5 shrink-0 text-civic" size={18} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-bold text-ink">Location</p>
              <input
                value={locationLabel}
                onChange={(event) => setLocationLabel(event.target.value)}
                disabled={confirmed}
                className="focus-ring mt-1 min-h-10 w-full rounded-md border border-ink/15 bg-white px-3 py-2 text-sm text-ink disabled:bg-white/45 disabled:text-ink/65"
              />
              <label className="mt-2 flex items-center gap-2 text-sm font-semibold text-ink/72">
                <input
                  type="checkbox"
                  checked={locationConfirmed}
                  onChange={(event) => setLocationConfirmed(event.target.checked)}
                  disabled={confirmed}
                  className="h-4 w-4 rounded border-ink/20 text-signal"
                />
                Resident confirmed exact location
              </label>
              {(detail || report.location.accuracy_meters || report.location.source) && (
                <dl className="mt-3 grid grid-cols-1 gap-2 text-xs text-ink/62 sm:grid-cols-2">
                  {detail && (
                    <div>
                      <dt className="font-semibold text-ink">Review context</dt>
                      <dd>{detail}</dd>
                    </div>
                  )}
                  {report.location.accuracy_meters && (
                    <div>
                      <dt className="font-semibold text-ink">GPS accuracy</dt>
                      <dd>{Math.round(report.location.accuracy_meters)} m</dd>
                    </div>
                  )}
                  {report.location.source && (
                    <div>
                      <dt className="font-semibold text-ink">Location source</dt>
                      <dd>{report.location.source}</dd>
                    </div>
                  )}
                </dl>
              )}
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
          <label className="block rounded-md bg-field p-3">
            <span className="text-sm font-bold text-ink">Priority</span>
            <select
              value={priority}
              onChange={(event) =>
                setPriority(event.target.value as ReportDraft["priority"])
              }
              disabled={confirmed}
              className="focus-ring mt-2 min-h-10 w-full rounded-md border border-ink/15 bg-white px-3 py-2 text-sm font-semibold capitalize text-ink disabled:bg-white/45 disabled:text-ink/65"
            >
              {["low", "medium", "high", "unknown"].map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
        </div>

        {report.civic_context && (
          <div className="mt-5 rounded-md border border-civic/20 bg-civic/10 p-3">
            <div className="flex items-center gap-2">
              <SearchCheck size={17} className="text-civic" />
              <p className="text-sm font-bold text-ink">311 historical context</p>
              <span className="ml-auto rounded-sm bg-white px-2 py-0.5 text-xs font-semibold text-civic">
                {percent(report.civic_context.confidence)}
              </span>
            </div>
            <p className="mt-2 text-sm leading-6 text-ink/72">
              {report.civic_context.evidence_summary}
            </p>
            <dl className="mt-3 grid grid-cols-1 gap-2 text-xs text-ink/65 sm:grid-cols-2">
              <div>
                <dt className="font-semibold text-ink">Source</dt>
                <dd>{report.civic_context.source}</dd>
              </div>
              <div>
                <dt className="font-semibold text-ink">Matches</dt>
                <dd>
                  {report.civic_context.used_live_data
                    ? `${report.civic_context.matched_count} records`
                    : "Fallback context"}
                </dd>
              </div>
              {report.civic_context.likely_problem_types.length > 0 && (
                <div>
                  <dt className="font-semibold text-ink">Problem types</dt>
                  <dd>{report.civic_context.likely_problem_types.join(", ")}</dd>
                </div>
              )}
              {report.civic_context.likely_agencies.length > 0 && (
                <div>
                  <dt className="font-semibold text-ink">Likely agencies</dt>
                  <dd>{report.civic_context.likely_agencies.join(", ")}</dd>
                </div>
              )}
            </dl>
            {report.civic_context.fallback_reason && (
              <p className="mt-2 text-xs font-semibold text-ink/55">
                {report.civic_context.fallback_reason}
              </p>
            )}
          </div>
        )}

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

        {report.uncertainty.length > 0 && (
          <div className="mt-4 rounded-md border border-ink/10 bg-field p-3">
            <p className="text-sm font-bold text-ink">Uncertainty</p>
            <ul className="mt-2 space-y-1">
              {report.uncertainty.map((item) => (
                <li key={item.field} className="text-sm leading-6 text-ink/72">
                  <span className="font-semibold text-ink">{item.field}</span>:{" "}
                  {item.reason} ({percent(item.confidence)} confidence)
                </li>
              ))}
            </ul>
          </div>
        )}

        <button
          type="button"
          onClick={handleSave}
          disabled={saving || confirmed || !hasChanges}
          className="focus-ring mt-5 flex min-h-12 w-full items-center justify-center gap-2 rounded-md border border-ink/15 bg-white px-4 py-3 font-bold text-ink transition hover:border-civic hover:text-civic disabled:cursor-not-allowed disabled:bg-field disabled:text-ink/35"
        >
          {saving ? (
            <Loader2 className="animate-spin" size={18} aria-hidden="true" />
          ) : (
            <Save size={18} aria-hidden="true" />
          )}
          {saving ? "Saving..." : "Save Edits"}
        </button>

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
