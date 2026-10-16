"use client";

import { useEffect, useState } from "react";
import { RotateCcw } from "lucide-react";

/**
 * A scripted, interactive replica of the Ask screen. Purpose: explanation —
 * it shows in a few seconds what the product does (search → cited answer →
 * open the exact passage). It plays once, then hands control to the visitor.
 */

const SOURCES = [
  {
    n: 1,
    doc: "Leave Policy 2025",
    where: "§ Annual leave",
    before: "Full-time employees receive ",
    mark: "20 days",
    after: " of paid annual leave per calendar year. Up to 5 unused days carry into the next year.",
  },
  {
    n: 2,
    doc: "Employee Handbook (2023)",
    where: "p. 14",
    before: "All full-time employees are entitled to ",
    mark: "25 days",
    after: " of paid annual leave each year.",
  },
];

// Phases: 0 question · 1 searching · 2 answer · 3 sources · 4 interactive
const TIMELINE = [400, 1300, 2300, 3000];

export function HeroDemo() {
  const [phase, setPhase] = useState(0);
  const [active, setActive] = useState<number | null>(null);
  const [run, setRun] = useState(0);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const timers = reduce
      ? [setTimeout(() => setPhase(4), 0), setTimeout(() => setActive(1), 0)]
      : [
          ...TIMELINE.map((t, i) => setTimeout(() => setPhase(i + 1), t)),
          setTimeout(() => setActive(1), TIMELINE[3] + 500),
        ];
    return () => timers.forEach(clearTimeout);
  }, [run]);

  function replay() {
    setPhase(0);
    setActive(null);
    setRun((r) => r + 1);
  }

  const show = (p: number) =>
    `transition-[opacity,transform] duration-500 ease-[var(--ease-out)] ${
      phase >= p ? "opacity-100 translate-y-0" : "pointer-events-none opacity-0 translate-y-1.5"
    }`;

  return (
    <figure
      className="fade-in relative overflow-hidden rounded-xl border border-rule-strong bg-surface shadow-[0_1px_0_rgb(0_0_0/0.04),0_24px_60px_-28px_rgb(0_0_0/0.25)]"
      style={{ "--delay": "450ms" } as React.CSSProperties}
      aria-label="Example of KnowOps answering a question with citations"
    >
      {/* Window chrome */}
      <div className="flex items-center justify-between border-b border-rule px-4 py-2.5">
        <div className="flex items-center gap-1.5" aria-hidden="true">
          <span className="size-2.5 rounded-full bg-rule-strong" />
          <span className="size-2.5 rounded-full bg-rule-strong" />
          <span className="size-2.5 rounded-full bg-rule-strong" />
        </div>
        <span className="font-mono text-[11px] text-muted">knowops / ask</span>
        <button
          type="button"
          onClick={replay}
          className="press -mr-1 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-muted hover:bg-surface-2 hover:text-ink"
          aria-label="Replay the example"
        >
          <RotateCcw className="size-3" />
          Replay
        </button>
      </div>

      <div className="space-y-4 px-5 pb-5 pt-5 text-[14px]">
        <p className={`font-serif text-[17px] font-semibold leading-snug ${show(0)}`}>
          How many days of annual leave do new hires get?
        </p>

        <div className="grid [&>*]:[grid-area:1/1]">
          <p
            className={`flex items-start gap-2 text-[13px] text-muted transition-opacity duration-300 ${
              phase === 1 ? "opacity-100" : "opacity-0"
            }`}
            aria-hidden={phase !== 1}
          >
            <span className="mt-[7px] inline-flex gap-1" aria-hidden="true">
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="size-1 animate-pulse rounded-full bg-muted"
                  style={{ animationDelay: `${i * 150}ms` }}
                />
              ))}
            </span>
            Searching 3 documents…
          </p>

          <p className={`leading-[1.7] text-ink ${show(2)}`}>
            Full-time employees get <strong className="font-semibold">20 days</strong> of paid annual leave
            <Cite n={1} active={active} onPick={setActive} enabled={phase >= 4} />, and up to 5 unused days carry
            over <Cite n={1} active={active} onPick={setActive} enabled={phase >= 4} />. The 2023 handbook still
            says <strong className="font-semibold">25 days</strong>
            <Cite n={2} active={active} onPick={setActive} enabled={phase >= 4} />, which conflicts with the
            current policy.
          </p>
        </div>

        <div className={show(3)}>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Sources</p>
          <ol className="divide-y divide-rule border-y border-rule">
            {SOURCES.map((s) => {
              const open = active === s.n;
              return (
                <li key={s.n}>
                  <button
                    type="button"
                    onClick={() => setActive(open ? null : s.n)}
                    aria-expanded={open}
                    className="flex w-full items-baseline gap-2.5 py-2 text-left text-[13px]"
                  >
                    <span className="font-mono text-[11px] text-accent">[{s.n}]</span>
                    <span className="font-medium">{s.doc}</span>
                    <span className="text-muted">{s.where}</span>
                  </button>
                  <div
                    className={`grid transition-[grid-template-rows] duration-300 ease-[var(--ease-out)] ${
                      open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
                    }`}
                  >
                    <div className="overflow-hidden">
                      <blockquote className="mb-2.5 ml-6 border-l-2 border-accent pl-3 text-[12.5px] leading-relaxed text-ink-2">
                        {s.before}
                        <span className="ink-mark" data-on={open} style={{ "--delay": "150ms" } as React.CSSProperties}>
                          {s.mark}
                        </span>
                        {s.after}
                      </blockquote>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </figure>
  );
}

function Cite({
  n,
  active,
  onPick,
  enabled,
}: {
  n: number;
  active: number | null;
  onPick: (n: number) => void;
  enabled: boolean;
}) {
  return (
    <button
      type="button"
      disabled={!enabled}
      onClick={() => onPick(n)}
      aria-label={`Show source ${n}`}
      className={`press relative -top-[0.45em] mx-0.5 rounded-[3px] px-1 font-mono text-[10.5px] font-medium ${
        active === n ? "bg-accent text-accent-ink" : "bg-accent-soft text-accent hover:bg-accent hover:text-accent-ink"
      }`}
    >
      {n}
    </button>
  );
}
