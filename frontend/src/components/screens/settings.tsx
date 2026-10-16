"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";
import { CreateOrgForm } from "@/components/app/create-org-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, FormError, Input, Select, Textarea } from "@/components/ui/field";
import { ErrorState, PageHeader, Segmented } from "@/components/ui/misc";
import { Loading } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage, type Group, type Member, type Role } from "@/lib/api";
import { formatDate, ROLE_LABEL } from "@/lib/format";
import { useData } from "@/lib/use-data";
import { isManager, useSession } from "@/stores/session";

type Tab = "account" | "organization" | "members" | "groups";

export function SettingsScreen() {
  const [tab, setTab] = useState<Tab>("account");
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Settings" />
      <div className="mb-6">
        <Segmented<Tab>
          label="Settings sections"
          value={tab}
          onChange={setTab}
          options={[
            { value: "account", label: "Your account" },
            { value: "organization", label: "Organization" },
            { value: "members", label: "Members" },
            { value: "groups", label: "Groups" },
          ]}
        />
      </div>
      {tab === "account" && <AccountTab />}
      {tab === "organization" && <OrganizationTab />}
      {tab === "members" && <MembersTab />}
      {tab === "groups" && <GroupsTab />}
    </div>
  );
}

function Section({ title, description, children }: { title: string; description?: ReactNode; children: ReactNode }) {
  return (
    <section className="grid gap-4 border-b border-rule pb-8 pt-2 md:grid-cols-[220px_1fr] [&+&]:pt-8">
      <div>
        <h2 className="text-[14px] font-semibold">{title}</h2>
        {description && <p className="mt-1 text-[13px] text-muted">{description}</p>}
      </div>
      <div className="max-w-lg">{children}</div>
    </section>
  );
}

// --- Account -------------------------------------------------------------------

function AccountTab() {
  const { user, setUser } = useSession();
  const toast = useToast();
  const [name, setName] = useState(user!.full_name);
  const [email, setEmail] = useState(user!.email);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [savingProfile, setSavingProfile] = useState(false);

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [savingPassword, setSavingPassword] = useState(false);

  const profileDirty = name.trim() !== user!.full_name || email.trim().toLowerCase() !== user!.email;

  async function saveProfile(e: FormEvent) {
    e.preventDefault();
    setSavingProfile(true);
    setProfileError(null);
    try {
      setUser(await api.updateMe({ full_name: name.trim(), email: email.trim() }));
      toast("Profile saved");
    } catch (err) {
      setProfileError(errorMessage(err));
    } finally {
      setSavingProfile(false);
    }
  }

  async function changePassword(e: FormEvent) {
    e.preventDefault();
    setPasswordError(null);
    if (next.length < 8) return setPasswordError("Use at least 8 characters.");
    if (next !== confirm) return setPasswordError("The new passwords don't match.");
    setSavingPassword(true);
    try {
      await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      toast("Password changed. Other sessions have been signed out.");
    } catch (err) {
      setPasswordError(errorMessage(err));
    } finally {
      setSavingPassword(false);
    }
  }

  return (
    <>
      <Section title="Profile">
        <form onSubmit={saveProfile} className="grid gap-4">
          <FormError message={profileError} />
          <Field label="Full name">{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} required maxLength={255} />}</Field>
          <Field label="Email">
            {(id) => <Input id={id} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />}
          </Field>
          <div>
            <Button type="submit" variant="primary" loading={savingProfile} disabled={!profileDirty || !name.trim() || !email.trim()}>
              Save profile
            </Button>
          </div>
        </form>
      </Section>
      <Section title="Password" description="Changing it signs you out everywhere else.">
        <form onSubmit={changePassword} className="grid gap-4">
          <FormError message={passwordError} />
          <Field label="Current password">
            {(id) => <Input id={id} type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />}
          </Field>
          <Field label="New password" hint="At least 8 characters.">
            {(id, d) => <Input id={id} aria-describedby={d} type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required />}
          </Field>
          <Field label="Confirm new password">
            {(id) => <Input id={id} type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />}
          </Field>
          <div>
            <Button type="submit" loading={savingPassword} disabled={!current || !next || !confirm}>
              Change password
            </Button>
          </div>
        </form>
      </Section>
    </>
  );
}

// --- Organization --------------------------------------------------------------

function OrganizationTab() {
  const { org, user, refreshOrganizations, organizations } = useSession();
  const router = useRouter();
  const toast = useToast();
  const manager = isManager(org);
  const [name, setName] = useState(org!.name);
  const [description, setDescription] = useState(org!.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [leaving, setLeaving] = useState(false);

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.updateOrganization(org!.id, { name: name.trim(), description: description.trim() });
      await refreshOrganizations(org!.id);
      toast("Organization updated");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function leave() {
    if (!window.confirm(`Leave ${org!.name}? You'll lose access to its documents.`)) return;
    setLeaving(true);
    try {
      await api.removeMember(org!.id, user!.id);
      const remaining = organizations.find((o) => o.id !== org!.id);
      await refreshOrganizations(remaining?.id);
      router.push("/app");
    } catch (err) {
      toast(errorMessage(err), "error");
      setLeaving(false);
    }
  }

  return (
    <>
      <Section title="Details" description={manager ? undefined : "Only owners and admins can change these."}>
        <form onSubmit={save} className="grid gap-4">
          <FormError message={error} />
          <Field label="Name">{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} disabled={!manager} required maxLength={255} />}</Field>
          <Field label="URL name">{(id) => <Input id={id} value={org!.slug} disabled className="font-mono" />}</Field>
          <Field label="Description">
            {(id) => <Textarea id={id} rows={3} value={description} onChange={(e) => setDescription(e.target.value)} disabled={!manager} maxLength={2000} />}
          </Field>
          {manager && (
            <div>
              <Button
                type="submit"
                variant="primary"
                loading={saving}
                disabled={!name.trim() || (name.trim() === org!.name && description.trim() === (org!.description ?? ""))}
              >
                Save
              </Button>
            </div>
          )}
        </form>
      </Section>
      <Section title="Create another organization" description="Each organization has its own documents, members and settings.">
        <CreateOrgForm
          submitLabel="Create organization"
          onCreated={async (created) => {
            await refreshOrganizations(created.id);
            toast(`Switched to ${created.name}`);
            router.push("/app");
          }}
        />
      </Section>
      <Section title="Leave organization" description="Owners must hand ownership to someone else first.">
        <Button variant="danger" onClick={leave} loading={leaving}>
          Leave {org!.name}
        </Button>
      </Section>
    </>
  );
}

// --- Members -------------------------------------------------------------------

function MembersTab() {
  const { org, user } = useSession();
  const orgId = org!.id;
  const toast = useToast();
  const manager = isManager(org);
  const owner = org!.role === "owner";
  const members = useData(() => api.members(orgId), [orgId]);
  const invitations = useData(manager ? () => api.invitations(orgId) : null, [orgId, manager]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function add(e: FormEvent) {
    e.preventDefault();
    setAdding(true);
    setError(null);
    try {
      const result = await api.addMember(orgId, email.trim(), role);
      setEmail("");
      if (result.status === "added") {
        await members.reload();
        toast(`${result.member?.user_name ?? "They"} can now use ${org!.name}.`);
      } else {
        await invitations.reload();
        toast(`Invited ${result.invitation?.email}. Copy their invitation link and share it with them privately.`);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setAdding(false);
    }
  }

  async function mutate(id: string, action: () => Promise<unknown>) {
    setBusy(id);
    try {
      await action();
      await members.reload();
    } catch (err) {
      toast(errorMessage(err), "error");
    } finally {
      setBusy(null);
    }
  }

  if (members.error) return <ErrorState message={members.error} onRetry={members.reload} />;
  if (!members.data) return <Loading />;

  return (
    <>
      {manager && (
        <Section
          title="Add people"
          description="Create an invitation, then share its private link with the intended person. Links expire after seven days."
        >
          <form onSubmit={add} className="grid gap-3">
            <FormError message={error} />
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Email" className="min-w-56 flex-1">
                {(id) => <Input id={id} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />}
              </Field>
              <Field label="Role">
                {(id) => (
                  <Select id={id} value={role} onChange={(e) => setRole(e.target.value as Role)} className="w-32">
                    {owner && <option value="owner">Owner</option>}
                    <option value="admin">Admin</option>
                    <option value="member">Member</option>
                    <option value="viewer">Viewer</option>
                  </Select>
                )}
              </Field>
              <Button type="submit" variant="primary" loading={adding} disabled={!email.trim()}>
                Add
              </Button>
            </div>

          </form>
        </Section>
      )}
      {manager && invitations.data && invitations.data.length > 0 && (
        <section className="pt-6">
          <h2 className="mb-2 text-[12px] font-semibold uppercase tracking-[0.06em] text-muted">
            Invited · waiting for acceptance
          </h2>
          <ul className="divide-y divide-rule border-y border-rule">
            {invitations.data.map((inv) => (
              <li key={inv.id} className="flex flex-wrap items-center gap-3 px-1 py-2.5 text-[13.5px]">
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{inv.email}</p>
                  <p className="truncate text-[12.5px] text-muted">
                    Invited {formatDate(inv.created_at)}
                    {inv.invited_by_name && ` by ${inv.invited_by_name}`}
                  </p>
                </div>
                <Badge>{ROLE_LABEL[inv.role]}</Badge>
                <Button size="sm" variant="ghost" onClick={() => {
                  const link = `${window.location.origin}/register#invitation=${encodeURIComponent(inv.token)}`;
                  navigator.clipboard.writeText(link).then(
                    () => toast("Invitation link copied; share it privately"),
                    () => toast(link),
                  );
                }}>Copy invitation link</Button>
                <Button
                  size="sm"
                  variant="ghost"
                  loading={busy === inv.id}
                  onClick={async () => {
                    setBusy(inv.id);
                    try {
                      await api.cancelInvitation(orgId, inv.id);
                      await invitations.reload();
                    } catch (err) {
                      toast(errorMessage(err), "error");
                    } finally {
                      setBusy(null);
                    }
                  }}
                >
                  Cancel
                </Button>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="pt-6">
        <dl className="mb-4 grid gap-x-6 gap-y-1 text-[12.5px] text-muted sm:grid-cols-2">
          <div><span className="font-medium text-ink-2">Owner / Admin</span> — manage members, groups, every document, and run scans.</div>
          <div><span className="font-medium text-ink-2">Member</span> — upload documents, ask questions, create tasks.</div>
          <div><span className="font-medium text-ink-2">Viewer</span> — read and ask only.</div>
        </dl>
        <ul className="divide-y divide-rule border-y border-rule">
          {members.data.map((m: Member) => {
            const self = m.user_id === user!.id;
            return (
              <li key={m.id} className="flex flex-wrap items-center gap-3 px-1 py-2.5 text-[13.5px]">
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">
                    {m.user_name} {self && <span className="font-normal text-muted">(you)</span>}
                  </p>
                  <p className="truncate text-[12.5px] text-muted">
                    {m.user_email} · joined {formatDate(m.created_at)}
                  </p>
                </div>
                {owner && !self ? (
                  <Select
                    aria-label={`Role for ${m.user_name}`}
                    value={m.role}
                    disabled={busy === m.user_id}
                    onChange={(e) => mutate(m.user_id, () => api.changeRole(orgId, m.user_id, e.target.value as Role))}
                    className="h-7 w-28 text-[13px]"
                  >
                    <option value="owner">Owner</option>
                    <option value="admin">Admin</option>
                    <option value="member">Member</option>
                    <option value="viewer">Viewer</option>
                  </Select>
                ) : (
                  <Badge tone={m.role === "owner" || m.role === "admin" ? "accent" : "neutral"}>{ROLE_LABEL[m.role]}</Badge>
                )}
                {manager && !self && m.role !== "owner" && (owner || m.role !== "admin") && (
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={busy === m.user_id}
                    onClick={() => {
                      if (window.confirm(`Remove ${m.user_name} from ${org!.name}?`)) void mutate(m.user_id, () => api.removeMember(orgId, m.user_id));
                    }}
                  >
                    Remove
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      </section>
    </>
  );
}

// --- Groups --------------------------------------------------------------------

function GroupsTab() {
  const { org } = useSession();
  const orgId = org!.id;
  const toast = useToast();
  const manager = isManager(org);
  const groups = useData(() => api.groups(orgId), [orgId]);
  const members = useData(manager ? () => api.members(orgId) : null, [orgId, manager]);
  const [name, setName] = useState("");
  const [department, setDepartment] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  async function create(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      await api.createGroup(orgId, { name: name.trim(), department: department.trim() || undefined });
      setName("");
      setDepartment("");
      await groups.reload();
      toast("Group created");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  if (groups.error) return <ErrorState message={groups.error} onRetry={groups.reload} />;
  if (!groups.data) return <Loading />;

  return (
    <>
      <p className="mb-6 max-w-2xl text-[13.5px] text-ink-2">
        Groups let you share a restricted document with a whole team at once, from the document&apos;s Access tab.
      </p>
      {manager && (
        <Section title="New group">
          <form onSubmit={create} className="grid gap-3">
            <FormError message={error} />
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Name" className="min-w-40 flex-1">
                {(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} required maxLength={255} placeholder="People team" />}
              </Field>
              <Field label="Department" className="min-w-32 flex-1">
                {(id) => <Input id={id} value={department} onChange={(e) => setDepartment(e.target.value)} maxLength={255} placeholder="HR" />}
              </Field>
              <Button type="submit" variant="primary" loading={creating} disabled={!name.trim()}>
                Create
              </Button>
            </div>
          </form>
        </Section>
      )}
      <section className="pt-6">
        {groups.data.length === 0 ? (
          <p className="text-[13.5px] text-muted">No groups yet.</p>
        ) : (
          <ul className="divide-y divide-rule border-y border-rule">
            {groups.data.map((g) => (
              <GroupRow
                key={g.id}
                group={g}
                orgId={orgId}
                open={open === g.id}
                onToggle={() => setOpen(open === g.id ? null : g.id)}
                manager={manager}
                members={members.data ?? []}
                onChanged={groups.reload}
              />
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function GroupRow({
  group: g,
  orgId,
  open,
  onToggle,
  manager,
  members,
  onChanged,
}: {
  group: Group;
  orgId: string;
  open: boolean;
  onToggle: () => void;
  manager: boolean;
  members: Member[];
  onChanged: () => Promise<void>;
}) {
  const toast = useToast();
  const groupMembers = useData(open ? () => api.groupMembers(orgId, g.id) : null, [orgId, g.id, open]);
  const [adding, setAdding] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  async function mutate(key: string, action: () => Promise<unknown>) {
    setBusy(key);
    try {
      await action();
      await Promise.all([groupMembers.reload(), onChanged()]);
    } catch (err) {
      toast(errorMessage(err), "error");
    } finally {
      setBusy(null);
    }
  }

  const inGroup = new Set((groupMembers.data ?? []).map((m) => m.user_id));

  return (
    <li>
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-center gap-3 px-1 py-2.5 text-left text-[13.5px] hover:bg-surface-2/50">
        <span className="min-w-0 flex-1">
          <span className="font-medium">{g.name}</span>
          {g.department && <span className="ml-2 text-muted">{g.department}</span>}
        </span>
        <span className="tabular text-[12.5px] text-muted">
          {g.member_count} member{g.member_count === 1 ? "" : "s"}
        </span>
      </button>
      {open && (
        <div className="pb-4 pl-4 pr-1">
          {groupMembers.loading ? (
            <Loading />
          ) : (
            <>
              {(groupMembers.data ?? []).length === 0 ? (
                <p className="mb-3 text-[13px] text-muted">No one in this group yet.</p>
              ) : (
                <ul className="mb-3 space-y-1">
                  {groupMembers.data!.map((m) => (
                    <li key={m.user_id} className="flex items-center gap-3 text-[13px]">
                      <span className="flex-1">
                        {m.user_name} <span className="text-muted">{m.user_email}</span>
                      </span>
                      {manager && (
                        <Button size="sm" variant="ghost" loading={busy === m.user_id} onClick={() => mutate(m.user_id, () => api.removeGroupMember(orgId, g.id, m.user_id))}>
                          Remove
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {manager && (
                <div className="flex flex-wrap items-center gap-2">
                  <Select aria-label="Add member to group" value={adding} onChange={(e) => setAdding(e.target.value)} className="h-7 w-60 text-[13px]">
                    <option value="">Add a member…</option>
                    {members
                      .filter((m) => !inGroup.has(m.user_id))
                      .map((m) => (
                        <option key={m.user_id} value={m.user_id}>
                          {m.user_name}
                        </option>
                      ))}
                  </Select>
                  <Button
                    size="sm"
                    disabled={!adding}
                    loading={busy === "add"}
                    onClick={() =>
                      mutate("add", async () => {
                        await api.addGroupMember(orgId, g.id, adding);
                        setAdding("");
                      })
                    }
                  >
                    Add
                  </Button>
                  <span className="flex-1" />
                  <Button
                    size="sm"
                    variant="danger"
                    loading={busy === "delete"}
                    onClick={() => {
                      if (window.confirm(`Delete the group “${g.name}”? Documents shared only with it will no longer be shared with its members.`))
                        void mutate("delete", () => api.deleteGroup(orgId, g.id));
                    }}
                  >
                    Delete group
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </li>
  );
}
