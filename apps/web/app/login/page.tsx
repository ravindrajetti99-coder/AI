"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useState } from "react";

import { useAuth } from "@/components/auth";
import { Button, Card, ErrorNote, Field } from "@/components/ui";

function safeNext(next: string | null) {
  // Only same-site paths: never redirect to another origin after sign-in.
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
}

function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await login(String(form.get("email")), String(form.get("password")));
      router.push(safeNext(params.get("next")));
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <Card className="mx-auto max-w-md">
      <h1 className="text-xl font-bold">Welcome back</h1>
      <p className="mt-1 text-sm text-muted">Sign in to continue your plan.</p>
      <form onSubmit={submit} className="mt-6 space-y-4">
        <Field label="Email" name="email" type="email" autoComplete="email" required />
        <Field label="Password" name="password" type="password" autoComplete="current-password" required />
        <p className="-mt-2 text-right text-sm">
          <Link href="/forgot-password" className="text-brand-600 hover:underline">
            Forgot password?
          </Link>
        </p>
        <ErrorNote error={error} />
        <Button type="submit" busy={busy} className="w-full">
          Sign in
        </Button>
      </form>
      <p className="mt-4 text-sm text-muted">
        New here?{" "}
        <Link href="/register" className="font-medium text-brand-600 hover:underline">
          Create an account
        </Link>
      </p>
    </Card>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
