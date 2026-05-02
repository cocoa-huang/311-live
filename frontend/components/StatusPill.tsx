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

  return (
    <div className="flex min-h-14 items-center gap-3 rounded-md border border-ink/10 bg-white px-3 py-2 shadow-sm">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-field text-civic">
        <Icon aria-hidden="true" size={18} strokeWidth={2.2} />
      </div>
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-wide text-ink/55">
          {label}
        </p>
        <p className="truncate text-sm font-semibold text-ink">{state}</p>
      </div>
    </div>
  );
}
