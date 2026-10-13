"use client";

import { type FormEvent, useState } from "react";

import { RequireAuth, useAuth } from "@/components/auth";
import { Button, Card, ErrorNote, Field, Notice, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import type { Me } from "@/lib/types";

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

function Profile() {
  const { me } = useAuth();
  if (!me) return null;
  return (
    <>
      <PageHeader title="Profile" subtitle={`${me.email} · ${me.role}`} />
      <ProfileForm me={me} />
    </>
  );
}

export default function ProfilePage() {
  return (
    <RequireAuth>
      <Profile />
    </RequireAuth>
  );
}
