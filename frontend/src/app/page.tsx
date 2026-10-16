import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { HeroDemo } from "@/components/marketing/hero-demo";
import { LandingHeader } from "@/components/marketing/landing-header";
import { Logo } from "@/components/marketing/logo";
import { Reveal } from "@/components/marketing/reveal";

const HEADLINE = ["Company", "knowledge", "you", "can", "check."];

const STEPS = [
  {
    n: "01",
    title: "Upload what you already have",
    body: "Policies, handbooks, runbooks, FAQs — PDF, Word, Markdown, text or CSV. Each file is split into passages and indexed, with its page or section kept.",
  },
  {
    n: "02",
    title: "Ask in plain language",
    body: "Answers are written only from documents you're allowed to open. Every sentence carries a numbered citation to the passage behind it.",
  },
  {
    n: "03",
    title: "Fix what's wrong at the source",
    body: "Contradictions, stale documents and questions nobody could answer are collected in one place, so the knowledge base gets better every week.",
  },
];

const FEATURES = [
  {
    title: "Citations you can click",
    body: "Each claim opens the exact passage, its document and its location. No source, no claim.",
  },
  {
    title: "Contradiction scans",
    body: "Similar passages across documents are compared, and disagreements are flagged with both sides quoted.",
  },
  {
    title: "Gaps, logged automatically",
    body: "A question with no supporting document becomes a finding, counted each time someone asks it again.",
  },
  {
    title: "Versions, compared",
    body: "Upload a revision and see a line-level diff plus a short summary of what actually changed.",
  },
  {
    title: "Answers into work",
    body: "Turn an answer into a task or an email draft. Nothing is created until a person approves it.",
  },
  {
    title: "Access that carries through",
    body: "Roles, groups and per-document grants apply to search too — people only get answers from what they may read.",
  },
];

export default function Home() {
  return (
    <div className="grain min-h-dvh overflow-x-clip">
      <LandingHeader />

      <main>
        {/* Hero ------------------------------------------------------------- */}
        <section className="mx-auto grid max-w-6xl gap-14 px-6 pb-20 pt-14 lg:grid-cols-[1.05fr_1fr] lg:items-center lg:gap-16 lg:pb-28 lg:pt-20">
          <div>
            <p className="fade-in mb-6 inline-flex items-center gap-2 font-mono text-[11.5px] uppercase tracking-[0.12em] text-muted">
              <span className="size-1.5 rounded-full bg-accent" aria-hidden="true" />
              Answers with receipts
            </p>
            <h1 className="font-serif text-[clamp(44px,7.4vw,96px)] font-semibold leading-[0.98] tracking-[-0.025em]">
              <span className="sr-only">Company knowledge you can check.</span>
              <span aria-hidden="true">
                {HEADLINE.map((word, i) => (
                  <span key={word} className="word-in mr-[0.22em]" style={{ "--i": i } as React.CSSProperties}>
                    {word === "check." ? <em className="not-italic text-accent">{word}</em> : word}
                  </span>
                ))}
              </span>
            </h1>
            <p
              className="fade-in mt-7 max-w-[30rem] text-[17px] leading-relaxed text-ink-2"
              style={{ "--delay": "320ms" } as React.CSSProperties}
            >
              KnowOps answers questions from your company&apos;s documents and shows the exact passage behind every
              sentence — so people can trust the answer, or fix the source.
            </p>
            <div className="fade-in mt-9 flex flex-wrap items-center gap-3" style={{ "--delay": "400ms" } as React.CSSProperties}>
              <Link
                href="/register"
                className="press group inline-flex items-center gap-2 rounded-md bg-accent px-5 py-2.5 text-[14.5px] font-medium text-accent-ink hover:opacity-90"
              >
                Start a workspace
                <ArrowRight className="size-4 transition-transform duration-200 ease-[var(--ease-out)] group-hover:translate-x-0.5" />
              </Link>
              <Link
                href="/login"
                className="press inline-flex items-center rounded-md border border-rule-strong bg-surface px-5 py-2.5 text-[14.5px] font-medium hover:bg-surface-2"
              >
                Sign in
              </Link>
            </div>
          </div>

          <HeroDemo />
        </section>

        {/* Formats strip ---------------------------------------------------- */}
        <div className="border-y border-rule">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-8 gap-y-2 px-6 py-4 font-mono text-[12px] uppercase tracking-[0.1em] text-muted">
            <span className="text-ink-2">Reads</span>
            {["PDF", "Word", "Markdown", "Plain text", "CSV"].map((f) => (
              <span key={f}>{f}</span>
            ))}
            <span className="ml-auto hidden normal-case tracking-normal sm:inline">Self-hosted · your model, your data</span>
          </div>
        </div>

        {/* How it works ----------------------------------------------------- */}
        <section id="how" className="mx-auto max-w-6xl scroll-mt-20 px-6 py-24 lg:py-32">
          <Reveal>
            <h2 className="max-w-3xl font-serif text-[clamp(32px,4.6vw,56px)] font-semibold leading-[1.05] tracking-[-0.02em]">
              From a folder of documents to answers people trust.
            </h2>
          </Reveal>
          <ol className="mt-16 grid gap-px overflow-hidden rounded-lg border border-rule bg-rule md:grid-cols-3">
            {STEPS.map((step, i) => (
              <Reveal as="li" key={step.n} delay={i * 90} className="reveal bg-bg p-7 lg:p-9">
                <span className="font-mono text-[13px] text-accent">{step.n}</span>
                <h3 className="mt-10 text-[19px] font-semibold leading-snug tracking-[-0.01em]">{step.title}</h3>
                <p className="mt-3 text-[14.5px] leading-relaxed text-ink-2">{step.body}</p>
              </Reveal>
            ))}
          </ol>
        </section>

        {/* Conflict showcase ------------------------------------------------ */}
        <section className="border-y border-rule bg-surface">
          <div className="mx-auto grid max-w-6xl gap-14 px-6 py-24 lg:grid-cols-[0.9fr_1.1fr] lg:items-center lg:py-32">
            <Reveal>
              <p className="font-mono text-[11.5px] uppercase tracking-[0.12em] text-muted">Knowledge health</p>
              <h2 className="mt-4 font-serif text-[clamp(32px,4.6vw,56px)] font-semibold leading-[1.05] tracking-[-0.02em]">
                Two documents. Two answers. Now you know.
              </h2>
              <p className="mt-6 max-w-md text-[16px] leading-relaxed text-ink-2">
                Most knowledge bases don&apos;t fail loudly — they quietly disagree with themselves. KnowOps compares
                similar passages across documents and flags the ones that contradict each other, with both sides quoted.
              </p>
            </Reveal>

            <div className="space-y-3">
              <Excerpt
                delay={0}
                doc="Leave Policy 2025"
                where="§ Annual leave"
                text={["Full-time employees receive ", "20 days", " of paid annual leave per calendar year."]}
              />
              <Excerpt
                delay={180}
                doc="Employee Handbook (2023)"
                where="p. 14"
                text={["All full-time employees are entitled to ", "25 days", " of paid annual leave each year."]}
              />
              <Reveal delay={520} className="reveal">
                <div className="flex flex-wrap items-center gap-3 rounded-lg border border-warn/30 bg-warn-soft px-4 py-3 text-[13.5px]">
                  <span className="rounded bg-warn px-1.5 py-px font-mono text-[11px] font-medium text-bg">CONFLICT</span>
                  <span className="font-medium text-ink">Annual leave entitlement differs</span>
                  <span className="text-ink-2">· found by the last scan</span>
                </div>
              </Reveal>
            </div>
          </div>
        </section>

        {/* Features --------------------------------------------------------- */}
        <section id="features" className="mx-auto max-w-6xl scroll-mt-20 px-6 py-24 lg:py-32">
          <Reveal>
            <h2 className="max-w-2xl font-serif text-[clamp(32px,4.6vw,56px)] font-semibold leading-[1.05] tracking-[-0.02em]">
              Built for knowledge that has to be right.
            </h2>
          </Reveal>
          <div className="mt-16 grid gap-px overflow-hidden rounded-lg border border-rule bg-rule sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f, i) => (
              <Reveal
                key={f.title}
                delay={(i % 3) * 70}
                className="reveal bg-bg p-7 lg:p-9"
              >
                <span className="font-mono text-[12px] text-muted">{String(i + 1).padStart(2, "0")}</span>
                <h3 className="mt-4 text-[17px] font-semibold tracking-[-0.01em]">{f.title}</h3>
                <p className="mt-2 text-[14.5px] leading-relaxed text-ink-2">{f.body}</p>
              </Reveal>
            ))}
          </div>
        </section>

        {/* Closing CTA ------------------------------------------------------ */}
        <section className="border-t border-rule">
          <div className="mx-auto max-w-6xl px-6 py-24 lg:py-32">
            <Reveal>
              <h2 className="max-w-4xl font-serif text-[clamp(40px,6.6vw,84px)] font-semibold leading-[1] tracking-[-0.025em]">
                Stop guessing which document is right.
              </h2>
              <div className="mt-10 flex flex-wrap items-center gap-4">
                <Link
                  href="/register"
                  className="press group inline-flex items-center gap-2 rounded-md bg-ink px-6 py-3 text-[15px] font-medium text-bg hover:opacity-90"
                >
                  Create your workspace
                  <ArrowRight className="size-4 transition-transform duration-200 ease-[var(--ease-out)] group-hover:translate-x-0.5" />
                </Link>
                <span className="text-[13.5px] text-muted">Runs on your own infrastructure, with the model you choose.</span>
              </div>
            </Reveal>
          </div>
        </section>
      </main>

      <footer className="border-t border-rule">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-8 text-[12.5px] text-muted">
          <Logo />
          <div className="flex gap-6">
            <a href="#how" className="hover:text-ink">
              How it works
            </a>
            <a href="#features" className="hover:text-ink">
              Features
            </a>
            <Link href="/login" className="hover:text-ink">
              Sign in
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}

function Excerpt({ doc, where, text, delay }: { doc: string; where: string; text: [string, string, string]; delay: number }) {
  return (
    <Reveal delay={delay} className="wipe">
      <figure className="rounded-lg border border-rule bg-bg p-5">
        <figcaption className="mb-3 flex items-baseline justify-between gap-3 text-[12.5px]">
          <span className="font-medium text-ink">{doc}</span>
          <span className="font-mono text-muted">{where}</span>
        </figcaption>
        <blockquote className="font-serif text-[19px] leading-snug text-ink-2">
          {text[0]}
          <span className="ink-mark text-ink" style={{ "--delay": `${delay + 700}ms` } as React.CSSProperties}>
            {text[1]}
          </span>
          {text[2]}
        </blockquote>
      </figure>
    </Reveal>
  );
}
