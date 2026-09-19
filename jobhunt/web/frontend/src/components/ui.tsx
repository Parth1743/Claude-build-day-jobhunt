import type { ReactNode } from "react";
import type { JobStatus, RoadmapStatus } from "../types";

export function Badge({ children, tone = "neutral", icon }: { children: ReactNode; tone?: string; icon?: string }) {
  return (
    <span className={`badge badge-${tone}`}>
      {icon && <span aria-hidden="true">{icon}</span>}
      {children}
    </span>
  );
}

export const JOB_STATUS_TONE: Record<JobStatus, string> = {
  saved: "neutral",
  applied: "info",
  screening: "info",
  interview: "accent",
  offer: "good",
  rejected: "serious",
  withdrawn: "muted",
};

export const ROADMAP_STATUS_TONE: Record<RoadmapStatus, string> = {
  todo: "neutral",
  in_progress: "info",
  done: "good",
  skipped: "muted",
};

export const labelize = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export function StatusBadge({ status }: { status: JobStatus }) {
  return <Badge tone={JOB_STATUS_TONE[status]}>{labelize(status)}</Badge>;
}

export function Chip({ children, tone = "neutral", title }: { children: ReactNode; tone?: string; title?: string }) {
  return (
    <span className={`chip chip-${tone}`} title={title}>
      {children}
    </span>
  );
}

export function EmptyState({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {body && <p>{body}</p>}
      {action}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="spinner-wrap">
      <span className="spinner" aria-hidden="true" />
      {label && <span>{label}</span>}
    </span>
  );
}

export function Field({ label, hint, children, span2 }: { label: string; hint?: string; children: ReactNode; span2?: boolean }) {
  return (
    <label className={`field ${span2 ? "span-2" : ""}`}>
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export function ErrorBanner({ text, onDismiss }: { text: string | null; onDismiss?: () => void }) {
  if (!text) return null;
  return (
    <div className="banner banner-error" role="alert">
      <span>{text}</span>
      {onDismiss && (
        <button className="btn btn-ghost btn-sm" onClick={onDismiss}>
          Dismiss
        </button>
      )}
    </div>
  );
}

export function FitScore({ score, size = "md" }: { score: number | null; size?: "sm" | "md" | "lg" }) {
  if (score === null || score === undefined) return <span className="muted">—</span>;
  const tone = score >= 75 ? "good" : score >= 50 ? "warning" : "serious";
  return (
    <span className={`fit fit-${size} fit-${tone}`} title={`Fit score ${score} of 100`}>
      <span className="fit-track" aria-hidden="true">
        <span className="fit-bar" style={{ width: `${score}%` }} />
      </span>
      <span className="fit-num">{score}</span>
    </span>
  );
}

export function Progress({ value, max, label }: { value: number; max: number; label?: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="progress" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max} aria-label={label}>
      <div className="progress-track">
        <div className="progress-bar" style={{ width: `${pct}%` }} />
      </div>
      <span className="progress-text">
        {value}/{max}
      </span>
    </div>
  );
}

export const fmtDate = (iso: string | null | undefined) => (iso ? iso.slice(0, 10) : "");

export function dateRange(start: string | null, end: string | null) {
  if (!start && !end) return "";
  return `${start ?? ""} – ${end ?? (start ? "present" : "")}`;
}
