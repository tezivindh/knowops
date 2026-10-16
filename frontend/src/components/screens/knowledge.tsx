"use client";

import Link from "next/link";
import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { Badge, SeverityBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, Select, Textarea } from "@/components/ui/field";
import { Empty, ErrorState, PageHeader, Segmented } from "@/components/ui/misc";
import { Loading, Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage, type Finding, type FindingStatus, type FindingType, type Member, type ScanState } from "@/lib/api";
import { formatDate, formatRelative, passageText, plural } from "@/lib/format";
import { useData, useInterval } from "@/lib/use-data";
import { isManager, useSession } from "@/stores/session";

type TypeFilter = "all" | FindingType;
type StatusFilter = "active" | "resolved" | "dismissed";

const TYPE_LABEL: Record<FindingType, string> = {
  conflict: "Conflict",
  unanswered: "Unanswered",
  stale: "Stale",
  gap: "Gap",
};

export function KnowledgeScreen() {
  const { org, user } = useSession();
  const orgId = org!.id;
  const manager = isManager(org);
  const toast = useToast();
  const [type, setType] = useState<TypeFilter>("all");
  const [status, setStatus] = useState<StatusFilter>("active");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const findings = useData(() => api.findings(orgId), [orgId]);
  const scan = useData(() => api.scanState(orgId), [orgId]);
  const members = useData<Member[]>(manager ? () => api.members(orgId) : null, [orgId, manager]);

  const scanning = scan.data?.status === "queued" || scan.data?.status === "running";
  useInterval(
    async () => {
      const before = scan.data?.status;
      await scan.reload();
      if (before && before !== "completed") await findings.reload();
    },
    2500,
    scanning,
  );

  async function startScan() {
    setStarting(true);
    try {
      const state = await api.startScan(orgId);
      scan.setData(() => state);
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setStarting(false);
    }
  }

  function replace(updated: Finding) {
    findings.setData((list) => list?.map((f) => (f.id === updated.id ? updated : f)));
  }

  const all = findings.data ?? [];
  const byStatus = all.filter((f) =>
    status === "active" ? f.status === "open" || f.status === "in_review" : f.status === status,
  );
  const visible = byStatus.filter((f) => type === "all" || f.finding_type === type);
  const count = (t: FindingType) => byStatus.filter((f) => f.finding_type === t).length;

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title="Knowledge health"
        description="Places where your documents disagree, have gone stale, or don't answer what people ask."
        actions={
          manager && (
            <Button variant="primary" onClick={startScan} loading={starting || scanning} disabled={scanning}>
              {scanning ? "Scanning…" : "Run scan"}
            </Button>
          )
        }
      />

      {scan.data && <ScanLine state={scan.data} manager={manager} />}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Segmented<TypeFilter>
          label="Finding type"
          value={type}
          onChange={setType}
          options={[
            { value: "all", label: "All", count: byStatus.length },
            { value: "conflict", label: "Conflicts", count: count("conflict") },
            { value: "unanswered", label: "Unanswered", count: count("unanswered") },
            { value: "stale", label: "Stale", count: count("stale") },
          ]}
        />
        <Segmented<StatusFilter>
          label="Finding status"
          value={status}
          onChange={setStatus}
          options={[
            { value: "active", label: "Open" },
            { value: "resolved", label: "Resolved" },
            { value: "dismissed", label: "Dismissed" },
          ]}
        />
      </div>

      {findings.error ? (
        <ErrorState message={findings.error} onRetry={findings.reload} />
      ) : findings.loading ? (
        <Loading />
      ) : visible.length === 0 ? (
        <Empty title={status === "active" ? "Nothing needs attention" : `No ${status} findings`}>
          {status === "active" &&
            (manager
              ? "Unanswered questions appear here automatically. Run a scan to look for conflicting and stale documents."
              : "Unanswered questions and scan results appear here.")}
        </Empty>
      ) : (
        <ul className="divide-y divide-rule border-y border-rule">
          {visible.map((f) => (
            <FindingRow
              key={f.id}
              finding={f}
              open={expanded === f.id}
              onToggle={() => setExpanded(expanded === f.id ? null : f.id)}
              canTriage={manager || f.assigned_to === user?.id}
              manager={manager}
              members={members.data ?? []}
              orgId={orgId}
              onUpdated={replace}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function ScanLine({ state, manager }: { state: ScanState; manager: boolean }) {
  const s = state.summary ?? {};
  let text: React.ReactNode;
  if (state.status === "idle") {
    text = manager ? "No scan has been run yet." : "No scan has been run yet. Admins can start one.";
  } else if (state.status === "queued" || state.status === "running") {
    text = (
      <span className="inline-flex items-center gap-2">
        <Spinner className="size-3.5" />
        {state.status === "queued" ? "Scan queued…" : "Comparing passages across documents…"}
      </span>
    );
  } else if (state.status === "failed") {
    text = <span className="text-danger">Last scan failed: {state.error ?? "unknown error"}</span>;
  } else {
    const parts = [
      `${s.conflicts_found ?? 0} new conflict${s.conflicts_found === 1 ? "" : "s"} from ${s.conflict_pairs_checked ?? 0} similar passage pairs`,
      `${s.stale_found ?? 0} stale`,
    ];
    if (s.auto_resolved) parts.push(`${s.auto_resolved} closed because a document changed`);
    text = (
      <>
        Last scan {formatRelative(state.finished_at)}: {parts.join(", ")}.
        {s.conflict_note && <span className="block text-warn">{String(s.conflict_note)}</span>}
      </>
    );
  }
  return <p className="mb-5 text-[13px] text-ink-2">{text}</p>;
}

function FindingRow({
  finding: f,
  open,
  onToggle,
  canTriage,
  manager,
  members,
  orgId,
  onUpdated,
}: {
  finding: Finding;
  open: boolean;
  onToggle: () => void;
  canTriage: boolean;
  manager: boolean;
  members: Member[];
  orgId: string;
  onUpdated: (f: Finding) => void;
}) {
  return (
    <li>
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-start gap-3 px-1 py-3 text-left hover:bg-surface-2/50">
        <ChevronRight className={`mt-0.5 size-4 shrink-0 text-muted transition-transform ${open ? "rotate-90" : ""}`} />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={f.finding_type === "conflict" ? "warn" : f.finding_type === "unanswered" ? "info" : "neutral"}>
              {TYPE_LABEL[f.finding_type]}
            </Badge>
            <span className="font-medium">{f.title}</span>
          </span>
          <span className="mt-0.5 block text-[12.5px] text-muted">
            {f.finding_type === "unanswered" && f.evidence.count ? `Asked ${plural(f.evidence.count, "time")} · ` : ""}
            Updated {formatRelative(f.updated_at)}
            {f.assigned_to_name && ` · Assigned to ${f.assigned_to_name}`}
            {f.status === "in_review" && " · In review"}
          </span>
        </span>
        <SeverityBadge severity={f.severity} />
      </button>

      {open && (
        <div className="pb-5 pl-8 pr-1">
          {f.description && <p className="mb-3 max-w-3xl text-[13.5px] text-ink-2">{f.description}</p>}
          <Evidence finding={f} />
          {f.resolution_notes && f.status !== "open" && f.status !== "in_review" && (
            <p className="mt-3 text-[13px]">
              <span className="text-muted">Notes: </span>
              {f.resolution_notes}
            </p>
          )}
          {canTriage && <Triage finding={f} manager={manager} members={members} orgId={orgId} onUpdated={onUpdated} />}
        </div>
      )}
    </li>
  );
}

function Evidence({ finding: f }: { finding: Finding }) {
  if (f.finding_type === "conflict" && f.evidence.passages?.length) {
    return (
      <div className="grid gap-3 md:grid-cols-2">
        {f.evidence.passages.map((p, i) => (
          <figure key={i} className="rounded-md border border-rule bg-surface p-3">
            <figcaption className="mb-2 flex items-baseline justify-between gap-2 text-[12.5px]">
              <Link href={`/app/documents/${p.document_id}`} className="font-medium text-ink hover:text-accent">
                {p.document_title}
              </Link>
              <span className="text-muted">
                {[p.section_heading, p.page_number ? `p. ${p.page_number}` : null].filter(Boolean).join(" · ")}
              </span>
            </figcaption>
            <blockquote className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink-2">{passageText(p.text)}</blockquote>
          </figure>
        ))}
      </div>
    );
  }
  if (f.finding_type === "unanswered") {
    const last = f.evidence.occurrences?.at(-1);
    return (
      <p className="text-[13px] text-muted">
        {last ? `Last asked ${formatRelative(last.asked_at)}. ` : ""}
        Upload or update a document that answers this, then mark it resolved.
      </p>
    );
  }
  if (f.finding_type === "stale" && f.related_documents[0]) {
    return (
      <p className="text-[13px]">
        <Link href={`/app/documents/${f.related_documents[0]}`} className="text-accent hover:underline">
          {f.evidence.document_title ?? "Open document"}
        </Link>
        <span className="text-muted">
          {" "}
          · version {f.evidence.version_number} uploaded {formatDate(f.evidence.uploaded_at)}
        </span>
      </p>
    );
  }
  return null;
}

function Triage({
  finding: f,
  manager,
  members,
  orgId,
  onUpdated,
}: {
  finding: Finding;
  manager: boolean;
  members: Member[];
  orgId: string;
  onUpdated: (f: Finding) => void;
}) {
  const toast = useToast();
  const [notes, setNotes] = useState(f.resolution_notes ?? "");
  const [busy, setBusy] = useState<string | null>(null);
  const active = f.status === "open" || f.status === "in_review";

  async function update(label: string, body: { status?: FindingStatus; resolution_notes?: string; assigned_to?: string }) {
    setBusy(label);
    try {
      onUpdated(await api.updateFinding(orgId, f.id, body));
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mt-4 grid max-w-3xl gap-3 border-t border-rule pt-4">
      {active && (
        <Field label="Notes" hint="What was done, or why this isn't a problem.">
          {(id, d) => <Textarea id={id} aria-describedby={d} rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={5000} />}
        </Field>
      )}
      <div className="flex flex-wrap items-end gap-2">
        {active ? (
          <>
            <Button size="sm" variant="primary" loading={busy === "resolve"} onClick={() => update("resolve", { status: "resolved", resolution_notes: notes })}>
              Mark resolved
            </Button>
            <Button size="sm" loading={busy === "dismiss"} onClick={() => update("dismiss", { status: "dismissed", resolution_notes: notes })}>
              Dismiss
            </Button>
            {f.status === "open" && (
              <Button size="sm" variant="ghost" loading={busy === "review"} onClick={() => update("review", { status: "in_review" })}>
                Start review
              </Button>
            )}
          </>
        ) : (
          <Button size="sm" loading={busy === "reopen"} onClick={() => update("reopen", { status: "open" })}>
            Reopen
          </Button>
        )}
        {manager && active && (
          <div className="ml-auto flex items-center gap-2">
            <label htmlFor={`assign-${f.id}`} className="text-[12.5px] text-muted">
              Assignee
            </label>
            <Select
              id={`assign-${f.id}`}
              value={f.assigned_to ?? ""}
              disabled={busy === "assign"}
              onChange={(e) => update("assign", { assigned_to: e.target.value })}
              className="h-7 w-48 text-[13px]"
            >
              <option value="">Unassigned</option>
              {members.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.user_name}
                </option>
              ))}
            </Select>
          </div>
        )}
      </div>
    </div>
  );
}
