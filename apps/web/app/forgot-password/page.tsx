"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { Button, Card, ErrorNote, Field, Notice } from "@/components/ui";
import { api } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await api("/auth/password/forgot", { body: { email: String(form.get("email")) } });
      setSent(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mx-auto max-w-md">
      <h1 className="text-xl font-bold">Reset your password</h1>
      {sent ? (
        <div className="mt-4 space-y-4">
          <Notice tone="green">If an account uses this address, a reset link is on its way. It works for 30 minutes. Check your spam folder too.</Notice>
          <Link href="/login" className="text-sm font-medium text-brand-600 hover:underline">
            Back to sign in
          </Link>
        </div>
      ) : (
        <>
          <p className="mt-1 text-sm text-muted">Enter the email you signed up with and we will send you a link to choose a new password.</p>
          <form onSubmit={submit} className="mt-6 space-y-4">
            <Field label="Email" name="email" type="email" autoComplete="email" required />
            <ErrorNote error={error} />
            <Button type="submit" busy={busy} className="w-full">
              Send reset link
            </Button>
          </form>
          <p className="mt-4 text-sm text-muted">
            Remembered it?{" "}
            <Link href="/login" className="font-medium text-brand-600 hover:underline">
              Sign in
            </Link>
          </p>
        </>
      )}
    </Card>
  );
}
