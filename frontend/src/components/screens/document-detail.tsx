"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";
import { ArrowLeft, Download, Lock, Users } from "lucide-react";
import { validateFile } from "@/components/screens/upload-dialog";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, FormError, Input, Select, Textarea } from "@/components/ui/field";
import { ErrorState, Segmented, SectionTitle } from "@/components/ui/misc";
import { Loading, Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import {
  api,
  errorMessage,
  type Comparison,
  type DocumentDetail,
  type DocumentPermission,
  type DocumentVersion,
} from "@/lib/api";
import { formatBytes, formatDate, formatDateTime, formatRelative } from "@/lib/format";
import { Markdown } from "@/lib/markdown";
import { useData, useInterval } from "@/lib/use-data";
import { useSession } from "@/stores/session";

type Tab = "details" | "versions" | "access";

export function DocumentDetailScreen() {
  const params = useParams<{ id: string }>();
  const docId = params.id;
  const router = useRouter();
  const toast = useToast();
  const { org } = useSession();
  const orgId = org!.id;
  const [tab, setTab] = useState<Tab>("details");
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmArchive, setConfirmArchive] = useState(false);

  const doc = useData(() => api.document(orgId, docId), [orgId, docId]);
  const versions = useData(() => api.versions(orgId, docId), [orgId, docId]);

  const processing =
    doc.data?.status === "uploaded" ||
    doc.data?.status === "processing" ||
    (versions.data?.some((v) => !["ready", "failed"].includes(v.status)) ?? false);
  useInterval(
    () => {
      void doc.reload();
      void versions.reload();
    },
    3000,
    processing,
  );

  if (doc.loading) return <Loading />;
  if (doc.error || !doc.data)
    return (
      <div className="mx-auto max-w-5xl">
        <BackLink />
        <ErrorState message={doc.error ?? "Document not found"} onRetry={doc.reload} />
      </div>
    );

  const d = doc.data;
  const canEdit = d.my_permission === "edit" || d.my_permission === "manage";
  const canManage = d.my_permission === "manage";
  const archived = d.status === "archived";

  async function run(label: string, action: () => Promise<unknown>, success: string) {
    setBusy(label);
    try {
      await action();
      toast(success);
      await Promise.all([doc.reload(), versions.reload()]);
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto max-w-5xl">
      <BackLink />
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4 border-b border-rule pb-4">
        <div className="min-w-0">
          <h1 className="font-serif text-[26px] font-semibold leading-tight">{d.title}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted">
            <StatusBadge status={d.status} />
            <span className="font-mono text-[12px]">{d.original_filename}</span>
            <span>
              {d.version_count} version{d.version_count === 1 ? "" : "s"}
            </span>
            {d.owner_name && <span>Owner: {d.owner_name}</span>}
            <span>Updated {formatRelative(d.updated_at)}</span>
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() => run("download", () => api.download(orgId, docId), "Download started")}
            loading={busy === "download"}
          >
            <Download className="size-4" />
            Download
          </Button>
          {canEdit && d.latest_version_status === "failed" && !archived && (
            <Button
              onClick={() => run("reprocess", () => api.reprocessDocument(orgId, docId), "Processing restarted")}
              loading={busy === "reprocess"}
            >
              Retry processing
            </Button>
          )}
          {canManage &&
            (archived ? (
              <Button
                onClick={() => run("restore", () => api.restoreDocument(orgId, docId), "Document restored")}
                loading={busy === "restore"}
              >
                Restore
              </Button>
            ) : (
              <Button variant="danger" onClick={() => setConfirmArchive(true)}>
                Archive
              </Button>
            ))}
        </div>
      </div>

      {d.latest_version_status === "failed" && d.latest_version_error && (
        <div role="alert" className="mb-5 rounded-md border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger">
          <p className="font-medium">The latest version could not be processed.</p>
          <p className="mt-0.5">{d.latest_version_error}</p>
          {d.active_version_id && <p className="mt-0.5">Answers still use the previous ready version.</p>}
        </div>
      )}
      {archived && (
        <p className="mb-5 rounded-md border border-rule bg-surface-2 px-4 py-3 text-[13px] text-ink-2">
          This document is archived. It is hidden from the library and never used in answers.
        </p>
      )}

      <div className="mb-5">
        <Segmented<Tab>
          label="Document sections"
          value={tab}
          onChange={setTab}
          options={[
            { value: "details", label: "Details" },
            { value: "versions", label: "Versions", count: versions.data?.length },
            { value: "access", label: "Access" },
          ]}
        />
      </div>

      {tab === "details" && <DetailsTab key={d.id} doc={d} canEdit={canEdit && !archived} onSaved={doc.reload} />}
      {tab === "versions" && (
        <VersionsTab
          orgId={orgId}
          doc={d}
          versions={versions.data}
          error={versions.error}
          canEdit={canEdit && !archived}
          onChanged={() => Promise.all([doc.reload(), versions.reload()])}
        />
      )}
      {tab === "access" && <AccessTab orgId={orgId} doc={d} canManage={canManage} onChanged={doc.reload} />}

      <Dialog
        open={confirmArchive}
        onClose={() => setConfirmArchive(false)}
        title="Archive this document?"
        footer={
          <>
            <Button onClick={() => setConfirmArchive(false)}>Cancel</Button>
            <Button
              variant="danger"
              loading={busy === "archive"}
              onClick={async () => {
                setBusy("archive");
                try {
                  await api.archiveDocument(orgId, docId);
                  toast("Document archived");
                  router.push("/app/documents");
                } catch (e) {
                  toast(errorMessage(e), "error");
                  setBusy(null);
                  setConfirmArchive(false);
                }
              }}
            >
              Archive
            </Button>
          </>
        }
      >
        <p className="text-[13.5px] text-ink-2">
          “{d.title}” will stop appearing in answers immediately. You can restore it later from the Archived filter.
        </p>
      </Dialog>
    </div>
  );
}

function BackLink() {
  return (
    <Link href="/app/documents" className="mb-4 inline-flex items-center gap-1 text-[13px] text-muted hover:text-ink">
      <ArrowLeft className="size-3.5" />
      Documents
    </Link>
  );
}

// --- Details ---------------------------------------------------------------

function DetailsTab({ doc, canEdit, onSaved }: { doc: DocumentDetail; canEdit: boolean; onSaved: () => Promise<void> }) {
  const toast = useToast();
  const { org } = useSession();
  const [form, setForm] = useState(() => toForm(doc));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const dirty = JSON.stringify(form) !== JSON.stringify(toForm(doc));

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.updateDocument(org!.id, doc.id, {
        title: form.title.trim(),
        description: form.description.trim() || null,
        category: form.category.trim() || null,
        department: form.department.trim() || null,
        tags: form.tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      });
      await onSaved();
      toast("Saved");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={save} className="grid max-w-2xl gap-4">
      <FormError message={error} />
      <Field label="Title">
        {(id) => (
          <Input id={id} value={form.title} disabled={!canEdit} maxLength={500} required onChange={(e) => setForm({ ...form, title: e.target.value })} />
        )}
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Category">
          {(id) => (
            <Input id={id} value={form.category} disabled={!canEdit} maxLength={100} onChange={(e) => setForm({ ...form, category: e.target.value })} />
          )}
        </Field>
        <Field label="Department">
          {(id) => (
            <Input id={id} value={form.department} disabled={!canEdit} maxLength={100} onChange={(e) => setForm({ ...form, department: e.target.value })} />
          )}
        </Field>
      </div>
      <Field label="Tags" hint="Separate with commas.">
        {(id, d) => (
          <Input id={id} aria-describedby={d} value={form.tags} disabled={!canEdit} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
        )}
      </Field>
      <Field label="Description">
        {(id) => (
          <Textarea id={id} rows={4} value={form.description} disabled={!canEdit} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        )}
      </Field>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 border-t border-rule pt-4 text-[13px] sm:grid-cols-3">
        <Meta label="File type" value={doc.file_type.toUpperCase()} />
        <Meta label="Created" value={formatDate(doc.created_at)} />
        <Meta label="Your access" value={doc.my_permission ? doc.my_permission[0].toUpperCase() + doc.my_permission.slice(1) : "—"} />
      </dl>
      {canEdit && (
        <div className="flex gap-2">
          <Button type="submit" variant="primary" loading={saving} disabled={!dirty || !form.title.trim()}>
            Save changes
          </Button>
          {dirty && (
            <Button onClick={() => setForm(toForm(doc))} disabled={saving}>
              Discard
            </Button>
          )}
        </div>
      )}
    </form>
  );
}

function toForm(doc: DocumentDetail) {
  return {
    title: doc.title,
    description: doc.description ?? "",
    category: doc.category ?? "",
    department: doc.department ?? "",
    tags: (doc.tags ?? []).join(", "),
  };
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[12px] text-muted">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

// --- Versions --------------------------------------------------------------

function VersionsTab({
  orgId,
  doc,
  versions,
  error,
  canEdit,
  onChanged,
}: {
  orgId: string;
  doc: DocumentDetail;
  versions: DocumentVersion[] | undefined;
  error: string | null;
  canEdit: boolean;
  onChanged: () => Promise<unknown>;
}) {
  const toast = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);

  if (error) return <ErrorState message={error} />;
  if (!versions) return <Loading />;

  async function uploadVersion(file: File) {
    const problem = validateFile(file);
    if (problem) {
      toast(problem, "error");
      return;
    }
    setUploading(true);
    try {
      const v = await api.uploadVersion(orgId, doc.id, file);
      toast(`Version ${v.version_number} uploaded. It replaces the current one once processed.`);
      await onChanged();
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-muted">The active version is the one answers are drawn from.</p>
        <div className="flex gap-2">
          {versions.length > 1 && <Button onClick={() => setCompareOpen(true)}>Compare versions</Button>}
          {canEdit && (
            <>
              <Button variant="primary" loading={uploading} onClick={() => fileInput.current?.click()}>
                Upload new version
              </Button>
              <input
                ref={fileInput}
                type="file"
                accept={`.${doc.file_type}`}
                className="sr-only"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) void uploadVersion(file);
                }}
              />
            </>
          )}
        </div>
      </div>

      <ul className="divide-y divide-rule border-y border-rule">
        {versions.map((v) => (
          <li key={v.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1 py-3 text-[13.5px]">
            <span className="w-10 font-mono text-[12.5px] font-medium">v{v.version_number}</span>
            <span className="flex items-center gap-2">
              <StatusBadge status={v.status} />
              {v.is_active && <Badge tone="accent">Active</Badge>}
            </span>
            <span className="text-muted">{formatDateTime(v.created_at)}</span>
            <span className="text-muted">{formatBytes(v.file_size_bytes)}</span>
            {v.page_count ? <span className="text-muted">{v.page_count} pages</span> : null}
            <span className="flex-1" />
            <Button size="sm" variant="ghost" onClick={() => api.download(orgId, doc.id, v.id).catch((e) => toast(errorMessage(e), "error"))}>
              <Download className="size-3.5" />
              Download
            </Button>
            {v.error_message && <p className="basis-full pl-14 text-[12.5px] text-danger">{v.error_message}</p>}
          </li>
        ))}
      </ul>

      {compareOpen && <CompareDialog orgId={orgId} doc={doc} versions={versions} onClose={() => setCompareOpen(false)} />}
    </div>
  );
}

function CompareDialog({
  orgId,
  doc,
  versions,
  onClose,
}: {
  orgId: string;
  doc: DocumentDetail;
  versions: DocumentVersion[];
  onClose: () => void;
}) {
  const [target, setTarget] = useState(versions[0].id);
  const [base, setBase] = useState(versions[1]?.id ?? versions[0].id);
  const [summary, setSummary] = useState<string | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summarizing, setSummarizing] = useState(false);

  const same = base === target;
  const diff = useData<Comparison | null>(
    same ? null : () => api.compare(orgId, doc.id, base, target),
    [orgId, doc.id, base, target],
  );

  function choose(which: "base" | "target", id: string) {
    if (which === "base") setBase(id);
    else setTarget(id);
    setSummary(null);
    setSummaryError(null);
  }

  async function summarize() {
    setSummarizing(true);
    setSummaryError(null);
    try {
      setSummary((await api.compareSummary(orgId, doc.id, base, target)).summary);
    } catch (e) {
      setSummaryError(errorMessage(e));
    } finally {
      setSummarizing(false);
    }
  }

  const label = (v: DocumentVersion) => `v${v.version_number} · ${formatDate(v.created_at)}`;

  return (
    <Dialog open onClose={onClose} title={`Compare versions of “${doc.title}”`} width="max-w-4xl">
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="From">
          {(id) => (
            <Select id={id} value={base} onChange={(e) => choose("base", e.target.value)} className="w-48">
              {versions.map((v) => (
                <option key={v.id} value={v.id}>
                  {label(v)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="To">
          {(id) => (
            <Select id={id} value={target} onChange={(e) => choose("target", e.target.value)} className="w-48">
              {versions.map((v) => (
                <option key={v.id} value={v.id}>
                  {label(v)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        {!same && diff.data && (
          <p className="tabular pb-1.5 text-[13px]">
            <span className="text-accent">+{diff.data.added}</span>{" "}
            <span className="text-danger">−{diff.data.removed}</span>{" "}
            <span className="text-muted">lines</span>
          </p>
        )}
      </div>

      {same ? (
        <p className="text-[13.5px] text-muted">Choose two different versions.</p>
      ) : diff.loading ? (
        <Loading label="Reading both versions" />
      ) : diff.error ? (
        <ErrorState message={diff.error} onRetry={diff.reload} />
      ) : diff.data && diff.data.hunks.length === 0 ? (
        <p className="text-[13.5px] text-muted">The extracted text of these versions is identical.</p>
      ) : diff.data ? (
        <>
          <div className="mb-4 rounded-md border border-rule bg-bg/50 px-4 py-3">
            {summary ? (
              <Markdown source={summary} />
            ) : (
              <div className="flex flex-wrap items-center gap-3 text-[13px]">
                <span className="text-muted">Get a plain-language summary of what changed.</span>
                <Button size="sm" onClick={summarize} loading={summarizing}>
                  Summarize changes
                </Button>
                {summaryError && <span className="text-danger">{summaryError}</span>}
              </div>
            )}
          </div>
          <div className="overflow-x-auto rounded-md border border-rule font-mono text-[12.5px] leading-relaxed">
            {diff.data.hunks.map((hunk, i) => (
              <div key={i} className={i ? "border-t border-rule" : ""}>
                <div className="bg-surface-2 px-3 py-1 text-[11.5px] text-muted">
                  v{diff.data!.base.version_number} line {hunk.base_start} · v{diff.data!.target.version_number} line {hunk.target_start}
                </div>
                {hunk.lines.map((line, j) => (
                  <div
                    key={j}
                    className={`flex ${
                      line.kind === "added" ? "bg-accent-soft" : line.kind === "removed" ? "bg-danger-soft" : ""
                    }`}
                  >
                    <span className="w-6 shrink-0 select-none text-center text-muted" aria-hidden="true">
                      {line.kind === "added" ? "+" : line.kind === "removed" ? "−" : ""}
                    </span>
                    <span className="sr-only">{line.kind === "context" ? "" : line.kind}</span>
                    <span className="whitespace-pre-wrap break-words py-px pr-3">{line.text}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
          {diff.data.truncated && (
            <p className="mt-2 text-[12.5px] text-muted">These files are long; only the first part of the difference is shown.</p>
          )}
        </>
      ) : null}
    </Dialog>
  );
}

// --- Access ----------------------------------------------------------------

function AccessTab({
  orgId,
  doc,
  canManage,
  onChanged,
}: {
  orgId: string;
  doc: DocumentDetail;
  canManage: boolean;
  onChanged: () => Promise<void>;
}) {
  const toast = useToast();
  const perms = useData(() => api.permissions(orgId, doc.id), [orgId, doc.id]);
  const subjects = useData(
    canManage ? () => Promise.all([api.members(orgId), api.groups(orgId)]) : null,
    [orgId, canManage],
  );
  const [subjectType, setSubjectType] = useState<"user" | "group">("user");
  const [subjectId, setSubjectId] = useState("");
  const [permission, setPermission] = useState("view");
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);

  const [members, groups] = subjects.data ?? [[], []];
  const options =
    subjectType === "user"
      ? members.map((m) => ({ id: m.user_id, label: `${m.user_name} (${m.user_email})` }))
      : groups.map((g) => ({ id: g.id, label: `${g.name} · ${g.member_count} member${g.member_count === 1 ? "" : "s"}` }));

  async function grant(e: FormEvent) {
    e.preventDefault();
    if (!subjectId) return;
    setSaving(true);
    try {
      await api.grant(orgId, doc.id, { subject_type: subjectType, subject_id: subjectId, permission });
      setSubjectId("");
      await Promise.all([perms.reload(), onChanged()]);
      toast("Access updated");
    } catch (err) {
      toast(errorMessage(err), "error");
    } finally {
      setSaving(false);
    }
  }

  async function setRestricted(restricted: boolean) {
    setSwitching(true);
    try {
      await api.setDocumentAccess(orgId, doc.id, restricted);
      await onChanged();
      toast(restricted ? "Access restricted" : "Now visible to everyone in the organization");
    } catch (err) {
      toast(errorMessage(err), "error");
    } finally {
      setSwitching(false);
    }
  }

  async function revoke(p: DocumentPermission) {
    setRemoving(p.id);
    try {
      await api.revoke(orgId, doc.id, p.subject_type, p.subject_id);
      await perms.reload();
    } catch (err) {
      toast(errorMessage(err), "error");
    } finally {
      setRemoving(null);
    }
  }

  if (perms.error) return <ErrorState message={perms.error} onRetry={perms.reload} />;
  if (!perms.data) return <Loading />;

  const restricted = doc.restricted;

  return (
    <div className="max-w-3xl">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4 rounded-md border border-rule bg-surface px-4 py-3">
        <div className="flex items-start gap-3">
          {restricted ? (
            <Lock className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden="true" />
          ) : (
            <Users className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden="true" />
          )}
          <div>
            <p className="text-[14px] font-medium">{restricted ? "Restricted" : "Everyone in the organization"}</p>
            <p className="mt-0.5 text-[13px] text-ink-2">
              {restricted
                ? perms.data.length
                  ? "Only the people and groups below, the owner, and admins can open it or get answers from it."
                  : "Only the owner and admins can open it or get answers from it. Add people or groups below."
                : "Every member can view it and get answers from it. Grants below add edit or manage rights."}
            </p>
          </div>
        </div>
        {canManage && (
          <Button size="sm" loading={switching} onClick={() => setRestricted(!restricted)}>
            {restricted ? "Make visible to everyone" : "Restrict access"}
          </Button>
        )}
      </div>

      {perms.data.length > 0 && (
        <>
          <SectionTitle>Grants</SectionTitle>
          <ul className="mb-6 divide-y divide-rule border-y border-rule">
            {perms.data.map((p) => (
              <li key={p.id} className="flex items-center gap-3 px-1 py-2.5 text-[13.5px]">
                <Badge>{p.subject_type === "group" ? "Group" : "Person"}</Badge>
                <span className="min-w-0 flex-1 truncate">{p.subject_name ?? p.subject_id}</span>
                <span className="text-ink-2">Can {p.permission}</span>
                {canManage && (
                  <Button size="sm" variant="ghost" onClick={() => revoke(p)} loading={removing === p.id}>
                    Remove
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {canManage ? (
        <form onSubmit={grant} className="rounded-md border border-rule p-4">
          <p className="mb-3 text-[13.5px] font-medium">Give access</p>
          {!restricted && (
            <p className="mb-3 rounded bg-warn-soft px-3 py-2 text-[12.5px] text-warn">
              Granting access restricts this document: members without a grant will no longer see it.
            </p>
          )}
          {subjects.loading ? (
            <Spinner />
          ) : (
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Type">
                {(id) => (
                  <Select
                    id={id}
                    value={subjectType}
                    onChange={(e) => {
                      setSubjectType(e.target.value as "user" | "group");
                      setSubjectId("");
                    }}
                    className="w-28"
                  >
                    <option value="user">Person</option>
                    <option value="group">Group</option>
                  </Select>
                )}
              </Field>
              <Field label={subjectType === "user" ? "Person" : "Group"} className="min-w-56 flex-1">
                {(id) => (
                  <Select id={id} value={subjectId} onChange={(e) => setSubjectId(e.target.value)} required>
                    <option value="">Choose…</option>
                    {options.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.label}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label="Permission">
                {(id) => (
                  <Select id={id} value={permission} onChange={(e) => setPermission(e.target.value)} className="w-32">
                    <option value="view">Can view</option>
                    <option value="edit">Can edit</option>
                    <option value="manage">Can manage</option>
                  </Select>
                )}
              </Field>
              <Button type="submit" variant="primary" loading={saving} disabled={!subjectId}>
                Grant
              </Button>
            </div>
          )}
          {subjectType === "group" && !subjects.loading && groups.length === 0 && (
            <p className="mt-2 text-[12.5px] text-muted">
              No groups yet. Create them in <Link href="/app/settings" className="text-accent hover:underline">Settings</Link>.
            </p>
          )}
        </form>
      ) : (
        <p className="text-[13px] text-muted">Only people with manage access can change who can open it.</p>
      )}
    </div>
  );
}
