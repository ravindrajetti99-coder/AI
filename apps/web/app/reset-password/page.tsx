"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useState } from "react";

import { Button, Card, ErrorNote, Field, Notice } from "@/components/ui";
import { api } from "@/lib/api";

function ResetForm() {
  const token = useSearchParams().get("token") ?? "";
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const password = String(form.get("password"));
    if (password !== String(form.get("confirm"))) {
      setError(new Error("The two passwords do not match."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api("/auth/password/reset", { body: { token, new_password: password } });
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <Card className="mx-auto max-w-md">
        <h1 className="text-xl font-bold">Reset link missing</h1>
        <p className="mt-2 text-sm text-muted">
          Open the link from your email again, or{" "}
          <Link href="/forgot-password" className="font-medium text-brand-600 hover:underline">
            request a new one
          </Link>
          .
        </p>
      </Card>
    );
  }
  return (
    <Card className="mx-auto max-w-md">
      <h1 className="text-xl font-bold">Choose a new password</h1>
      {done ? (
        <div className="mt-4 space-y-4">
          <Notice tone="green">Your password is changed and you were signed out everywhere. Sign in with the new password.</Notice>
          <Link href="/login" className="text-sm font-medium text-brand-600 hover:underline">
            Sign in
          </Link>
        </div>
      ) : (
        <form onSubmit={submit} className="mt-6 space-y-4">
          <Field label="New password" name="password" type="password" autoComplete="new-password" required minLength={8} hint="At least 8 characters." />
          <Field label="Repeat the new password" name="confirm" type="password" autoComplete="new-password" required minLength={8} />
          <ErrorNote error={error} />
          <Button type="submit" busy={busy} className="w-full">
            Set new password
          </Button>
          <p className="text-sm text-muted">
            Link expired?{" "}
            <Link href="/forgot-password" className="font-medium text-brand-600 hover:underline">
              Request a new one
            </Link>
          </p>
        </form>
      )}
    </Card>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense>
      <ResetForm />
    </Suspense>
  );
}
