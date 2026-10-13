"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { Loading } from "@/components/ui";
import { api, onUnauthorized, refreshSession, setAccessToken } from "@/lib/api";
import type { Me, Role, TokenOut } from "@/lib/types";

type AuthState = {
  me: Me | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string, locale: string, inviteCode?: string) => Promise<void>;
  /** Continue with tokens the API just issued (e.g. after a password change). */
  adopt: (out: TokenOut) => Promise<void>;
  logout: () => Promise<void>;
  reload: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);

  const reload = useCallback(async () => {
    setMe(await api<Me>("/me"));
  }, []);

  useEffect(() => {
    onUnauthorized(() => {
      setAccessToken(null);
      setMe(null);
    });
    // A reload loses the in-memory access token; the httpOnly refresh cookie restores it.
    refreshSession()
      .then((ok) => (ok ? reload() : undefined))
      .catch(() => setMe(null))
      .finally(() => setReady(true));
  }, [reload]);

  const value = useMemo<AuthState>(
    () => ({
      me,
      ready,
      reload,
      async login(email, password) {
        const out = await api<TokenOut>("/auth/login", { body: { email, password } });
        setAccessToken(out.access_token);
        await reload();
      },
      async register(name, email, password, locale, inviteCode) {
        const out = await api<TokenOut>("/auth/register", { body: { name, email, password, preferred_locale: locale, invite_code: inviteCode || null } });
        setAccessToken(out.access_token);
        await reload();
      },
      async adopt(out) {
        setAccessToken(out.access_token);
        await reload();
      },
      async logout() {
        await api("/auth/logout", { method: "POST" }).catch(() => undefined);
        setAccessToken(null);
        setMe(null);
      },
    }),
    [me, ready, reload],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export function isStaff(role?: Role) {
  return role === "reviewer" || role === "admin";
}

/** Renders children only for a signed-in user (optionally with one of `roles`). */
export function RequireAuth({ children, roles }: { children: ReactNode; roles?: Role[] }) {
  const { me, ready } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (ready && !me) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [ready, me, router, pathname]);

  if (!ready || !me) return <Loading label="Checking your session" />;
  if (roles && !roles.includes(me.role)) {
    return <p className="py-10 text-muted">This page is for {roles.join(" or ")} accounts.</p>;
  }
  return <>{children}</>;
}
