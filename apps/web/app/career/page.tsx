"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { RequireAuth, useAuth } from "@/components/auth";
import { Button, Card, ErrorNote, PageHeader, TextArea } from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Course } from "@/lib/types";

type Guide = { summary: string; paths: { title: string; why: string; next_steps: string[]; course_slugs: string[] }[]; provider: string };

function Career() {
  const { me } = useAuth();
  const courses = useApi<Course[]>("/courses");
  const [goal, setGoal] = useState(me?.profile.career_goal ?? "");
  const [guide, setGuide] = useState<Guide | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const titles = Object.fromEntries((courses.data ?? []).map((c) => [c.slug, c.title]));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setGuide(await api<Guide>("/career/guide", { body: { goal } }));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Career guide" subtitle="Tell us where you want to be. We suggest realistic paths and the courses that get you there." />
      <Card>
        <form onSubmit={submit} className="space-y-3">
          <TextArea label="Your goal" rows={3} value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="e.g. I want a central government job through SSC CGL, or: I want my first job as a Python developer" maxLength={300} required />
          <ErrorNote error={error} />
          <Button type="submit" busy={busy}>
            Suggest paths
          </Button>
        </form>
      </Card>
      {guide && (
        <div className="space-y-4">
          <p className="text-muted">{guide.summary}</p>
          <div className="grid gap-4 md:grid-cols-2">
            {guide.paths.map((p) => (
              <Card key={p.title} title={p.title}>
                <p className="text-sm text-muted">{p.why}</p>
                <ol className="mt-3 ml-5 list-decimal space-y-1 text-sm">
                  {p.next_steps.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ol>
                {p.course_slugs.length > 0 && (
                  <div className="mt-4 space-y-1 text-sm">
                    <div className="font-medium">Courses</div>
                    {p.course_slugs.map((s) => (
                      <Link key={s} href={`/courses/${s}`} className="block text-brand-600 hover:underline">
                        {titles[s] ?? s}
                      </Link>
                    ))}
                  </div>
                )}
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function CareerPage() {
  return (
    <RequireAuth>
      <Career />
    </RequireAuth>
  );
}
