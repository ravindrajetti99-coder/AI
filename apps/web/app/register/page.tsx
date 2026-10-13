"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { useAuth } from "@/components/auth";
import { Button, Card, ErrorNote, Field, Select } from "@/components/ui";

export default function RegisterPage() {
  const { register } = useAuth();
  const router = useRouter();
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await register(String(form.get("name")), String(form.get("email")), String(form.get("password")), String(form.get("locale")));
      router.push("/courses");
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <Card className="mx-auto max-w-md">
      <h1 className="text-xl font-bold">Create your account</h1>
      <p className="mt-1 text-sm text-muted">Free. Pick a course next and we will build your daily plan.</p>
      <form onSubmit={submit} className="mt-6 space-y-4">
        <Field label="Name" name="name" autoComplete="name" required maxLength={120} />
        <Field label="Email" name="email" type="email" autoComplete="email" required />
        <Field label="Password" name="password" type="password" autoComplete="new-password" required minLength={8} hint="At least 8 characters." />
        <Select label="Preferred language for lessons" name="locale" defaultValue="en">
          <option value="en">English</option>
          <option value="te">తెలుగు (Telugu)</option>
        </Select>
        <ErrorNote error={error} />
        <Button type="submit" busy={busy} className="w-full">
          Create account
        </Button>
      </form>
      <p className="mt-4 text-sm text-muted">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-brand-600 hover:underline">
          Sign in
        </Link>
      </p>
    </Card>
  );
}
