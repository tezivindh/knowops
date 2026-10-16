"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { ArrowLeft, Check, Eye, EyeOff } from "lucide-react";
import { Logo } from "@/components/marketing/logo";
import { Reveal } from "@/components/marketing/reveal";
import { Button } from "@/components/ui/button";
import { Field, FormError, Input } from "@/components/ui/field";
import { api, errorMessage } from "@/lib/api";
import { useSession } from "@/stores/session";

const delay = (ms: number) => ({ "--delay": `${ms}ms` }) as React.CSSProperties;

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const { status, restore, signIn, signUp } = useSession();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const token = new URLSearchParams(window.location.hash.slice(1)).get("invitation");
    if (token) {
      sessionStorage.setItem("knowops.invitation", token);
      window.history.replaceState(null, "", window.location.pathname);
    }
    restore().catch(() => {});
  }, [restore]);

  useEffect(() => {
    if (status !== "signed-in") return;
    let cancelled = false;
    async function finish() {
      try {
        const token = sessionStorage.getItem("knowops.invitation");
        if (token) {
          const member = await api.acceptInvitation(token);
          sessionStorage.removeItem("knowops.invitation");
          await useSession.getState().refreshOrganizations(member.organization_id);
        }
        if (!cancelled) router.replace("/app");
      } catch (err) {
        if (!cancelled) { setError(errorMessage(err)); setBusy(false); }
      }
    }
    void finish();
    return () => { cancelled = true; };
  }, [status, router]);

  const register = mode === "register";
  const longEnough = password.length >= 8;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (register && !longEnough) {
      setError("Use at least 8 characters for your password.");
      return;
    }
    setBusy(true);
    try {
      if (register) await signUp(email.trim(), password, name.trim());
      else await signIn(email.trim(), password);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  function trackCapsLock(e: KeyboardEvent<HTMLInputElement>) {
    setCapsLock(e.getModifierState?.("CapsLock") ?? false);
  }

  return (
    <div className="grid min-h-dvh lg:grid-cols-[1fr_1.05fr]">
      {/* Form column */}
      <div className="flex min-h-dvh flex-col px-6 sm:px-10">
        <header className="flex items-center justify-between py-5">
          <Logo />
          <Link href="/" className="inline-flex items-center gap-1 text-[13px] text-muted hover:text-ink">
            <ArrowLeft className="size-3.5" />
            Home
          </Link>
        </header>

        <main className="flex flex-1 items-center justify-center py-10">
          <div className="w-full max-w-[380px]">
            <h1 className="fade-in font-serif text-[clamp(30px,4vw,40px)] font-semibold leading-[1.05] tracking-[-0.02em]">
              {register ? "Create your account" : "Welcome back"}
            </h1>
            <p className="fade-in mt-2 text-[14px] text-muted" style={delay(60)}>
              {register ? (
                <>
                  Already have one?{" "}
                  <Link href="/login" className="font-medium text-accent underline-offset-2 hover:underline">
                    Sign in
                  </Link>
                </>
              ) : (
                <>
                  New to KnowOps?{" "}
                  <Link href="/register" className="font-medium text-accent underline-offset-2 hover:underline">
                    Create an account
                  </Link>
                </>
              )}
            </p>

            <form onSubmit={submit} className="fade-in mt-8 flex flex-col gap-4" style={delay(120)} noValidate>
              {error && (
                <div className="fade-in">
                  <FormError message={error} />
                </div>
              )}
              {register && (
                <Field label="Full name">
                  {(id) => (
                    <Input
                      id={id}
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      autoComplete="name"
                      className="h-10 text-[14px]"
                      required
                      autoFocus
                    />
                  )}
                </Field>
              )}
              <Field label="Work email">
                {(id) => (
                  <Input
                    id={id}
                    type="email"
                    inputMode="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    autoComplete="email"
                    placeholder="you@company.com"
                    className="h-10 text-[14px]"
                    required
                    autoFocus={!register}
                  />
                )}
              </Field>
              <Field label="Password">
                {(id) => (
                  <div className="relative">
                    <Input
                      id={id}
                      type={showPassword ? "text" : "password"}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      onKeyDown={trackCapsLock}
                      onKeyUp={trackCapsLock}
                      onBlur={() => setCapsLock(false)}
                      autoComplete={register ? "new-password" : "current-password"}
                      aria-describedby="password-help"
                      className="h-10 pr-10 text-[14px]"
                      required
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((v) => !v)}
                      aria-label={showPassword ? "Hide password" : "Show password"}
                      aria-pressed={showPassword}
                      className="press absolute right-1 top-1/2 -translate-y-1/2 rounded p-1.5 text-muted hover:bg-surface-2 hover:text-ink"
                    >
                      {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                    </button>
                  </div>
                )}
              </Field>
              <div id="password-help" className="-mt-2 min-h-[18px] text-[12.5px]" aria-live="polite">
                {capsLock ? (
                  <span className="text-warn">Caps Lock is on.</span>
                ) : register ? (
                  <span
                    className={`inline-flex items-center gap-1.5 transition-colors duration-200 ${
                      longEnough ? "text-accent" : "text-muted"
                    }`}
                  >
                    <Check className={`size-3.5 transition-opacity duration-200 ${longEnough ? "opacity-100" : "opacity-40"}`} />
                    At least 8 characters
                  </span>
                ) : null}
              </div>

              <Button
                type="submit"
                variant="primary"
                loading={busy}
                disabled={!email.trim() || !password || (register && !name.trim())}
                className="press h-10 text-[14px]"
              >
                {register ? "Create account" : "Sign in"}
              </Button>

              {register && (
                <p className="text-center text-[12.5px] text-muted">
                  You&apos;ll set up your organization next. It takes under a minute.
                </p>
              )}
            </form>
          </div>
        </main>

        <footer className="py-5 text-[12px] text-muted">
          Answers come only from documents your organization uploads.
        </footer>
      </div>

      {/* Editorial panel */}
      <aside className="relative hidden overflow-hidden border-l border-rule bg-surface lg:flex lg:flex-col lg:justify-center">
        <div className="mx-auto w-full max-w-[520px] px-12 py-16">
          {register ? <RegisterPanel /> : <LoginPanel />}
        </div>
      </aside>
    </div>
  );
}

function LoginPanel() {
  return (
    <>
      <p className="fade-in font-mono text-[11.5px] uppercase tracking-[0.12em] text-muted" style={delay(200)}>
        Answers with receipts
      </p>
      <h2
        className="fade-in mt-4 font-serif text-[clamp(32px,3.4vw,46px)] font-semibold leading-[1.04] tracking-[-0.02em]"
        style={delay(260)}
      >
        Pick up where your team left off.
      </h2>

      <Reveal className="mt-10" delay={0}>
        <figure className="fade-in rounded-lg border border-rule bg-bg p-5" style={delay(380)}>
          <p className="text-[14px] leading-relaxed">
            Security incidents must be reported within{" "}
            <strong className="font-semibold">1 hour</strong> of discovery
            <span className="relative -top-[0.45em] mx-0.5 rounded-[3px] bg-accent px-1 font-mono text-[10.5px] font-medium text-accent-ink">
              1
            </span>
            .
          </p>
          <figcaption className="mt-4 border-t border-rule pt-3 text-[12.5px]">
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-[11px] text-accent">[1]</span>
              <span className="font-medium">Security Incident Runbook</span>
              <span className="text-muted">§ Reporting</span>
            </div>
            <blockquote className="ml-6 mt-2 border-l-2 border-accent pl-3 leading-relaxed text-ink-2">
              Report suspected incidents to the security team{" "}
              <span className="ink-mark text-ink" style={delay(900)}>
                within 1 hour of discovery
              </span>
              .
            </blockquote>
          </figcaption>
        </figure>
      </Reveal>

      <p className="fade-in mt-6 text-[13.5px] leading-relaxed text-ink-2" style={delay(500)}>
        Every sentence links to the passage it came from — so you can check it in a click.
      </p>
    </>
  );
}

const STEPS = [
  { n: "01", title: "Upload your documents", body: "Policies, handbooks and runbooks — PDF, Word, Markdown, text or CSV." },
  { n: "02", title: "Ask in plain language", body: "Every answer cites the exact passage, page or section it came from." },
  { n: "03", title: "Fix what's wrong", body: "Conflicts, stale documents and unanswered questions are flagged for you." },
];

function RegisterPanel() {
  return (
    <>
      <p className="fade-in font-mono text-[11.5px] uppercase tracking-[0.12em] text-muted" style={delay(200)}>
        Getting started
      </p>
      <h2
        className="fade-in mt-4 font-serif text-[clamp(32px,3.4vw,46px)] font-semibold leading-[1.04] tracking-[-0.02em]"
        style={delay(260)}
      >
        Company knowledge you can check.
      </h2>
      <ol className="mt-10 overflow-hidden rounded-lg border border-rule bg-bg">
        {STEPS.map((step, i) => (
          <li
            key={step.n}
            className="fade-in flex gap-5 border-rule px-5 py-5 [&+&]:border-t"
            style={delay(380 + i * 70)}
          >
            <span className="pt-0.5 font-mono text-[12.5px] text-accent">{step.n}</span>
            <div>
              <p className="text-[15px] font-semibold tracking-[-0.01em]">{step.title}</p>
              <p className="mt-1 text-[13.5px] leading-relaxed text-ink-2">{step.body}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className="fade-in mt-6 text-[13.5px] leading-relaxed text-ink-2" style={delay(620)}>
        Self-hosted, with the language model you choose. Your documents stay on your infrastructure.
      </p>
    </>
  );
}
