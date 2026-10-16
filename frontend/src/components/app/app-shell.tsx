"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import {
  BookOpenText,
  CircleCheck,
  FileText,
  Gauge,
  LogOut,
  Menu,
  MessageSquareText,
  Settings,
  ShieldAlert,
  X,
} from "lucide-react";
import { CreateOrgForm } from "@/components/app/create-org-form";
import { Logo } from "@/components/marketing/logo";
import { Button } from "@/components/ui/button";
import { Loading } from "@/components/ui/spinner";
import { api, errorMessage } from "@/lib/api";
import { useInterval } from "@/lib/use-data";
import { initials, ROLE_LABEL } from "@/lib/format";
import { useSession } from "@/stores/session";

const NAV = [
  { href: "/app", label: "Overview", icon: Gauge },
  { href: "/app/ask", label: "Ask", icon: MessageSquareText },
  { href: "/app/documents", label: "Documents", icon: FileText },
  { href: "/app/knowledge", label: "Knowledge health", icon: ShieldAlert },
  { href: "/app/actions", label: "Tasks & drafts", icon: CircleCheck },
  { href: "/app/settings", label: "Settings", icon: Settings },
];

export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname() ?? "/app";
  const { status, user, organizations, org, restore, signOut, selectOrg } = useSession();
  const [bootError, setBootError] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    api.onSessionExpired = () => {
      useSession.setState({ status: "signed-out", user: null, organizations: [], org: null });
    };
    restore().catch((e) => setBootError(errorMessage(e)));
    return () => {
      api.onSessionExpired = null;
    };
  }, [restore]);

  useEffect(() => {
    if (status === "signed-out" && !bootError) router.replace("/login");
  }, [status, bootError, router]);

  if (bootError) {
    return (
      <Centered>
        <p className="font-medium">Couldn&apos;t load your workspace</p>
        <p className="mt-1 text-muted">{bootError}</p>
        <Button
          className="mt-4"
          onClick={() => {
            setBootError(null);
            restore().catch((e) => setBootError(errorMessage(e)));
          }}
        >
          Try again
        </Button>
      </Centered>
    );
  }

  if (status !== "signed-in" || !user) {
    return (
      <Centered>
        <Loading label="Opening your workspace" />
      </Centered>
    );
  }

  if (!org) {
    return <NoOrganization email={user.email} onSignOut={() => void signOut()} />;
  }

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-4 pb-3 pt-4">
        <Logo href="/app" />
        <button className="rounded p-1 text-muted hover:bg-surface-2 md:hidden" onClick={() => setMenuOpen(false)} aria-label="Close menu">
          <X className="size-4" />
        </button>
      </div>

      <div className="px-3 pb-3">
        <label htmlFor="org-switch" className="sr-only">
          Organization
        </label>
        <select
          id="org-switch"
          value={org.id}
          onChange={(e) => {
            selectOrg(e.target.value);
            setMenuOpen(false);
            router.push("/app");
          }}
          className="h-8 w-full rounded-md border border-rule-strong bg-surface px-2 text-[13px] font-medium"
        >
          {organizations.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
        <p className="mt-1 px-0.5 text-[12px] text-muted">{ROLE_LABEL[org.role ?? ""] ?? "Member"}</p>
      </div>

      <nav className="flex-1 px-2" aria-label="Main">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/app" ? pathname === "/app" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              onClick={() => setMenuOpen(false)}
              className={`mb-px flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13.5px] transition-colors ${
                active ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:bg-surface-2/60 hover:text-ink"
              }`}
            >
              <Icon className={`size-4 ${active ? "text-accent" : "text-muted"}`} strokeWidth={1.75} />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-rule p-3">
        <div className="flex items-center gap-2.5">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[11px] font-semibold text-ink-2">
            {initials(user.full_name)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-medium">{user.full_name}</p>
            <p className="truncate text-[12px] text-muted">{user.email}</p>
          </div>
          <button
            onClick={() => void signOut().then(() => router.replace("/login"))}
            className="rounded p-1.5 text-muted hover:bg-surface-2 hover:text-ink"
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex min-h-dvh">
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 border-r border-rule bg-surface/60 md:block">{sidebar}</aside>

      {menuOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/30" onClick={() => setMenuOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 border-r border-rule bg-surface">{sidebar}</aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-3 border-b border-rule px-4 py-2.5 md:hidden">
          <button onClick={() => setMenuOpen(true)} className="rounded p-1 text-ink-2 hover:bg-surface-2" aria-label="Open menu">
            <Menu className="size-5" />
          </button>
          <span className="truncate text-[13.5px] font-medium">{org.name}</span>
        </div>
        {/* Keyed by org so every screen reloads its data on switch. */}
        <main key={org.id} className="flex-1 px-5 py-6 md:px-10 md:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}

/**
 * First screen for an account with no organization. Most people arriving here
 * were told to sign up by a teammate, so joining comes first; we keep checking
 * for an invitation so they're moved in as soon as an admin adds them.
 */
function NoOrganization({ email, onSignOut }: { email: string; onSignOut: () => void }) {
  const refreshOrganizations = useSession((s) => s.refreshOrganizations);
  const [checking, setChecking] = useState(false);
  const [creating, setCreating] = useState(false);

  useInterval(() => refreshOrganizations().catch(() => {}), 5000, !creating);

  async function checkNow() {
    setChecking(true);
    try {
      await refreshOrganizations();
    } catch {
      // The next automatic check will retry.
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="min-h-dvh">
      <header className="flex items-center justify-between px-6 py-5">
        <Logo href="/app" />
        <Button variant="ghost" size="sm" onClick={onSignOut}>
          Sign out
        </Button>
      </header>
      <main className="mx-auto max-w-md px-6 pb-16 pt-[6vh]">
        <h1 className="fade-in font-serif text-[30px] font-semibold leading-tight">You&apos;re in. One more step.</h1>
        <p className="fade-in mt-2 text-[14px] text-ink-2" style={{ "--delay": "60ms" } as React.CSSProperties}>
          KnowOps works inside an organization — your company&apos;s shared space for documents and answers.
        </p>

        <section
          className="fade-in mt-8 rounded-lg border border-rule bg-surface p-5"
          style={{ "--delay": "120ms" } as React.CSSProperties}
        >
          <h2 className="text-[15px] font-semibold">Joining your team?</h2>
          <p className="mt-1 text-[13.5px] leading-relaxed text-ink-2">
            Ask an admin to add <span className="font-medium text-ink">{email}</span> under Settings → Members. You&apos;ll
            be taken in automatically — no need to refresh.
          </p>
          <div className="mt-4 flex items-center gap-3 text-[12.5px] text-muted">
            <span className="inline-flex items-center gap-2" role="status">
              <span className="size-1.5 animate-pulse rounded-full bg-accent" aria-hidden="true" />
              Checking for an invitation…
            </span>
            <Button size="sm" variant="ghost" loading={checking} onClick={checkNow} className="ml-auto">
              Check now
            </Button>
          </div>
        </section>

        <section className="fade-in mt-4" style={{ "--delay": "180ms" } as React.CSSProperties}>
          {creating ? (
            <div className="rounded-lg border border-rule p-5">
              <div className="mb-4 flex items-baseline justify-between">
                <h2 className="text-[15px] font-semibold">Create a new organization</h2>
                <button type="button" onClick={() => setCreating(false)} className="text-[12.5px] text-muted hover:text-ink">
                  Cancel
                </button>
              </div>
              <p className="-mt-2 mb-4 text-[13px] text-muted">You&apos;ll be its owner and can invite your team.</p>
              <CreateOrgForm onCreated={(created) => void refreshOrganizations(created.id)} />
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setCreating(true)}
              className="press w-full rounded-lg border border-dashed border-rule-strong px-5 py-4 text-left hover:bg-surface-2/50"
            >
              <span className="block text-[15px] font-semibold">Starting fresh?</span>
              <span className="mt-0.5 block text-[13.5px] text-ink-2">Create a new organization for your company.</span>
            </button>
          )}
        </section>
      </main>
    </div>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center px-6 text-center text-[13.5px]">
      <BookOpenText className="mb-3 size-5 text-muted" strokeWidth={1.5} aria-hidden="true" />
      {children}
    </div>
  );
}
