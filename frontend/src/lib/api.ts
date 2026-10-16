/**
 * KnowOps API client.
 *
 * A thin fetch wrapper that attaches the access token, transparently rotates
 * it once on a 401, and turns every failure into an `ApiError` with a
 * human-readable message.
 */

const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");
const ACCESS_KEY = "knowops.access";
const REFRESH_KEY = "knowops.refresh";

// --- Types -----------------------------------------------------------------

export type Role = "owner" | "admin" | "member" | "viewer";

export interface User {
  id: string;
  email: string;
  full_name: string;
  status: string;
  email_verified: boolean;
  created_at: string;
  updated_at: string;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  role: Role | null;
  created_at: string;
  updated_at: string;
}

export interface Member {
  id: string;
  user_id: string;
  organization_id: string;
  role: Role;
  status: string;
  user_email: string | null;
  user_name: string | null;
  created_at: string;
}

export interface Invitation {
  token: string;
  id: string;
  organization_id: string;
  email: string;
  role: Role;
  invited_by: string | null;
  invited_by_name: string | null;
  created_at: string;
}

export interface InviteResult {
  /** Invitations require the signed link shared by an administrator. */
  status: "added" | "invited";
  member: Member | null;
  invitation: Invitation | null;
}

export interface Group {
  id: string;
  organization_id: string;
  name: string;
  department: string | null;
  description: string | null;
  member_count: number;
  created_at: string;
}

export interface GroupMember {
  user_id: string;
  user_email: string;
  user_name: string;
  added_at: string;
}

export type DocumentStatus = "uploaded" | "processing" | "ready" | "failed" | "archived";

export interface DocumentItem {
  id: string;
  organization_id: string;
  title: string;
  description: string | null;
  file_type: string;
  original_filename: string;
  status: DocumentStatus;
  category: string | null;
  department: string | null;
  tags: string[] | null;
  active_version_id: string | null;
  owner_id: string | null;
  /** Visible only to the owner, admins, and explicit grantees. */
  restricted: boolean;
  created_at: string;
  updated_at: string;
}

export interface DocumentDetail extends DocumentItem {
  owner_name: string | null;
  version_count: number;
  latest_version_status: string | null;
  latest_version_error: string | null;
  my_permission: "view" | "edit" | "manage" | null;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface DocumentVersion {
  id: string;
  document_id: string;
  version_number: number;
  file_size_bytes: number;
  page_count: number | null;
  status: string;
  error_message: string | null;
  uploaded_by: string | null;
  is_active: boolean;
  created_at: string;
}

export interface DocumentPermission {
  id: string;
  document_id: string;
  subject_type: "user" | "group";
  subject_id: string;
  subject_name: string | null;
  permission: "view" | "edit" | "manage";
  granted_by: string | null;
  created_at: string;
}

export interface DiffLine {
  kind: "context" | "added" | "removed";
  text: string;
  base_line: number | null;
  target_line: number | null;
}

export interface VersionRef {
  id: string;
  version_number: number;
  created_at: string;
}

export interface Comparison {
  document_id: string;
  base: VersionRef;
  target: VersionRef;
  added: number;
  removed: number;
  unchanged: number;
  truncated: boolean;
  hunks: { base_start: number; target_start: number; lines: DiffLine[] }[];
}

export interface ConversationSummary {
  id: string;
  organization_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Citation {
  citation_index: number;
  document_id: string | null;
  document_title: string | null;
  document_version_id: string;
  chunk_id: string;
  quoted_text: string;
  page_number: number | null;
  section_heading: string | null;
  relevance_score: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  model_used: string | null;
  token_count: number | null;
  created_at: string;
  citations: Citation[];
}

export type FindingType = "conflict" | "gap" | "stale" | "unanswered";
export type FindingStatus = "open" | "in_review" | "resolved" | "dismissed";

export interface Passage {
  document_id: string;
  document_title: string;
  version_id: string;
  chunk_id: string;
  text: string;
  page_number: number | null;
  section_heading: string | null;
}

export interface Finding {
  id: string;
  organization_id: string;
  finding_type: FindingType;
  title: string;
  description: string;
  evidence: {
    passages?: Passage[];
    similarity?: number;
    count?: number;
    occurrences?: { asked_by: string; conversation_id: string; asked_at: string; had_sources: boolean }[];
    document_title?: string;
    version_number?: number;
    uploaded_at?: string;
    age_days?: number;
  };
  severity: "low" | "medium" | "high" | "critical";
  status: FindingStatus;
  related_documents: string[];
  assigned_to: string | null;
  assigned_to_name: string | null;
  resolved_by: string | null;
  resolution_notes: string | null;
  detected_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScanState {
  status: "idle" | "queued" | "running" | "completed" | "failed";
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  summary: Record<string, number | string> | null;
}

export interface QualitySummary {
  open_by_type: Record<FindingType, number>;
  total_open: number;
  resolved: number;
  documents_ready: number;
  documents_processing: number;
  documents_failed: number;
  indexed_chunks: number;
  embedding_model: string;
  scan: ScanState;
}

export interface ChecklistItem {
  text: string;
  done: boolean;
}

export interface TaskPayload {
  title: string;
  description: string;
  priority: Priority;
  checklist: ChecklistItem[];
  due_date: string | null;
}

export interface EmailPayload {
  subject: string;
  to: string[];
  body: string;
}

export interface SourceReference {
  document_id?: string;
  document_title?: string;
  quoted_text?: string;
  page_number?: number | null;
  section_heading?: string | null;
  citation_index?: number;
  conversation_id?: string;
}

export type Priority = "low" | "medium" | "high" | "urgent";
export type TaskStatus = "draft" | "todo" | "in_progress" | "completed" | "cancelled";

export interface ActionRun {
  id: string;
  organization_id: string;
  action_type: "task_create" | "email_draft";
  status: "proposed" | "approved" | "rejected" | "executing" | "completed" | "failed";
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error_message: string | null;
  proposed_by: string | null;
  proposed_by_name: string | null;
  /** The assistant answer this draft was generated from, if any. */
  source_message_id: string | null;
  approved_by: string | null;
  source_references: SourceReference[];
  approved_at: string | null;
  executed_at: string | null;
  created_at: string;
}

export interface Task {
  id: string;
  organization_id: string;
  title: string;
  description: string | null;
  status: TaskStatus;
  priority: Priority;
  assignee_id: string | null;
  assignee_name: string | null;
  created_by: string | null;
  created_by_name: string | null;
  due_date: string | null;
  checklist: ChecklistItem[];
  source_references: SourceReference[];
  created_at: string;
  updated_at: string;
}

interface TokenPair {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

// --- Errors ----------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function errorMessage(error: unknown, fallback = "Something went wrong"): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

// --- Token storage ----------------------------------------------------------

function readStorage(key: string): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string | null) {
  try {
    if (typeof window === "undefined") return;
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // Storage may be unavailable (private mode); tokens stay in memory.
  }
}

// --- Client ------------------------------------------------------------------

type Query = Record<string, string | number | undefined | null>;

function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

const NO_REFRESH = new Set(["/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh"]);

class ApiClient {
  private accessToken: string | null = null;
  private refreshToken: string | null = null;
  private loaded = false;
  private refreshing: Promise<boolean> | null = null;
  /** Called when the session can no longer be refreshed. */
  onSessionExpired: (() => void) | null = null;

  private load() {
    if (this.loaded || typeof window === "undefined") return;
    this.accessToken = readStorage(ACCESS_KEY);
    this.refreshToken = readStorage(REFRESH_KEY);
    this.loaded = true;
  }

  hasSession(): boolean {
    this.load();
    return Boolean(this.accessToken || this.refreshToken);
  }

  private setTokens(tokens: TokenPair) {
    this.accessToken = tokens.access_token;
    this.refreshToken = tokens.refresh_token;
    writeStorage(ACCESS_KEY, tokens.access_token);
    writeStorage(REFRESH_KEY, tokens.refresh_token);
  }

  clearTokens() {
    this.accessToken = null;
    this.refreshToken = null;
    writeStorage(ACCESS_KEY, null);
    writeStorage(REFRESH_KEY, null);
  }

  private async refresh(): Promise<boolean> {
    if (!this.refreshToken) return false;
    // Share one in-flight refresh between concurrent 401s.
    const rotate = async (): Promise<boolean> => {
      // Another tab may have rotated while this tab waited for the lock.
      const sharedAccess = readStorage(ACCESS_KEY);
      const sharedRefresh = readStorage(REFRESH_KEY);
      if (sharedRefresh && sharedRefresh !== this.refreshToken && sharedAccess) {
        this.accessToken = sharedAccess;
        this.refreshToken = sharedRefresh;
        return true;
      }
      const token = this.refreshToken;
      if (!token) return false;
      try {
        const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: token }),
        });
        if (!res.ok || this.refreshToken !== token) return false;
        this.setTokens((await res.json()) as TokenPair);
        return true;
      } catch {
        return false;
      }
    };
    this.refreshing = (async () => {
      try {
        // Web Locks serialize rotation across tabs on the same origin.
        // Browsers without this API must sign in again when access expires.
        if (typeof navigator === "undefined" || !navigator.locks) return false;
        return await navigator.locks.request("knowops.refresh", rotate);
      } finally {
        setTimeout(() => (this.refreshing = null), 0);
      }
    })();
    return this.refreshing;
  }

  private async send(path: string, init: RequestInit): Promise<Response> {
    const headers = new Headers(init.headers);
    if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (this.accessToken) headers.set("Authorization", `Bearer ${this.accessToken}`);
    try {
      return await fetch(`${API_BASE}${path}`, { ...init, headers });
    } catch {
      throw new ApiError(
        "Can't reach the KnowOps server. Check your connection and try again.",
        "NETWORK_ERROR",
        0,
      );
    }
  }

  async raw(path: string, init: RequestInit = {}): Promise<Response> {
    this.load();
    let res = await this.send(path, init);
    if (res.status === 401 && !NO_REFRESH.has(path.split("?")[0])) {
      if (await this.refresh()) {
        res = await this.send(path, init);
      } else if (this.accessToken || this.refreshToken) {
        this.clearTokens();
        this.onSessionExpired?.();
      }
    }
    if (!res.ok) throw await toError(res);
    return res;
  }

  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const res = await this.raw(path, init);
    if (res.status === 204) return undefined as T;
    const text = await res.text();
    return (text ? JSON.parse(text) : undefined) as T;
  }

  private json<T>(method: string, path: string, body?: unknown): Promise<T> {
    return this.request<T>(path, {
      method,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  // --- Auth ---

  async login(email: string, password: string) {
    const tokens = await this.json<TokenPair>("POST", "/api/v1/auth/login", { email, password });
    this.setTokens(tokens);
  }

  register(email: string, password: string, fullName: string) {
    return this.json<{ id: string }>("POST", "/api/v1/auth/register", {
      email,
      password,
      full_name: fullName,
    });
  }

  async logout() {
    try {
      if (this.accessToken) await this.json<void>("POST", "/api/v1/auth/logout");
    } catch {
      // The local session ends regardless.
    } finally {
      this.clearTokens();
    }
  }

  me = () => this.json<User>("GET", "/api/v1/auth/me");
  updateMe = (body: { full_name?: string; email?: string }) =>
    this.json<User>("PATCH", "/api/v1/auth/me", body);
  changePassword = (current_password: string, new_password: string) =>
    this.json<void>("POST", "/api/v1/auth/change-password", { current_password, new_password });

  // --- Organizations ---

  organizations = () => this.json<Organization[]>("GET", "/api/v1/organizations");
  createOrganization = (body: { name: string; slug: string; description?: string }) =>
    this.json<Organization>("POST", "/api/v1/organizations", body);
  updateOrganization = (orgId: string, body: { name?: string; description?: string }) =>
    this.json<Organization>("PATCH", `/api/v1/organizations/${orgId}`, body);
  members = (orgId: string) => this.json<Member[]>("GET", `/api/v1/organizations/${orgId}/members`);
  addMember = (orgId: string, email: string, role: Role) =>
    this.json<InviteResult>("POST", `/api/v1/organizations/${orgId}/members`, { email, role });
  acceptInvitation = (token: string) =>
    this.json<Member>("POST", "/api/v1/organizations/invitations/accept", { token });
  invitations = (orgId: string) =>
    this.json<Invitation[]>("GET", `/api/v1/organizations/${orgId}/invitations`);
  cancelInvitation = (orgId: string, invitationId: string) =>
    this.json<void>("DELETE", `/api/v1/organizations/${orgId}/invitations/${invitationId}`);
  removeMember = (orgId: string, userId: string) =>
    this.json<void>("DELETE", `/api/v1/organizations/${orgId}/members/${userId}`);
  changeRole = (orgId: string, userId: string, role: Role) =>
    this.json<Member>("PATCH", `/api/v1/organizations/${orgId}/members/${userId}/role`, { role });
  groups = (orgId: string) => this.json<Group[]>("GET", `/api/v1/organizations/${orgId}/groups`);
  createGroup = (orgId: string, body: { name: string; department?: string; description?: string }) =>
    this.json<Group>("POST", `/api/v1/organizations/${orgId}/groups`, body);
  deleteGroup = (orgId: string, groupId: string) =>
    this.json<void>("DELETE", `/api/v1/organizations/${orgId}/groups/${groupId}`);
  groupMembers = (orgId: string, groupId: string) =>
    this.json<GroupMember[]>("GET", `/api/v1/organizations/${orgId}/groups/${groupId}/members`);
  addGroupMember = (orgId: string, groupId: string, userId: string) =>
    this.json<void>("POST", `/api/v1/organizations/${orgId}/groups/${groupId}/members`, {
      user_id: userId,
    });
  removeGroupMember = (orgId: string, groupId: string, userId: string) =>
    this.json<void>(
      "DELETE",
      `/api/v1/organizations/${orgId}/groups/${groupId}/members/${userId}`,
    );

  // --- Documents ---

  private docs = (orgId: string) => `/api/v1/organizations/${orgId}/documents`;

  documents = (
    orgId: string,
    query: { page?: number; per_page?: number; search?: string; status?: string } = {},
  ) => this.json<Paginated<DocumentItem>>("GET", withQuery(this.docs(orgId), query));
  document = (orgId: string, docId: string) =>
    this.json<DocumentDetail>("GET", `${this.docs(orgId)}/${docId}`);
  uploadDocument = (
    orgId: string,
    file: File,
    meta: { title?: string; description?: string; category?: string; department?: string; tags?: string[] },
  ) => {
    const form = new FormData();
    form.append("file", file);
    if (meta.title) form.append("title", meta.title);
    if (meta.description) form.append("description", meta.description);
    if (meta.category) form.append("category", meta.category);
    if (meta.department) form.append("department", meta.department);
    if (meta.tags?.length) form.append("tags", JSON.stringify(meta.tags));
    return this.request<{ id: string; title: string }>(this.docs(orgId), { method: "POST", body: form });
  };
  updateDocument = (
    orgId: string,
    docId: string,
    body: Partial<Pick<DocumentItem, "title" | "description" | "category" | "department" | "tags">>,
  ) => this.json<DocumentItem>("PATCH", `${this.docs(orgId)}/${docId}`, body);
  archiveDocument = (orgId: string, docId: string) =>
    this.json<void>("DELETE", `${this.docs(orgId)}/${docId}`);
  restoreDocument = (orgId: string, docId: string) =>
    this.json<DocumentItem>("POST", `${this.docs(orgId)}/${docId}/restore`);
  reprocessDocument = (orgId: string, docId: string) =>
    this.json<DocumentVersion>("POST", `${this.docs(orgId)}/${docId}/reprocess`);
  versions = (orgId: string, docId: string) =>
    this.json<DocumentVersion[]>("GET", `${this.docs(orgId)}/${docId}/versions`);
  uploadVersion = (orgId: string, docId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return this.request<DocumentVersion>(`${this.docs(orgId)}/${docId}/versions`, {
      method: "POST",
      body: form,
    });
  };
  compare = (orgId: string, docId: string, base?: string, target?: string) =>
    this.json<Comparison>("GET", withQuery(`${this.docs(orgId)}/${docId}/compare`, { base, target }));
  compareSummary = (orgId: string, docId: string, base?: string, target?: string) =>
    this.json<{ summary: string }>(
      "POST",
      withQuery(`${this.docs(orgId)}/${docId}/compare/summary`, { base, target }),
    );
  setDocumentAccess = (orgId: string, docId: string, restricted: boolean) =>
    this.json<DocumentItem>("PUT", `${this.docs(orgId)}/${docId}/access`, { restricted });
  permissions = (orgId: string, docId: string) =>
    this.json<DocumentPermission[]>("GET", `${this.docs(orgId)}/${docId}/permissions`);
  grant = (
    orgId: string,
    docId: string,
    body: { subject_type: "user" | "group"; subject_id: string; permission: string },
  ) => this.json<DocumentPermission>("POST", `${this.docs(orgId)}/${docId}/permissions`, body);
  revoke = (orgId: string, docId: string, subject_type: string, subject_id: string) =>
    this.json<void>(
      "DELETE",
      withQuery(`${this.docs(orgId)}/${docId}/permissions`, { subject_type, subject_id }),
    );

  async download(orgId: string, docId: string, versionId?: string) {
    const res = await this.raw(
      withQuery(`${this.docs(orgId)}/${docId}/download`, { version_id: versionId }),
    );
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") ?? "";
    const encoded = /filename\*=UTF-8''([^;]+)/.exec(disposition)?.[1];
    const plain = /filename="([^"]+)"/.exec(disposition)?.[1];
    const name = encoded ? decodeURIComponent(encoded) : plain ?? "document";
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // --- Conversations ---

  private convs = (orgId: string) => `/api/v1/organizations/${orgId}/conversations`;

  conversations = (orgId: string) => this.json<ConversationSummary[]>("GET", this.convs(orgId));
  createConversation = (orgId: string) =>
    this.json<ConversationSummary>("POST", this.convs(orgId), {});
  conversation = (orgId: string, id: string) =>
    this.json<{ conversation: ConversationSummary; messages: ChatMessage[] }>(
      "GET",
      `${this.convs(orgId)}/${id}`,
    );
  renameConversation = (orgId: string, id: string, title: string) =>
    this.json<ConversationSummary>("PATCH", `${this.convs(orgId)}/${id}`, { title });
  deleteConversation = (orgId: string, id: string) =>
    this.json<void>("DELETE", `${this.convs(orgId)}/${id}`);
  sendMessage = (orgId: string, id: string, content: string) =>
    this.json<{ conversation_id: string; user_message: ChatMessage; assistant_message: ChatMessage }>(
      "POST",
      `${this.convs(orgId)}/${id}/messages`,
      { content },
    );

  // --- Knowledge quality ---

  private kq = (orgId: string) => `/api/v1/organizations/${orgId}/knowledge`;

  qualitySummary = (orgId: string) => this.json<QualitySummary>("GET", `${this.kq(orgId)}/summary`);
  findings = (orgId: string, query: { type?: string; status?: string } = {}) =>
    this.json<Finding[]>("GET", withQuery(`${this.kq(orgId)}/findings`, query));
  updateFinding = (
    orgId: string,
    id: string,
    body: { status?: FindingStatus; resolution_notes?: string; assigned_to?: string },
  ) => this.json<Finding>("PATCH", `${this.kq(orgId)}/findings/${id}`, body);
  scanState = (orgId: string) => this.json<ScanState>("GET", `${this.kq(orgId)}/scan`);
  startScan = (orgId: string) => this.json<ScanState>("POST", `${this.kq(orgId)}/scan`);

  // --- Actions & tasks ---

  private org = (orgId: string) => `/api/v1/organizations/${orgId}`;

  actions = (orgId: string, status?: string) =>
    this.json<ActionRun[]>("GET", withQuery(`${this.org(orgId)}/actions`, { status }));
  proposeAction = (
    orgId: string,
    body: {
      action_type: "task_create" | "email_draft";
      message_id?: string;
      instructions?: string;
      payload?: Record<string, unknown>;
    },
  ) => this.json<ActionRun>("POST", `${this.org(orgId)}/actions`, body);
  updateAction = (orgId: string, id: string, payload: Record<string, unknown>) =>
    this.json<ActionRun>("PATCH", `${this.org(orgId)}/actions/${id}`, { payload });
  approveAction = (orgId: string, id: string) =>
    this.json<ActionRun>("POST", `${this.org(orgId)}/actions/${id}/approve`);
  rejectAction = (orgId: string, id: string) =>
    this.json<ActionRun>("POST", `${this.org(orgId)}/actions/${id}/reject`);
  tasks = (orgId: string, query: { status?: string; assignee?: string } = {}) =>
    this.json<Task[]>("GET", withQuery(`${this.org(orgId)}/tasks`, query));
  createTask = (
    orgId: string,
    body: {
      title: string;
      description?: string;
      priority?: Priority;
      assignee_id?: string | null;
      due_date?: string | null;
      checklist?: ChecklistItem[];
    },
  ) => this.json<Task>("POST", `${this.org(orgId)}/tasks`, body);
  updateTask = (orgId: string, id: string, body: Partial<Omit<Task, "id">>) =>
    this.json<Task>("PATCH", `${this.org(orgId)}/tasks/${id}`, body);
  deleteTask = (orgId: string, id: string) =>
    this.json<void>("DELETE", `${this.org(orgId)}/tasks/${id}`);
}

async function toError(res: Response): Promise<ApiError> {
  let detail = "";
  let code = "HTTP_ERROR";
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") detail = body.detail;
    else if (Array.isArray(body?.detail)) detail = body.detail.map((d: { msg?: string }) => d.msg).join("; ");
    if (typeof body?.error_code === "string") code = body.error_code;
  } catch {
    // Non-JSON error body (proxy error page etc.).
  }
  if (!detail) {
    detail =
      res.status >= 500
        ? "The server ran into a problem. Please try again."
        : res.status === 404
          ? "Not found."
          : `Request failed (${res.status}).`;
  }
  return new ApiError(detail, code, res.status);
}

export const api = new ApiClient();
