import {
  AlertTriangle,
  CheckCircle2,
  MapPin,
  Mic,
  ScanEye,
  Video,
} from "lucide-react";

interface StatusPillProps {
  kind: "camera" | "microphone" | "location" | "dtpr" | "review" | "confirmed";
  label: string;
  state: string;
}

const iconMap = {
  camera: Video,
  microphone: Mic,
  location: MapPin,
  dtpr: ScanEye,
  review: AlertTriangle,
  confirmed: CheckCircle2,
};

export function StatusPill({ kind, label, state }: StatusPillProps) {
  const Icon = iconMap[kind];
  const isConfirmed = kind === "confirmed";
  const isWarning = kind === "review";

  return (
    <div className="flex min-h-[50px] items-center gap-3 border border-ink/10 bg-white px-3 py-2">
      <div
        className={`flex h-8 w-8 shrink-0 items-center justify-center transition-colors ${
          isConfirmed
            ? "bg-signal/10 text-signal"
            : isWarning
              ? "bg-caution/10 text-caution"
              : "bg-field text-ink/50"
        }`}
      >
        <Icon aria-hidden="true" size={15} strokeWidth={2.2} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-[9px] font-black uppercase tracking-[0.2em] text-ink/35">
          {label}
        </p>
        <p className="mt-0.5 truncate text-sm font-bold text-ink">{state}</p>
      </div>
    </div>
  );
}
