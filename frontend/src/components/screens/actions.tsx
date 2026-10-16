"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, FormError, Input, Select, Textarea } from "@/components/ui/field";
import { Empty, ErrorState, PageHeader, SectionTitle, Segmented } from "@/components/ui/misc";
import { Loading } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import {
  api,
  errorMessage,
  type ActionRun,
  type ChecklistItem,
  type EmailPayload,
  type Member,
  type Priority,
  type SourceReference,
  type Task,
  type TaskPayload,
  type TaskStatus,
} from "@/lib/api";
import { formatDate, formatRelative, passageText } from "@/lib/format";
import { useData } from "@/lib/use-data";
import { canContribute, useSession } from "@/stores/session";

const STATUS_LABEL: Record<TaskStatus, string> = {
  draft: "Draft",
  todo: "To do",
  in_progress: "In progress",
  completed: "Done",
  cancelled: "Cancelled",
};
const PRIORITY_TONE: Record<Priority, "neutral" | "info" | "warn" | "danger"> = {
  low: "neutral",
  medium: "info",
  high: "warn",
  urgent: "danger",
};

export function ActionsScreen() {
  const { org, user } = useSession();
  const orgId = org!.id;
  const contributor = canContribute(org);
  const [scope, setScope] = useState<"mine" | "all">("all");
  const [state, setState] = useState<"open" | "done">("open");
  const [editing, setEditing] = useState<Task | "new" | null>(null);

  const runs = useData(() => api.actions(orgId), [orgId]);
  const tasks = useData(() => api.tasks(orgId), [orgId]);
  const members = useData(() => api.members(orgId), [orgId]);

  const proposals = (runs.data ?? []).filter((r) => r.status === "proposed");
  const drafts = (runs.data ?? []).filter((r) => r.status === "completed" && r.action_type === "email_draft");

  const shownTasks = (tasks.data ?? [])
    .filter((t) => (scope === "mine" ? t.assignee_id === user?.id || t.created_by === user?.id : true))
    .filter((t) => (state === "open" ? !["completed", "cancelled"].includes(t.status) : ["completed", "cancelled"].includes(t.status)));

  async function afterRunChange() {
    await Promise.all([runs.reload(), tasks.reload()]);
  }

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Tasks & drafts"
        description="Work created from answers. Drafts proposed by the assistant do nothing until someone approves them."
        actions={
          contributor && (
            <Button variant="primary" onClick={() => setEditing("new")}>
              <Plus className="size-4" />
              New task
            </Button>
          )
        }
      />

      {runs.error && <ErrorState message={runs.error} onRetry={runs.reload} />}

      {proposals.length > 0 && (
        <section className="mb-10">
          <SectionTitle>Waiting for review · {proposals.length}</SectionTitle>
          <div className="space-y-4">
            {proposals.map((run) => (
              <Proposal key={run.id} run={run} orgId={orgId} onChanged={afterRunChange} />
            ))}
          </div>
        </section>
      )}

      <section className="mb-10">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-[12px] font-semibold uppercase tracking-[0.06em] text-muted">Tasks</h2>
          <div className="flex flex-wrap gap-2">
            <Segmented
              label="Whose tasks"
              value={scope}
              onChange={setScope}
              options={[
                { value: "all", label: "Everyone" },
                { value: "mine", label: "Mine" },
              ]}
            />
            <Segmented
              label="Task state"
              value={state}
              onChange={setState}
              options={[
                { value: "open", label: "Open" },
                { value: "done", label: "Closed" },
              ]}
            />
          </div>
        </div>
        {tasks.error ? (
          <ErrorState message={tasks.error} onRetry={tasks.reload} />
        ) : tasks.loading ? (
          <Loading />
        ) : shownTasks.length === 0 ? (
          <Empty title={state === "open" ? "No open tasks" : "No closed tasks"}>
            {state === "open" && (
              <>
                Create one here, or use <span className="font-medium text-ink">Turn into a task</span> under an answer in{" "}
                <Link href="/app/ask" className="text-accent hover:underline">
                  Ask
                </Link>
                .
              </>
            )}
          </Empty>
        ) : (
          <div className="overflow-x-auto border-y border-rule">
            <table className="w-full table-fixed text-left text-[13.5px]">
              <thead>
                <tr className="border-b border-rule text-[12px] text-muted">
                  <th className="py-2 pl-1 pr-3 font-medium">Task</th>
                  <th className="w-28 px-3 py-2 font-medium">Status</th>
                  <th className="hidden w-24 px-3 py-2 font-medium sm:table-cell">Priority</th>
                  <th className="hidden w-40 px-3 py-2 font-medium md:table-cell">Assignee</th>
                  <th className="w-24 py-2 pl-3 pr-1 text-right font-medium">Due</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rule">
                {shownTasks.map((t) => {
                  const done = t.checklist.filter((c) => c.done).length;
                  const overdue = t.due_date && !["completed", "cancelled"].includes(t.status) && t.due_date < today();
                  return (
                    <tr key={t.id} className="hover:bg-surface-2/50">
                      <td className="py-2.5 pl-1 pr-3">
                        <button onClick={() => setEditing(t)} className="block max-w-full truncate text-left font-medium hover:text-accent">
                          {t.title}
                        </button>
                        <span className="text-[12px] text-muted">
                          {t.checklist.length > 0 && `${done}/${t.checklist.length} steps · `}
                          {t.source_references.length > 0 && `${t.source_references.length} source${t.source_references.length === 1 ? "" : "s"} · `}
                          updated {formatRelative(t.updated_at)}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-ink-2">{STATUS_LABEL[t.status]}</td>
                      <td className="hidden px-3 py-2.5 sm:table-cell">
                        <Badge tone={PRIORITY_TONE[t.priority]}>{t.priority[0].toUpperCase() + t.priority.slice(1)}</Badge>
                      </td>
                      <td className="hidden truncate px-3 py-2.5 text-ink-2 md:table-cell">{t.assignee_name ?? <span className="text-muted">—</span>}</td>
                      <td className={`whitespace-nowrap py-2.5 pl-3 pr-1 text-right text-[12.5px] ${overdue ? "text-danger" : "text-muted"}`}>
                        {t.due_date ? formatDate(t.due_date + "T00:00:00") : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {drafts.length > 0 && (
        <section>
          <SectionTitle>Approved email drafts</SectionTitle>
          <ul className="space-y-3">
            {drafts.map((run) => (
              <ApprovedEmail key={run.id} run={run} />
            ))}
          </ul>
          <p className="mt-2 text-[12.5px] text-muted">KnowOps doesn&apos;t send email. Copy a draft into your mail client.</p>
        </section>
      )}

      {editing && (
        <TaskDialog
          orgId={orgId}
          task={editing === "new" ? null : editing}
          members={members.data ?? []}
          canEdit={contributor}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            await tasks.reload();
          }}
        />
      )}
    </div>
  );
}

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// --- Proposals ---------------------------------------------------------------

function checklistToText(items: ChecklistItem[]) {
  return items.map((i) => i.text).join("\n");
}

function textToChecklist(text: string, previous: ChecklistItem[] = []): ChecklistItem[] {
  return text
    .split("\n")
    .map((line) => line.replace(/^\s*[-*•]\s*/, "").trim())
    .filter(Boolean)
    .map((t) => ({ text: t.slice(0, 500), done: previous.find((p) => p.text === t)?.done ?? false }));
}

function Proposal({ run, orgId, onChanged }: { run: ActionRun; orgId: string; onChanged: () => Promise<void> }) {
  const toast = useToast();
  const isTask = run.action_type === "task_create";
  const task = run.payload as unknown as TaskPayload;
  const email = run.payload as unknown as EmailPayload;

  const [title, setTitle] = useState(isTask ? task.title : email.subject);
  const [body, setBody] = useState(isTask ? task.description : email.body);
  const [priority, setPriority] = useState<Priority>(isTask ? task.priority : "medium");
  const [due, setDue] = useState(isTask ? task.due_date ?? "" : "");
  const [steps, setSteps] = useState(isTask ? checklistToText(task.checklist) : "");
  const [to, setTo] = useState(isTask ? "" : email.to.join(", "));
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function payload() {
    return isTask
      ? { title: title.trim(), description: body, priority, due_date: due || null, checklist: textToChecklist(steps) }
      : {
          subject: title.trim(),
          body,
          to: to
            .split(/[,\s]+/)
            .map((s) => s.trim())
            .filter(Boolean),
        };
  }

  async function act(kind: "approve" | "reject") {
    setBusy(kind);
    setError(null);
    try {
      if (kind === "approve") {
        await api.updateAction(orgId, run.id, payload());
        await api.approveAction(orgId, run.id);
        toast(isTask ? "Task created" : "Email draft approved");
      } else {
        await api.rejectAction(orgId, run.id);
        toast("Draft discarded");
      }
      await onChanged();
    } catch (e) {
      setError(errorMessage(e));
      setBusy(null);
    }
  }

  return (
    <article className="rounded-md border border-rule bg-surface">
      <header className="flex flex-wrap items-center gap-2 border-b border-rule px-4 py-2.5 text-[12.5px] text-muted">
        <Badge tone="info">{isTask ? "Task" : "Email draft"}</Badge>
        <span>
          Drafted {formatRelative(run.created_at)}
          {run.proposed_by_name && ` for ${run.proposed_by_name}`}
        </span>
      </header>
      <div className="grid gap-4 p-4 lg:grid-cols-[1fr_280px]">
        <div className="grid gap-3">
          <FormError message={error} />
          <Field label={isTask ? "Title" : "Subject"}>
            {(id) => <Input id={id} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={500} />}
          </Field>
          {!isTask && (
            <Field label="To" hint="Optional. Separate addresses with commas.">
              {(id, d) => <Input id={id} aria-describedby={d} value={to} onChange={(e) => setTo(e.target.value)} placeholder="name@company.com" />}
            </Field>
          )}
          <Field label={isTask ? "Description" : "Body"}>
            {(id) => <Textarea id={id} rows={isTask ? 3 : 9} value={body} onChange={(e) => setBody(e.target.value)} />}
          </Field>
          {isTask && (
            <>
              <Field label="Steps" hint="One per line.">
                {(id, d) => <Textarea id={id} aria-describedby={d} rows={4} value={steps} onChange={(e) => setSteps(e.target.value)} />}
              </Field>
              <div className="grid grid-cols-2 gap-3 sm:max-w-sm">
                <Field label="Priority">
                  {(id) => (
                    <Select id={id} value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
                      <option value="low">Low</option>
                      <option value="medium">Medium</option>
                      <option value="high">High</option>
                      <option value="urgent">Urgent</option>
                    </Select>
                  )}
                </Field>
                <Field label="Due">
                  {(id) => <Input id={id} type="date" value={due} onChange={(e) => setDue(e.target.value)} />}
                </Field>
              </div>
            </>
          )}
          <div className="flex gap-2 pt-1">
            <Button variant="primary" loading={busy === "approve"} disabled={Boolean(busy) || !title.trim() || (!isTask && !body.trim())} onClick={() => act("approve")}>
              {isTask ? "Approve & create task" : "Approve draft"}
            </Button>
            <Button loading={busy === "reject"} disabled={Boolean(busy)} onClick={() => act("reject")}>
              Discard
            </Button>
          </div>
        </div>
        <Sources refs={run.source_references} />
      </div>
    </article>
  );
}

function Sources({ refs }: { refs: SourceReference[] }) {
  if (!refs.length) return <p className="text-[12.5px] text-muted">No cited sources.</p>;
  return (
    <div>
      <p className="mb-1.5 text-[12px] font-semibold uppercase tracking-[0.06em] text-muted">Based on</p>
      <ul className="space-y-2.5 text-[12.5px]">
        {refs.map((r, i) => (
          <li key={i}>
            {r.document_id ? (
              <Link href={`/app/documents/${r.document_id}`} className="font-medium hover:text-accent">
                {r.document_title ?? "Document"}
              </Link>
            ) : (
              <span className="font-medium">{r.document_title ?? "Document"}</span>
            )}
            {r.page_number ? <span className="text-muted"> · p. {r.page_number}</span> : null}
            {r.quoted_text && <p className="mt-0.5 line-clamp-3 text-muted">{passageText(r.quoted_text)}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ApprovedEmail({ run }: { run: ActionRun }) {
  const toast = useToast();
  const email = (run.result ?? run.payload) as unknown as EmailPayload;
  const text = `${email.to?.length ? `To: ${email.to.join(", ")}\n` : ""}Subject: ${email.subject}\n\n${email.body}`;
  return (
    <li className="rounded-md border border-rule bg-surface">
      <details>
        <summary className="flex cursor-pointer items-center gap-3 px-4 py-2.5 text-[13.5px]">
          <span className="min-w-0 flex-1 truncate font-medium">{email.subject}</span>
          <span className="text-[12.5px] text-muted">{formatRelative(run.executed_at)}</span>
        </summary>
        <div className="border-t border-rule px-4 py-3">
          <pre className="whitespace-pre-wrap font-sans text-[13.5px] leading-relaxed text-ink-2">{text}</pre>
          <Button
            size="sm"
            className="mt-3"
            onClick={() =>
              navigator.clipboard.writeText(text).then(
                () => toast("Copied to clipboard"),
                () => toast("Couldn't access the clipboard", "error"),
              )
            }
          >
            Copy
          </Button>
        </div>
      </details>
    </li>
  );
}

// --- Task dialog -------------------------------------------------------------

function TaskDialog({
  orgId,
  task,
  members,
  canEdit,
  onClose,
  onSaved,
}: {
  orgId: string;
  task: Task | null;
  members: Member[];
  canEdit: boolean;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const toast = useToast();
  const [title, setTitle] = useState(task?.title ?? "");
  const [description, setDescription] = useState(task?.description ?? "");
  const [status, setStatus] = useState<TaskStatus>(task?.status ?? "todo");
  const [priority, setPriority] = useState<Priority>(task?.priority ?? "medium");
  const { user } = useSession();
  // New tasks default to the person creating them.
  const [assignee, setAssignee] = useState(task ? (task.assignee_id ?? "") : (user?.id ?? ""));
  const [due, setDue] = useState(task?.due_date ?? "");
  const [checklist, setChecklist] = useState<ChecklistItem[]>(task?.checklist ?? []);
  const [newStep, setNewStep] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy("save");
    setError(null);
    const body = {
      title: title.trim(),
      description: description.trim() || null,
      priority,
      assignee_id: assignee || null,
      due_date: due || null,
      checklist: newStep.trim() ? [...checklist, { text: newStep.trim(), done: false }] : checklist,
    };
    try {
      if (task) await api.updateTask(orgId, task.id, { ...body, status });
      else await api.createTask(orgId, { ...body, description: body.description ?? undefined });
      toast(task ? "Task updated" : "Task created");
      await onSaved();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(null);
    }
  }

  async function remove() {
    if (!task || !window.confirm("Delete this task?")) return;
    setBusy("delete");
    try {
      await api.deleteTask(orgId, task.id);
      toast("Task deleted");
      await onSaved();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(null);
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={task ? "Task" : "New task"}
      width="max-w-2xl"
      footer={
        canEdit && (
          <>
            {task && (
              <Button variant="danger" className="mr-auto" loading={busy === "delete"} disabled={Boolean(busy)} onClick={remove}>
                Delete
              </Button>
            )}
            <Button onClick={onClose} disabled={Boolean(busy)}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" form="task-form" loading={busy === "save"} disabled={Boolean(busy) || !title.trim()}>
              {task ? "Save" : "Create task"}
            </Button>
          </>
        )
      }
    >
      <form id="task-form" onSubmit={save} className="grid gap-4">
        <FormError message={error} />
        <Field label="Title">
          {(id) => <Input id={id} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={500} disabled={!canEdit} required autoFocus={!task} />}
        </Field>
        <Field label="Description">
          {(id) => <Textarea id={id} rows={3} value={description} onChange={(e) => setDescription(e.target.value)} disabled={!canEdit} />}
        </Field>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {task && (
            <Field label="Status">
              {(id) => (
                <Select id={id} value={status} onChange={(e) => setStatus(e.target.value as TaskStatus)} disabled={!canEdit}>
                  {Object.entries(STATUS_LABEL).map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          )}
          <Field label="Priority">
            {(id) => (
              <Select id={id} value={priority} onChange={(e) => setPriority(e.target.value as Priority)} disabled={!canEdit}>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="urgent">Urgent</option>
              </Select>
            )}
          </Field>
          <Field label="Assignee">
            {(id) => (
              <Select id={id} value={assignee} onChange={(e) => setAssignee(e.target.value)} disabled={!canEdit}>
                <option value="">Unassigned</option>
                {members.map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.user_name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Due">
            {(id) => <Input id={id} type="date" value={due} onChange={(e) => setDue(e.target.value)} disabled={!canEdit} />}
          </Field>
        </div>

        <fieldset>
          <legend className="mb-1.5 text-[13px] font-medium text-ink-2">Steps</legend>
          {checklist.length > 0 && (
            <ul className="mb-2 space-y-1">
              {checklist.map((item, i) => (
                <li key={i} className="flex items-center gap-2 text-[13.5px]">
                  <input
                    type="checkbox"
                    checked={item.done}
                    disabled={!canEdit}
                    onChange={() => setChecklist(checklist.map((c, j) => (j === i ? { ...c, done: !c.done } : c)))}
                    className="size-4 accent-[var(--accent)]"
                    aria-label={`Mark "${item.text}" as ${item.done ? "not done" : "done"}`}
                  />
                  <span className={`flex-1 ${item.done ? "text-muted line-through" : ""}`}>{item.text}</span>
                  {canEdit && (
                    <button type="button" onClick={() => setChecklist(checklist.filter((_, j) => j !== i))} className="text-[12px] text-muted hover:text-danger">
                      Remove
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {canEdit && (
            <div className="flex gap-2">
              <Input
                value={newStep}
                onChange={(e) => setNewStep(e.target.value)}
                placeholder="Add a step"
                aria-label="New step"
                maxLength={500}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    if (newStep.trim()) {
                      setChecklist([...checklist, { text: newStep.trim(), done: false }]);
                      setNewStep("");
                    }
                  }
                }}
              />
              <Button
                onClick={() => {
                  if (!newStep.trim()) return;
                  setChecklist([...checklist, { text: newStep.trim(), done: false }]);
                  setNewStep("");
                }}
              >
                Add
              </Button>
            </div>
          )}
        </fieldset>

        {task && task.source_references.length > 0 && (
          <div className="border-t border-rule pt-4">
            <Sources refs={task.source_references} />
          </div>
        )}
        {task && (
          <p className="text-[12px] text-muted">
            Created by {task.created_by_name ?? "—"} · {formatDate(task.created_at)}
          </p>
        )}
      </form>
    </Dialog>
  );
}
