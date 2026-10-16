"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ArrowUp, Check, ChevronRight, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/misc";
import { Loading, Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import {
  api,
  errorMessage,
  type ActionRun,
  type ChatMessage,
  type Citation,
  type ConversationSummary,
} from "@/lib/api";
import { formatRelative, passageText } from "@/lib/format";
import { Markdown } from "@/lib/markdown";
import { canContribute, useSession } from "@/stores/session";

const SUGGESTIONS = [
  "How many days of annual leave do employees get?",
  "What is the process for reporting a security incident?",
  "Who approves expense reports over the limit?",
];

export function AskScreen() {
  const { org } = useSession();
  const orgId = org!.id;
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const toast = useToast();
  const activeId = params.get("c");

  const [conversations, setConversations] = useState<ConversationSummary[] | null>(null);
  // The loaded thread, tagged with its conversation id so a stale thread is
  // never shown for a different conversation.
  const [thread, setThread] = useState<{ id: string | null; messages: ChatMessage[]; error: string | null }>({
    id: null,
    messages: [],
    error: null,
  });
  const [pending, setPending] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sendError, setSendError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  // The conversation the user last chose. URL updates are asynchronous, so a
  // question sent right after "New question" must not go to the old thread.
  // It only applies until the URL catches up (`from` is the URL state it was
  // made in), so browser back/forward still wins afterwards.
  const selection = useRef<{ id: string | null; from: string | null } | null>(null);

  // Drafts already made from answers, so each answer is drafted at most once.
  const [drafts, setDrafts] = useState<Record<string, DraftsByKind>>({});
  const userId = useSession((s) => s.user?.id);

  useEffect(() => {
    let stale = false;
    api
      .actions(orgId)
      .then((runs) => {
        if (stale) return;
        const map: Record<string, DraftsByKind> = {};
        for (const run of runs) {
          if (!run.source_message_id || run.proposed_by !== userId || run.status === "rejected") continue;
          (map[run.source_message_id] ??= {})[run.action_type] = run;
        }
        setDrafts(map);
      })
      .catch(() => {});
    return () => {
      stale = true;
    };
  }, [orgId, userId]);

  const recordDraft = useCallback((run: ActionRun) => {
    if (!run.source_message_id) return;
    const messageId = run.source_message_id;
    setDrafts((d) => ({ ...d, [messageId]: { ...d[messageId], [run.action_type]: run } }));
  }, []);

  const loadConversations = useCallback(
    () =>
      api
        .conversations(orgId)
        .then(setConversations)
        .catch((e) => {
          setConversations([]);
          toast(errorMessage(e), "error");
        }),
    [orgId, toast],
  );

  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    if (!activeId || thread.id === activeId) return;
    let stale = false;
    api
      .conversation(orgId, activeId)
      .then((detail) => !stale && setThread({ id: activeId, messages: detail.messages, error: null }))
      .catch((e) => !stale && setThread({ id: activeId, messages: [], error: errorMessage(e) }));
    return () => {
      stale = true;
    };
  }, [orgId, activeId, thread.id]);

  const messages = activeId && thread.id === activeId ? thread.messages : [];
  const loadingThread = Boolean(activeId) && thread.id !== activeId;
  const threadError = activeId && thread.id === activeId ? thread.error : null;

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages.length, pending]);

  function open(id: string | null) {
    selection.current = { id, from: activeId };
    setSendError(null);
    router.push(id ? `${pathname}?c=${id}` : pathname);
  }

  async function send(text: string) {
    const content = text.trim();
    if (!content || pending) return;
    setSendError(null);
    setPending(content);
    setDraft("");
    let createdId: string | null = null;
    try {
      let id =
        selection.current && selection.current.from === activeId ? selection.current.id : activeId;
      if (!id) {
        const created = await api.createConversation(orgId);
        id = createdId = created.id;
        // Mark the new thread as loaded so selecting it doesn't refetch.
        selection.current = { id, from: activeId };
        setThread({ id, messages: [], error: null });
        router.replace(`${pathname}?c=${id}`);
      }
      const result = await api.sendMessage(orgId, id, content);
      const conversationId = id;
      setThread((t) =>
        t.id === conversationId
          ? { ...t, messages: [...t.messages, result.user_message, result.assistant_message] }
          : t,
      );
      void loadConversations();
    } catch (e) {
      setSendError(errorMessage(e));
      setDraft(content);
      if (createdId) {
        // Don't leave an empty conversation behind when its first question failed.
        const failed = createdId;
        void api.deleteConversation(orgId, failed).catch(() => {});
        selection.current = { id: null, from: activeId };
        setThread({ id: null, messages: [], error: null });
        router.replace(pathname);
      }
    } finally {
      setPending(null);
      textarea.current?.focus();
    }
  }

  async function remove(c: ConversationSummary) {
    if (!window.confirm(`Delete “${c.title}”? This can't be undone.`)) return;
    try {
      await api.deleteConversation(orgId, c.id);
      setConversations((list) => list?.filter((x) => x.id !== c.id) ?? null);
      if (c.id === activeId) open(null);
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(draft);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send(draft);
    }
  }

  const empty = !activeId && !pending && messages.length === 0;

  return (
    <div className="-mx-5 -my-6 flex h-[calc(100dvh-49px)] md:-mx-10 md:-my-8 md:h-dvh">
      {/* Conversation list */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-rule lg:flex">
        <div className="p-3">
          <Button className="w-full" onClick={() => open(null)}>
            <Plus className="size-4" />
            New question
          </Button>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 pb-3" aria-label="Conversations">
          {conversations === null ? (
            <div className="px-2 py-3">
              <Spinner />
            </div>
          ) : conversations.length === 0 ? (
            <p className="px-2 py-3 text-[12.5px] text-muted">Your questions will be listed here.</p>
          ) : (
            conversations.map((c) => (
              <div
                key={c.id}
                className={`group flex items-center rounded-md ${c.id === activeId ? "bg-surface-2" : "hover:bg-surface-2/60"}`}
              >
                <button
                  onClick={() => open(c.id)}
                  aria-current={c.id === activeId ? "page" : undefined}
                  className="min-w-0 flex-1 px-2.5 py-1.5 text-left"
                >
                  <span className={`block truncate text-[13px] ${c.id === activeId ? "font-medium" : "text-ink-2"}`}>{c.title}</span>
                  <span className="block text-[11.5px] text-muted">{formatRelative(c.updated_at)}</span>
                </button>
                <button
                  onClick={() => remove(c)}
                  className="mr-1 rounded p-1 text-muted opacity-0 hover:text-danger focus:opacity-100 group-hover:opacity-100"
                  aria-label={`Delete ${c.title}`}
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            ))
          )}
        </nav>
      </aside>

      {/* Thread */}
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-5 py-8 md:px-8">
            {empty ? (
              <div className="pt-[8vh]">
                <h1 className="font-serif text-[28px] font-semibold">Ask your documents</h1>
                <p className="mt-1 max-w-lg text-[13.5px] text-muted">
                  Answers come only from documents marked Ready that you have access to. Each statement links to the passage
                  it&apos;s based on.
                </p>
                <ul className="mt-6 space-y-1.5">
                  {SUGGESTIONS.map((s) => (
                    <li key={s}>
                      <button
                        onClick={() => setDraft(s)}
                        className="group inline-flex items-center gap-1.5 text-left text-[13.5px] text-ink-2 hover:text-ink"
                      >
                        <ChevronRight className="size-3.5 text-muted group-hover:text-accent" />
                        {s}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : loadingThread ? (
              <Loading label="Loading conversation" />
            ) : threadError ? (
              <p className="text-[13.5px] text-danger">{threadError}</p>
            ) : (
              <div className="space-y-10">
                {pairs(messages).map(([question, answer]) => (
                  <Turn
                    key={(question ?? answer)!.id}
                    question={question}
                    answer={answer}
                    orgId={orgId}
                    drafts={answer ? drafts[answer.id] : undefined}
                    onDrafted={recordDraft}
                  />
                ))}
                {pending && (
                  <div>
                    <Question text={pending} />
                    <p className="mt-3 flex items-center gap-2 text-[13.5px] text-muted" role="status">
                      <Spinner className="size-3.5" />
                      Searching your documents and writing an answer…
                    </p>
                  </div>
                )}
              </div>
            )}
            <div ref={bottom} />
          </div>
        </div>

        <div className="border-t border-rule bg-bg">
          <form onSubmit={onSubmit} className="mx-auto max-w-3xl px-5 py-3 md:px-8">
            {sendError && (
              <p role="alert" className="mb-2 text-[13px] text-danger">
                {sendError}
              </p>
            )}
            <div className="flex items-end gap-2 rounded-lg border border-rule-strong bg-surface p-1.5 focus-within:border-accent">
              <label htmlFor="question" className="sr-only">
                Your question
              </label>
              <textarea
                id="question"
                ref={textarea}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={onKeyDown}
                rows={Math.min(6, Math.max(1, draft.split("\n").length))}
                maxLength={8000}
                placeholder="Ask a question about your documents"
                className="max-h-40 flex-1 resize-none bg-transparent px-2 py-1.5 text-[14px] leading-relaxed placeholder:text-muted focus:outline-none focus-visible:outline-none"
                autoFocus
              />
              <Button type="submit" variant="primary" size="icon" disabled={!draft.trim() || Boolean(pending)} aria-label="Send">
                <ArrowUp className="size-4" />
              </Button>
            </div>
            <p className="mt-1.5 text-[11.5px] text-muted">
              <Kbd>Enter</Kbd> to send · <Kbd>Shift</Kbd>+<Kbd>Enter</Kbd> for a new line
            </p>
          </form>
        </div>
      </section>
    </div>
  );
}

/** Group a flat message list into (question, answer) turns. */
function pairs(messages: ChatMessage[]): [ChatMessage | null, ChatMessage | null][] {
  const out: [ChatMessage | null, ChatMessage | null][] = [];
  for (const m of messages) {
    if (m.role === "user") out.push([m, null]);
    else if (m.role === "assistant") {
      const last = out[out.length - 1];
      if (last && last[1] === null && last[0]) last[1] = m;
      else out.push([null, m]);
    }
  }
  return out;
}

function Question({ text }: { text: string }) {
  return <p className="whitespace-pre-wrap font-serif text-[19px] font-semibold leading-snug">{text}</p>;
}

function Turn({
  question,
  answer,
  orgId,
  drafts,
  onDrafted,
}: {
  question: ChatMessage | null;
  answer: ChatMessage | null;
  orgId: string;
  drafts: DraftsByKind | undefined;
  onDrafted: (run: ActionRun) => void;
}) {
  const [focused, setFocused] = useState<number | null>(null);
  const sourceRefs = useRef<Record<number, HTMLLIElement | null>>({});

  function focusSource(n: number) {
    setFocused(n);
    sourceRefs.current[n]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  return (
    <article>
      {question && <Question text={question.content} />}
      {answer && (
        <div className="mt-3">
          <div className="text-[14.5px] leading-[1.65] text-ink">
            <Markdown
              source={answer.content}
              renderCitation={(n, key) => {
                const known = answer.citations.some((c) => c.citation_index === n);
                if (!known) return null;
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => focusSource(n)}
                    aria-label={`Source ${n}`}
                    className={`relative -top-[0.4em] mx-px rounded-[3px] px-1 font-mono text-[10.5px] font-medium transition-colors ${
                      focused === n ? "bg-accent text-accent-ink" : "bg-accent-soft text-accent hover:bg-accent hover:text-accent-ink"
                    }`}
                  >
                    {n}
                  </button>
                );
              }}
            />
          </div>

          {answer.citations.length > 0 ? (
            <div className="mt-4">
              <p className="mb-1.5 text-[12px] font-semibold uppercase tracking-[0.06em] text-muted">Sources</p>
              <ol className="divide-y divide-rule border-y border-rule">
                {answer.citations.map((c) => (
                  <Source
                    key={c.citation_index}
                    citation={c}
                    open={focused === c.citation_index}
                    onToggle={() => setFocused(focused === c.citation_index ? null : c.citation_index)}
                    ref={(el) => {
                      sourceRefs.current[c.citation_index] = el;
                    }}
                  />
                ))}
              </ol>
            </div>
          ) : (
            <p className="mt-4 rounded-md bg-surface-2 px-3 py-2 text-[12.5px] text-ink-2">
              No document supported this answer, so it has no sources. The question was logged under{" "}
              <Link href="/app/knowledge" className="text-accent hover:underline">
                Knowledge health
              </Link>{" "}
              so someone can fill the gap.
            </p>
          )}

          <AnswerActions orgId={orgId} answer={answer} drafts={drafts} onDrafted={onDrafted} />
        </div>
      )}
    </article>
  );
}

function Source({
  citation: c,
  open,
  onToggle,
  ref,
}: {
  citation: Citation;
  open: boolean;
  onToggle: () => void;
  ref: (el: HTMLLIElement | null) => void;
}) {
  const where = [c.section_heading, c.page_number ? `page ${c.page_number}` : null].filter(Boolean).join(" · ");
  return (
    <li ref={ref} className={open ? "bg-surface" : ""}>
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-baseline gap-2.5 px-1 py-2 text-left text-[13px] hover:bg-surface-2/50">
        <span className="w-5 shrink-0 font-mono text-[11px] text-accent">[{c.citation_index}]</span>
        <span className="min-w-0 flex-1">
          <span className="font-medium">{c.document_title ?? "Unavailable document"}</span>
          {where && <span className="ml-2 text-muted">{where}</span>}
        </span>
        <ChevronRight className={`size-3.5 shrink-0 self-center text-muted transition-transform ${open ? "rotate-90" : ""}`} />
      </button>
      {open && (
        <div className="px-1 pb-3 pl-8">
          <blockquote className="whitespace-pre-wrap border-l-2 border-accent pl-3 text-[13px] leading-relaxed text-ink-2">{passageText(c.quoted_text)}</blockquote>
          {c.document_id && (
            <Link href={`/app/documents/${c.document_id}`} className="mt-2 inline-block text-[12.5px] text-accent hover:underline">
              Open document
            </Link>
          )}
        </div>
      )}
    </li>
  );
}

type DraftKind = "task_create" | "email_draft";
type DraftsByKind = Partial<Record<DraftKind, ActionRun>>;

const DRAFT_LABEL: Record<DraftKind, { action: string; done: string; approved: string }> = {
  task_create: { action: "Turn into a task", done: "Task drafted", approved: "Task created" },
  email_draft: { action: "Draft an email", done: "Email drafted", approved: "Email approved" },
};

function AnswerActions({
  orgId,
  answer,
  drafts,
  onDrafted,
}: {
  orgId: string;
  answer: ChatMessage;
  drafts: DraftsByKind | undefined;
  onDrafted: (run: ActionRun) => void;
}) {
  const { org } = useSession();
  const toast = useToast();
  const [busy, setBusy] = useState<DraftKind | null>(null);

  // An answer without citations is a "not found" reply; there's nothing
  // verified to turn into work (the API refuses it too).
  if (!canContribute(org) || answer.citations.length === 0) return null;

  async function propose(kind: DraftKind) {
    if (busy || drafts?.[kind]) return;
    setBusy(kind);
    try {
      onDrafted(await api.proposeAction(orgId, { action_type: kind, message_id: answer.id }));
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-[12.5px]">
      {(["task_create", "email_draft"] as const).map((kind) => {
        const existing = drafts?.[kind];
        if (existing) {
          const label = existing.status === "completed" ? DRAFT_LABEL[kind].approved : DRAFT_LABEL[kind].done;
          return (
            <span key={kind} className="inline-flex items-center gap-1.5 text-ink-2">
              <Check className="size-3.5 text-accent" aria-hidden="true" />
              {label}
              {existing.status === "proposed" && (
                <>
                  {" · "}
                  <Link href="/app/actions" className="text-accent hover:underline">
                    Review it
                  </Link>
                </>
              )}
            </span>
          );
        }
        return (
          <Button
            key={kind}
            size="sm"
            variant="ghost"
            loading={busy === kind}
            disabled={Boolean(busy)}
            onClick={() => propose(kind)}
            className="-mx-2.5"
          >
            {DRAFT_LABEL[kind].action}
          </Button>
        );
      })}
    </div>
  );
}
