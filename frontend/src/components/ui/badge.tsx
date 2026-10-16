import type { ReactNode } from "react";

export type Tone = "neutral" | "accent" | "warn" | "danger" | "info";

const TONES: Record<Tone, string> = {
  neutral: "bg-surface-2 text-ink-2",
  accent: "bg-accent-soft text-accent",
  warn: "bg-warn-soft text-warn",
  danger: "bg-danger-soft text-danger",
  info: "bg-info-soft text-info",
};

export function Badge({ tone = "neutral", children, dot = false }: { tone?: Tone; children: ReactNode; dot?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded px-1.5 py-px text-[12px] font-medium ${TONES[tone]}`}>
      {dot && <span className="size-1.5 rounded-full bg-current" aria-hidden="true" />}
      {children}
    </span>
  );
}

const DOC_STATUS: Record<string, { label: string; tone: Tone }> = {
  uploaded: { label: "Queued", tone: "neutral" },
  processing: { label: "Processing", tone: "info" },
  ready: { label: "Ready", tone: "accent" },
  failed: { label: "Failed", tone: "danger" },
  archived: { label: "Archived", tone: "neutral" },
  pending: { label: "Queued", tone: "neutral" },
  extracting: { label: "Extracting", tone: "info" },
  chunking: { label: "Chunking", tone: "info" },
  embedding: { label: "Embedding", tone: "info" },
  indexing: { label: "Indexing", tone: "info" },
};

export function StatusBadge({ status }: { status: string }) {
  const meta = DOC_STATUS[status] ?? { label: status, tone: "neutral" as Tone };
  return (
    <Badge tone={meta.tone} dot>
      {meta.label}
    </Badge>
  );
}

const SEVERITY: Record<string, Tone> = { low: "neutral", medium: "warn", high: "danger", critical: "danger" };

export function SeverityBadge({ severity }: { severity: string }) {
  return <Badge tone={SEVERITY[severity] ?? "neutral"}>{severity[0]?.toUpperCase() + severity.slice(1)}</Badge>;
}
