import type { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b border-rule pb-4">
      <div className="min-w-0">
        <h1 className="font-serif text-[26px] font-semibold leading-tight tracking-[-0.01em]">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-[13.5px] text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-rule-strong px-6 py-10 text-center">
      <p className="font-medium">{title}</p>
      {children && <div className="mx-auto mt-1 max-w-md text-[13px] text-muted">{children}</div>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-md border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger">
      {message}
      {onRetry && (
        <button type="button" onClick={onRetry} className="ml-2 font-medium underline underline-offset-2">
          Try again
        </button>
      )}
    </div>
  );
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-2 flex items-baseline justify-between gap-4">
      <h2 className="text-[12px] font-semibold uppercase tracking-[0.06em] text-muted">{children}</h2>
      {aside}
    </div>
  );
}

/** Segmented control for filters. */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string; count?: number }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="inline-flex rounded-md border border-rule-strong bg-surface p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          type="button"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={`rounded px-2.5 py-1 text-[13px] transition-colors ${
            value === o.value ? "bg-surface-2 font-medium text-ink" : "text-muted hover:text-ink"
          }`}
        >
          {o.label}
          {o.count !== undefined && <span className="tabular ml-1.5 text-muted">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-rule-strong bg-surface px-1 font-mono text-[11px] text-muted">{children}</kbd>
  );
}
