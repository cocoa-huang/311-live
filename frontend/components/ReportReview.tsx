import { useEffect, useMemo, useState } from "react";
import {
  Building2,
  CheckCircle2,
  HelpCircle,
  Loader2,
  MapPin,
  Save,
} from "lucide-react";
import type { ReportDraft, ReportUpdateRequest } from "@/lib/api";

interface ReportReviewProps {
  report: ReportDraft;
  onConfirm: () => void;
  onSaveEdits: (updates: ReportUpdateRequest) => Promise<void>;
  confirming: boolean;
  saving: boolean;
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
  const detail = locationDetail(report);
  const provenance = report.inferred_context.find(
    (item) => item.label === "Candidate provenance",
  );
  const schoolTransit = report.inferred_context.find(
    (item) => item.label === "School or transit proximity",
  );
  const actionableReview = report.human_review.filter(
    (item) => item.field === "location.confirmed",
  );

  useEffect(() => {
    setTitle(report.title);
    setDescription(report.description);
    setLocationLabel(report.location.label ?? "");
    setLocationConfirmed(report.location.confirmed);
  }, [report]);

  const hasChanges = useMemo(
    () =>
      title !== report.title ||
      description !== report.description ||
      locationLabel !== (report.location.label ?? "") ||
      locationConfirmed !== report.location.confirmed,
    [description, locationConfirmed, locationLabel, report, title],
  );

  async function handleSave() {
    await onSaveEdits({
      title,
      description,
      location: {
        ...report.location,
        label: locationLabel || null,
        confirmed: locationConfirmed,
      },
    });
  }

  return (
    <section className="space-y-4" aria-labelledby="draft-heading">
      <div className="bg-white shadow-card">
        {/* Card header */}
        <div className="border-l-[3px] border-brand px-5 py-4">
          <div className="min-w-0">
            <p className="text-[9px] font-black uppercase tracking-[0.2em] text-ink/35">
              Review your report
            </p>
            <h2 id="draft-heading" className="mt-0.5 text-lg font-black text-ink">
              {report.title}
            </h2>
          </div>
        </div>

        <div className="border-t border-ink/8 px-5 py-4">
          <p className="text-sm font-semibold text-ink/55">
            Check this before confirming the demo report. Phone location can be approximate.
          </p>

          {/* Editable fields */}
          <div className="mt-4 grid grid-cols-1 gap-3">
            <label className="block">
              <span className="text-[9px] font-black uppercase tracking-[0.2em] text-ink/35">
                Title
              </span>
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                disabled={confirmed}
                className="focus-ring mt-1.5 min-h-11 w-full border border-ink/15 bg-white px-3 py-2 text-sm font-semibold text-ink disabled:bg-field disabled:text-ink/50"
              />
            </label>
            <label className="block">
              <span className="text-[9px] font-black uppercase tracking-[0.2em] text-ink/35">
                Description
              </span>
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                disabled={confirmed}
                rows={4}
                className="focus-ring mt-1.5 w-full resize-none border border-ink/15 bg-white px-3 py-2 text-sm leading-6 text-ink disabled:bg-field disabled:text-ink/50"
              />
            </label>
          </div>

          {/* Location + routing */}
          <div className="mt-4 grid grid-cols-1 gap-3">
            <div className="border border-ink/10 bg-field p-3">
              <div className="flex gap-3">
                <MapPin className="mt-0.5 shrink-0 text-ink/40" size={16} />
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-black uppercase tracking-wide text-ink/40">
                    Location
                  </p>
                  <input
                    value={locationLabel}
                    onChange={(event) => setLocationLabel(event.target.value)}
                    disabled={confirmed}
                    className="focus-ring mt-1.5 min-h-10 w-full border border-ink/15 bg-white px-3 py-2 text-sm text-ink disabled:bg-white/60 disabled:text-ink/50"
                  />
                  <label className="mt-2 flex items-center gap-2 text-sm font-bold text-ink/60">
                    <input
                      type="checkbox"
                      checked={locationConfirmed}
                      onChange={(event) => setLocationConfirmed(event.target.checked)}
                      disabled={confirmed}
                      className="h-4 w-4 border-ink/20 accent-brand"
                    />
                    This is the correct report location
                  </label>
                  {(detail || report.location.accuracy_meters || report.location.source) && (
                    <dl className="mt-3 grid grid-cols-1 gap-2 text-xs text-ink/50 sm:grid-cols-2">
                      {detail && (
                        <div>
                          <dt className="font-black text-ink/60">Review context</dt>
                          <dd>{detail}</dd>
                        </div>
                      )}
                      {report.location.accuracy_meters && (
                        <div>
                          <dt className="font-black text-ink/60">GPS accuracy</dt>
                          <dd>{Math.round(report.location.accuracy_meters)} m</dd>
                        </div>
                      )}
                      {report.location.source && (
                        <div>
                          <dt className="font-black text-ink/60">Location source</dt>
                          <dd>{report.location.source}</dd>
                        </div>
                      )}
                    </dl>
                  )}
                </div>
              </div>
            </div>
            {report.routing && (
              <div className="border border-ink/10 bg-field p-3">
                <div className="flex gap-3">
                  <Building2 className="mt-0.5 shrink-0 text-ink/40" size={16} />
                  <div>
                    <p className="text-xs font-black uppercase tracking-wide text-ink/40">
                      City department
                    </p>
                    <p className="mt-1 text-sm font-semibold text-ink/75">
                      {report.routing.agency ?? report.routing.department}
                    </p>
                    <p className="mt-0.5 text-xs text-ink/45">{report.routing.service}</p>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Actionable review prompts */}
          {actionableReview.length > 0 && (
            <div className="mt-4 border border-caution/25 bg-caution/8 p-3">
              <div className="flex items-center gap-2">
                <HelpCircle size={16} className="text-caution" />
                <p className="text-sm font-black text-ink">Please check before confirming</p>
              </div>
              <ul className="mt-2 space-y-1">
                {actionableReview.map((item) => (
                  <li key={item.field} className="text-sm leading-6 text-ink/65">
                    {item.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* More report details (collapsed) */}
          <details className="mt-4 border border-ink/10 bg-field">
            <summary className="cursor-pointer px-4 py-3 text-sm font-black text-ink hover:bg-ink/5">
              More report details
            </summary>
            <div className="space-y-4 px-4 pb-4 pt-2">
              {schoolTransit && (
                <div className="border border-signal/20 bg-signal/8 p-3">
                  <p className="text-xs font-black uppercase tracking-wide text-signal/70">
                    School / Transit context
                  </p>
                  <p className="mt-1 text-sm leading-6 text-ink/70">
                    {schoolTransit.value}
                  </p>
                </div>
              )}

              {provenance && (
                <div className="border border-ink/10 bg-white p-3">
                  <p className="text-sm font-black text-ink">
                    What this draft is based on
                  </p>
                  <p className="mt-2 text-sm leading-6 text-ink/60">
                    {provenance.value === "camera observed"
                      ? "The intake flow marked this candidate as camera-observed before draft review."
                      : provenance.value === "visual unclear"
                        ? "The camera context was not clear enough to establish the candidate on its own."
                        : "This candidate is based on the resident's report rather than a camera-established issue."}
                  </p>
                </div>
              )}

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <p className="text-[9px] font-black uppercase tracking-[0.2em] text-ink/35">
                    What you shared
                  </p>
                  <ul className="mt-2 space-y-2">
                    {report.collected_inputs.map((item) => (
                      <li
                        key={`${item.kind}-${item.value}`}
                        className="text-sm text-ink/60"
                      >
                        <span className="font-black capitalize text-ink/75">
                          {item.kind}:
                        </span>{" "}
                        {item.value}
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <p className="text-[9px] font-black uppercase tracking-[0.2em] text-ink/35">
                    What the agent understood
                  </p>
                  <ul className="mt-2 space-y-2">
                    {report.inferred_context
                      .filter(
                        (item) =>
                          item.label !== "Candidate provenance" &&
                          item.label !== "School or transit proximity" &&
                          item.label !== "Intake slot quality" &&
                          item.label !== "311 historical context" &&
                          item.label !== "Model category recommendation" &&
                          item.label !== "Model agency recommendation",
                      )
                      .map((item) => (
                        <li key={item.label} className="text-sm text-ink/60">
                          <span className="font-black text-ink/75">{item.label}:</span>{" "}
                          {item.value}
                        </li>
                      ))}
                  </ul>
                </div>
              </div>

              {report.uncertainty.length > 0 && (
                <div className="border border-ink/10 bg-white p-3">
                  <p className="text-sm font-black text-ink">
                    Details that may need confirmation
                  </p>
                  <ul className="mt-2 space-y-1">
                    {report.uncertainty.map((item) => (
                      <li key={item.field} className="text-sm leading-6 text-ink/60">
                        <span className="font-black text-ink/70">{item.field}</span>:{" "}
                        {item.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </details>

          {/* Action buttons */}
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || confirmed || !hasChanges}
            className="focus-ring mt-4 flex min-h-12 w-full items-center justify-center gap-2 border border-ink/20 bg-white px-4 py-3 font-black text-ink transition hover:bg-field disabled:cursor-not-allowed disabled:text-ink/30"
          >
            {saving ? (
              <Loader2 className="animate-spin" size={18} aria-hidden="true" />
            ) : (
              <Save size={18} aria-hidden="true" />
            )}
            {saving ? "Saving…" : "Save Edits"}
          </button>

          <button
            type="button"
            onClick={onConfirm}
            disabled={confirming || confirmed}
            className="focus-ring mt-3 flex min-h-12 w-full items-center justify-center gap-2 bg-signal px-4 py-3 font-black text-white transition hover:bg-signal/85 disabled:cursor-not-allowed disabled:bg-ink/20 disabled:text-ink/40"
          >
            <CheckCircle2 size={18} aria-hidden="true" />
            {confirmed ? "Confirmed" : confirming ? "Confirming…" : "Confirm Report"}
          </button>
        </div>
      </div>
    </section>
  );
}
