import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

const CONTROL =
  "rounded-md border border-rule-strong bg-surface px-2.5 text-[13.5px] text-ink placeholder:text-muted transition-colors focus:border-accent focus:outline-none focus-visible:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-60";

/** Full width unless the caller sets its own width (Tailwind can't merge `w-*`). */
function width(className: string): string {
  return /(^|\s)(w-|min-w-|max-w-|size-|flex-1)/.test(className) ? "" : "w-full";
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className = "", ...rest }, ref) {
    return <input ref={ref} className={`${CONTROL} ${width(className)} h-8 ${className}`} {...rest} />;
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className = "", ...rest }, ref) {
    return <textarea ref={ref} className={`${CONTROL} ${width(className)} py-1.5 leading-relaxed ${className}`} {...rest} />;
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className = "", children, ...rest }, ref) {
    return (
      <select ref={ref} className={`${CONTROL} ${width(className)} h-8 pr-7 ${className}`} {...rest}>
        {children}
      </select>
    );
  },
);

/** Label + control + hint/error, wired together for screen readers. */
export function Field({
  label,
  hint,
  error,
  children,
  className = "",
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: (id: string, describedBy: string | undefined) => ReactNode;
  className?: string;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      <label htmlFor={id} className="text-[13px] font-medium text-ink-2">
        {label}
      </label>
      {children(id, hint || error ? hintId : undefined)}
      {error ? (
        <p id={hintId} className="text-[12.5px] text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-[12.5px] text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function FormError({ message }: { message: string | null | undefined }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-[13px] text-danger">
      {message}
    </p>
  );
}
