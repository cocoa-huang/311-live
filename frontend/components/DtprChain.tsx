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

export function DtprChain({ steps }: DtprChainProps) {
  if (steps.length === 0) {
    return null;
  }

  return (
    <section className="space-y-3" aria-labelledby="dtpr-heading">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-ink/55">
            DTPR Data Chain
          </p>
          <h2 id="dtpr-heading" className="text-xl font-bold text-ink">
            What the system used
          </h2>
        </div>
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-signal text-white">
          <ShieldCheck aria-hidden="true" size={20} />
        </div>
      </div>

      <div className="space-y-2">
        {steps.map((step) => {
          const Icon = originIcon[step.origin];
          return (
            <article
              key={step.id}
              className="rounded-md border border-ink/10 bg-white p-4 shadow-sm"
            >
              <div className="flex items-start gap-3">
                <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-field text-civic">
                  <Icon aria-hidden="true" size={18} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-bold text-ink">{step.label}</h3>
                    <span className="rounded-sm bg-civic/10 px-2 py-0.5 text-xs font-semibold text-civic">
                      {originLabel[step.origin]}
                    </span>
                  </div>
                  <p className="mt-1 text-sm leading-6 text-ink/72">
                    {step.purpose}
                  </p>
                  <dl className="mt-3 grid grid-cols-1 gap-2 text-xs text-ink/65 sm:grid-cols-2">
                    <div>
                      <dt className="font-semibold text-ink">Data</dt>
                      <dd>{step.data_type}</dd>
                    </div>
                    <div>
                      <dt className="font-semibold text-ink">Processor</dt>
                      <dd>{step.processor}</dd>
                    </div>
                    <div>
                      <dt className="font-semibold text-ink">Retention</dt>
                      <dd>{step.retention}</dd>
                    </div>
                    <div>
                      <dt className="font-semibold text-ink">Control</dt>
                      <dd>{step.control_point}</dd>
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
