"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { useAuth } from "@/components/auth";
import { Card, ErrorNote, Loading, Notice } from "@/components/ui";
import { api } from "@/lib/api";

function Verify() {
  const token = useSearchParams().get("token") ?? "";
  const { me, reload } = useAuth();
  const [state, setState] = useState<{ done: boolean; error: unknown }>({ done: false, error: null });

  useEffect(() => {
    if (!token) return;
    let live = true;
    api("/auth/email/verify", { body: { token } }).then(
      () => live && setState({ done: true, error: null }),
      (error) => live && setState({ done: false, error }),
    );
    return () => {
      live = false;
    };
  }, [token]);

  const signedIn = Boolean(me);
  useEffect(() => {
    if (state.done && signedIn) void reload(); // refresh the "verified" badge
  }, [state.done, signedIn, reload]);

  return (
    <Card className="mx-auto max-w-md">
      <h1 className="text-xl font-bold">Confirm your email</h1>
      <div className="mt-4 space-y-4 text-sm">
        {!token ? (
          <p className="text-muted">This link is missing its code. Open the link from your email again.</p>
        ) : state.done ? (
          <Notice tone="green">Thank you, your email address is confirmed.</Notice>
        ) : state.error ? (
          <>
            <ErrorNote error={state.error} />
            <p className="text-muted">You can send a fresh link from your profile.</p>
          </>
        ) : (
          <Loading label="Confirming" />
        )}
        <Link href={signedIn ? "/profile" : "/login"} className="block font-medium text-brand-600 hover:underline">
          {signedIn ? "Go to your profile" : "Sign in"}
        </Link>
      </div>
    </Card>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <Verify />
    </Suspense>
  );
}
