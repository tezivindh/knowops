"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { StatusBadge } from "@/components/ui/badge";
import { ErrorState, PageHeader, SectionTitle } from "@/components/ui/misc";
import { Loading } from "@/components/ui/spinner";
import { api } from "@/lib/api";
import { formatRelative, plural } from "@/lib/format";
import { useData } from "@/lib/use-data";
import { useSession } from "@/stores/session";

export function OverviewScreen() {
  const { org, user } = useSession();
  const orgId = org!.id;

  const { data, error, loading, reload } = useData(
    () =>
      Promise.all([
        api.qualitySummary(orgId),
        api.documents(orgId, { per_page: 6 }),
        api.conversations(orgId),
        api.tasks(orgId, { assignee: "me" }),
      ]),
    [orgId],
  );

  if (loading) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? "Could not load the overview"} onRetry={reload} />;

  const [summary, docs, conversations, myTasks] = data;
  const openTasks = myTasks.filter((t) => t.status === "todo" || t.status === "in_progress");
  const firstName = user?.full_name.split(" ")[0] ?? "";

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title={org!.name}
        description={firstName ? `Welcome back, ${firstName}.` : undefined}
        actions={
          <Link href="/app/ask" className="inline-flex h-8 items-center gap-2 rounded-md border border-accent bg-accent px-3 text-[13.5px] font-medium text-accent-ink hover:opacity-90">
            Ask a question
          </Link>
        }
      />

      <dl className="mb-10 grid grid-cols-2 border-y border-rule sm:grid-cols-4">
        <Stat label="Documents ready" value={summary.documents_ready} href="/app/documents" />
        <Stat
          label="Processing"
          value={summary.documents_processing}
          note={summary.documents_failed ? `${summary.documents_failed} failed` : undefined}
          href="/app/documents"
        />
        <Stat label="Open findings" value={summary.total_open} href="/app/knowledge" />
        <Stat label="Your open tasks" value={openTasks.length} href="/app/actions" />
      </dl>

      <div className="grid gap-10 lg:grid-cols-[1.4fr_1fr]">
        <section>
          <SectionTitle aside={<MoreLink href="/app/documents">All documents</MoreLink>}>Recently updated</SectionTitle>
          {docs.items.length === 0 ? (
            <p className="rounded-md border border-dashed border-rule-strong px-4 py-6 text-[13.5px] text-muted">
              No documents yet.{" "}
              <Link href="/app/documents" className="text-accent hover:underline">
                Upload the first one
              </Link>{" "}
              — answers can only come from what&apos;s been uploaded.
            </p>
          ) : (
            <ul className="divide-y divide-rule border-y border-rule">
              {docs.items.map((d) => (
                <li key={d.id}>
                  <Link href={`/app/documents/${d.id}`} className="flex items-center gap-3 px-1 py-2.5 hover:bg-surface-2/50">
                    <span className="w-10 shrink-0 font-mono text-[11px] uppercase text-muted">{d.file_type}</span>
                    <span className="min-w-0 flex-1 truncate font-medium">{d.title}</span>
                    <StatusBadge status={d.status} />
                    <span className="w-24 shrink-0 text-right text-[12.5px] text-muted">{formatRelative(d.updated_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        <div className="space-y-10">
          <section>
            <SectionTitle aside={<MoreLink href="/app/ask">Open Ask</MoreLink>}>Your recent questions</SectionTitle>
            {conversations.length === 0 ? (
              <p className="text-[13.5px] text-muted">Nothing asked yet.</p>
            ) : (
              <ul className="divide-y divide-rule border-y border-rule">
                {conversations.slice(0, 5).map((c) => (
                  <li key={c.id}>
                    <Link href={`/app/ask?c=${c.id}`} className="flex items-baseline gap-3 px-1 py-2.5 hover:bg-surface-2/50">
                      <span className="min-w-0 flex-1 truncate">{c.title}</span>
                      <span className="shrink-0 text-[12.5px] text-muted">{formatRelative(c.updated_at)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <SectionTitle aside={<MoreLink href="/app/knowledge">Review</MoreLink>}>Knowledge health</SectionTitle>
            <ul className="space-y-1.5 text-[13.5px]">
              <HealthRow label="Conflicting statements" value={summary.open_by_type.conflict} />
              <HealthRow label="Unanswered questions" value={summary.open_by_type.unanswered} />
              <HealthRow label="Stale documents" value={summary.open_by_type.stale} />
            </ul>
            <p className="mt-3 text-[12.5px] text-muted">
              {summary.scan.finished_at
                ? `Last scanned ${formatRelative(summary.scan.finished_at)}.`
                : "Not scanned yet."}{" "}
              {plural(summary.indexed_chunks, "passage")} indexed.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, note, href }: { label: string; value: number; note?: string; href: string }) {
  return (
    <Link href={href} className="border-rule px-4 py-4 hover:bg-surface-2/50 [&:not(:first-child)]:border-l max-sm:[&:nth-child(3)]:border-l-0 max-sm:[&:nth-child(n+3)]:border-t">
      <dt className="text-[12.5px] text-muted">{label}</dt>
      <dd className="tabular mt-1 font-serif text-[28px] font-semibold leading-none">{value.toLocaleString()}</dd>
      {note && <dd className="mt-1 text-[12px] text-danger">{note}</dd>}
    </Link>
  );
}

function HealthRow({ label, value }: { label: string; value: number }) {
  return (
    <li className="flex items-baseline justify-between gap-4">
      <span className="text-ink-2">{label}</span>
      <span className={`tabular font-medium ${value ? "text-warn" : "text-muted"}`}>{value}</span>
    </li>
  );
}

function MoreLink({ href, children }: { href: string; children: string }) {
  return (
    <Link href={href} className="inline-flex items-center gap-1 text-[12.5px] text-muted hover:text-ink">
      {children}
      <ArrowRight className="size-3" />
    </Link>
  );
}
