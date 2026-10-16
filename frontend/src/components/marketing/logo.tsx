import Link from "next/link";

/** Wordmark: a bracketed index mark, echoing the citation markers in answers. */
export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="inline-flex items-center gap-2 font-semibold tracking-tight text-ink">
      <span
        aria-hidden="true"
        className="inline-flex h-5 min-w-5 items-center justify-center rounded-[3px] bg-ink px-1 font-mono text-[11px] font-medium text-bg"
      >
        [1]
      </span>
      KnowOps
    </Link>
  );
}
