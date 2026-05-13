import { Database, Eye, FileCheck2, GitBranch, ShieldCheck } from "lucide-react";
import type { DataOrigin, DtprStep } from "@/lib/api";

interface DtprChainProps {
  steps: DtprStep[];
}

const originLabel: Record<DataOrigin, string> = {
  collected: "Collected",
  inferred: "Inferred",
  selected: "Selected",
  review_required: "Review",
};

const originIcon = {
  collected: Database,
  inferred: Eye,
  selected: GitBranch,
  review_required: FileCheck2,
};

const originStyle: Record<DataOrigin, string> = {
  collected: "bg-civic/10 text-civic",
  inferred: "bg-ink/8 text-ink/60",
  selected: "bg-signal/10 text-signal",
  review_required: "bg-caution/10 text-caution",
};

export function DtprChain({ steps }: DtprChainProps) {
  if (steps.length === 0) {
    return null;
  }

  return (
    <section className="space-y-3" aria-labelledby="dtpr-heading">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 bg-white px-5 py-4 shadow-card">
        <div>
          <p className="text-[9px] font-black uppercase tracking-[0.2em] text-ink/35">
            Data Transparency
          </p>
          <h2 id="dtpr-heading" className="mt-0.5 text-lg font-black text-ink">
            DTPR Data Chain
          </h2>
        </div>
        <div className="flex h-10 w-10 shrink-0 items-center justify-center bg-signal/10 text-signal">
          <ShieldCheck aria-hidden="true" size={20} />
        </div>
      </div>

      {/* Steps */}
      <div className="space-y-2">
        {steps.map((step) => {
          const Icon = originIcon[step.origin];
          return (
            <article
              key={step.id}
              className="overflow-hidden bg-white shadow-card"
            >
              <div className="flex items-start gap-3 p-4">
                <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center bg-field text-ink/50">
                  <Icon aria-hidden="true" size={17} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-black text-ink">{step.label}</h3>
                    <span
                      className={`px-2.5 py-0.5 text-[10px] font-black uppercase tracking-wider ${originStyle[step.origin]}`}
                    >
                      {originLabel[step.origin]}
                    </span>
                  </div>
                  <p className="mt-1.5 text-sm leading-6 text-ink/60">
                    {step.purpose}
                  </p>
                  <dl className="mt-3 grid grid-cols-1 gap-2 bg-field p-3 text-xs text-ink/55 sm:grid-cols-2">
                    <div>
                      <dt className="font-black text-ink/70">Data</dt>
                      <dd className="mt-0.5">{step.data_type}</dd>
                    </div>
                    <div>
                      <dt className="font-black text-ink/70">Processor</dt>
                      <dd className="mt-0.5">{step.processor}</dd>
                    </div>
                    <div>
                      <dt className="font-black text-ink/70">Retention</dt>
                      <dd className="mt-0.5">{step.retention}</dd>
                    </div>
                    <div>
                      <dt className="font-black text-ink/70">Control</dt>
                      <dd className="mt-0.5">{step.control_point}</dd>
                    </div>
                  </dl>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
