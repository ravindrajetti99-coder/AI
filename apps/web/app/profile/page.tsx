"use client";

import { type FormEvent, useState } from "react";

import { RequireAuth, useAuth } from "@/components/auth";
import { Badge, Button, Card, ErrorNote, Field, Notice, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import type { Me, TokenOut } from "@/lib/types";

function ProfileForm({ me }: { me: Me }) {
  const { reload } = useAuth();
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const examDate = String(f.get("exam_date") || "");
    setBusy(true);
    setSaved(false);
    setError(null);
    try {
      await api("/me", {
        method: "PATCH",
        body: {
          name: String(f.get("name")),
          preferred_locale: String(f.get("preferred_locale")),
          daily_minutes_goal: Number(f.get("daily_minutes_goal")),
          education_level: String(f.get("education_level")),
          career_goal: String(f.get("career_goal")),
          target_exams: String(f.get("target_exams"))
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          exam_date: examDate ? new Date(`${examDate}T00:00:00Z`).toISOString() : null,
        },
      });
      await reload();
      setSaved(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="max-w-2xl">
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" name="name" defaultValue={me.name} required maxLength={120} />
        <Select label="Lesson language" name="preferred_locale" defaultValue={me.preferred_locale}>
          <option value="en">English</option>
          <option value="te">తెలుగు (Telugu)</option>
        </Select>
        <Field label="Daily study goal (minutes)" name="daily_minutes_goal" type="number" min={10} max={720} defaultValue={me.profile.daily_minutes_goal} hint="Your daily plan fits inside this." />
        <Field label="Exam date" name="exam_date" type="date" defaultValue={me.profile.exam_date?.slice(0, 10) ?? ""} />
        <Field label="Education" name="education_level" defaultValue={me.profile.education_level} placeholder="e.g. B.Com final year" maxLength={60} />
        <Field label="Target exams" name="target_exams" defaultValue={me.profile.target_exams.join(", ")} placeholder="e.g. SSC CGL, CA Foundation" />
        <div className="sm:col-span-2">
          <Field label="Career goal" name="career_goal" defaultValue={me.profile.career_goal} maxLength={255} />
        </div>
        <div className="space-y-3 sm:col-span-2">
          <ErrorNote error={error} />
          {saved && <Notice tone="green">Saved. Your next daily plan uses these settings.</Notice>}
          <Button type="submit" busy={busy}>
            Save profile
          </Button>
        </div>
      </form>
    </Card>
  );
}

function EmailStatus({ me }: { me: Me }) {
  const [state, setState] = useState<{ busy: boolean; sent: boolean; error: unknown }>({ busy: false, sent: false, error: null });

  async function resend() {
    setState({ busy: true, sent: false, error: null });
    try {
      await api("/auth/email/resend", { method: "POST" });
      setState({ busy: false, sent: true, error: null });
    } catch (error) {
      setState({ busy: false, sent: false, error });
    }
  }

  return (
    <Card title="Email" className="max-w-2xl">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="font-medium">{me.email}</span>
        <Badge tone={me.email_verified ? "green" : "amber"}>{me.email_verified ? "verified" : "not verified"}</Badge>
        {!me.email_verified && (
          <Button size="sm" variant="secondary" busy={state.busy} onClick={() => void resend()}>
            Send the confirmation link again
          </Button>
        )}
      </div>
      <div className="mt-3 space-y-2">
        {state.sent && <Notice tone="green">Sent. Open the link in the email to confirm your address.</Notice>}
        <ErrorNote error={state.error} />
      </div>
    </Card>
  );
}

function ChangePassword() {
  const { adopt } = useAuth();
  const [state, setState] = useState<{ busy: boolean; saved: boolean; error: unknown }>({ busy: false, saved: false, error: null });

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formEl = e.currentTarget;
    const f = new FormData(formEl);
    if (f.get("new_password") !== f.get("confirm")) {
      setState({ busy: false, saved: false, error: new Error("The two new passwords do not match.") });
      return;
    }
    setState({ busy: true, saved: false, error: null });
    try {
      const out = await api<TokenOut>("/me/password", { body: { current_password: String(f.get("current_password")), new_password: String(f.get("new_password")) } });
      await adopt(out);
      formEl.reset();
      setState({ busy: false, saved: true, error: null });
    } catch (error) {
      setState({ busy: false, saved: false, error });
    }
  }

  return (
    <Card title="Password" className="max-w-2xl">
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-3">
        <Field label="Current password" name="current_password" type="password" autoComplete="current-password" required />
        <Field label="New password" name="new_password" type="password" autoComplete="new-password" required minLength={8} />
        <Field label="Repeat new password" name="confirm" type="password" autoComplete="new-password" required minLength={8} />
        <div className="space-y-3 sm:col-span-3">
          <ErrorNote error={state.error} />
          {state.saved && <Notice tone="green">Password changed. Other devices were signed out.</Notice>}
          <Button type="submit" busy={state.busy}>
            Change password
          </Button>
        </div>
      </form>
    </Card>
  );
}

function Profile() {
  const { me } = useAuth();
  if (!me) return null;
  return (
    <div className="space-y-6">
      <PageHeader title="Profile" subtitle={`${me.email} · ${me.role}`} />
      <ProfileForm me={me} />
      <EmailStatus me={me} />
      <ChangePassword />
    </div>
  );
}

export default function ProfilePage() {
  return (
    <RequireAuth>
      <Profile />
    </RequireAuth>
  );
}
