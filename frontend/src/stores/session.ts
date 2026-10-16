/**
 * Session store: the signed-in user, their organizations, and which one is
 * active. The active organization is remembered per browser.
 */

import { create } from "zustand";
import { api, ApiError, type Organization, type User } from "@/lib/api";

const ACTIVE_ORG_KEY = "knowops.org";

function rememberOrg(id: string | null) {
  try {
    if (id) localStorage.setItem(ACTIVE_ORG_KEY, id);
    else localStorage.removeItem(ACTIVE_ORG_KEY);
  } catch {
    // Not critical.
  }
}

function recalledOrg(): string | null {
  try {
    return localStorage.getItem(ACTIVE_ORG_KEY);
  } catch {
    return null;
  }
}

type Status = "unknown" | "loading" | "signed-in" | "signed-out";

interface SessionState {
  status: Status;
  user: User | null;
  organizations: Organization[];
  org: Organization | null;

  restore: () => Promise<void>;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, fullName: string) => Promise<void>;
  signOut: () => Promise<void>;
  setUser: (user: User) => void;
  refreshOrganizations: (preferId?: string) => Promise<void>;
  selectOrg: (id: string) => void;
}

export const useSession = create<SessionState>((set, get) => ({
  status: "unknown",
  user: null,
  organizations: [],
  org: null,

  restore: async () => {
    if (get().status === "loading" || get().status === "signed-in") return;
    if (!api.hasSession()) {
      set({ status: "signed-out" });
      return;
    }
    set({ status: "loading" });
    try {
      const user = await api.me();
      set({ user });
      await get().refreshOrganizations();
      set({ status: "signed-in" });
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) api.clearTokens();
      set({ status: "signed-out", user: null, organizations: [], org: null });
      if (!(e instanceof ApiError) || e.status === 0) throw e;
    }
  },

  signIn: async (email, password) => {
    await api.login(email, password);
    const user = await api.me();
    set({ user });
    await get().refreshOrganizations();
    set({ status: "signed-in" });
  },

  signUp: async (email, password, fullName) => {
    await api.register(email, password, fullName);
    await get().signIn(email, password);
  },

  signOut: async () => {
    await api.logout();
    rememberOrg(null);
    set({ status: "signed-out", user: null, organizations: [], org: null });
  },

  setUser: (user) => set({ user }),

  refreshOrganizations: async (preferId) => {
    const organizations = await api.organizations();
    const wanted = preferId ?? get().org?.id ?? recalledOrg();
    const org = organizations.find((o) => o.id === wanted) ?? organizations[0] ?? null;
    rememberOrg(org?.id ?? null);
    set({ organizations, org });
  },

  selectOrg: (id) => {
    const org = get().organizations.find((o) => o.id === id);
    if (!org) return;
    rememberOrg(org.id);
    set({ org });
  },
}));

/** Convenience: can the current user manage the active organization? */
export function isManager(org: Organization | null): boolean {
  return org?.role === "owner" || org?.role === "admin";
}

export function canContribute(org: Organization | null): boolean {
  return Boolean(org?.role && org.role !== "viewer");
}
