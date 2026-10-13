"use client";

import Link from "next/link";
import { useState } from "react";

import { RequireAuth } from "@/components/auth";
import { Badge, Button, ButtonLink, Card, Empty, ErrorNote, Loading, MasteryBadge, Notice, PageHeader, pct, ProgressBar, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Dashboard, PlanItem } from "@/lib/types";

const KIND_TONE = { review: "brand", learn: "green", practice: "neutral", weak: "red", test: "amber" } as const;
const KIND_LABEL = { review: "Revise", learn: "Learn", practice: "Practise", weak: "Fix", test: "Test" } as const;

function planHref(item: PlanItem, courseSlug: string | undefined) {
  if (item.kind === "learn" && item.concept_id) return `/learn/${item.concept_id}`;
  if (item.kind === "review") return "/reviews";
  if (item.kind === "test") return courseSlug ? `/courses/${courseSlug}#tests` : "/courses";
  return item.concept_id ? `/practice?concept=${item.concept_id}` : `/practice?course=${courseSlug}`;
}

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

function DashboardView() {
  const { data, error, loading, reload } = useApi<Dashboard>("/me/dashboard");
  const [mentor, setMentor] = useState<{ message: string; focus: string[]; provider: string } | null>(null);
  const [mentorBusy, setMentorBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);

  if (loading) return <Loading label="Building today's plan" />;
  if (error || !data) return <ErrorNote error={error} />;
  const slugById = Object.fromEntries(data.courses.map((c) => [c.course_id, c.slug]));
  const firstCourse = data.courses[0];

  async function setStatus(item: PlanItem, status: PlanItem["status"]) {
    try {
      await api(`/me/plan/${item.id}`, { method: "PATCH", body: { status } });
      await reload();
    } catch (e) {
      setActionError(e);
    }
  }

  async function askMentor() {
    if (!firstCourse) return;
    setMentorBusy(true);
    try {
      setMentor(await api("/me/mentor", { query: { course: firstCourse.slug } }));
    } catch (e) {
      setActionError(e);
    } finally {
      setMentorBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={`${greeting()}, ${data.user.name.split(" ")[0]}`}
        subtitle="Here is what will move your readiness most today."
        action={data.ai.mode === "offline" ? <Badge>Built-in engines (no AI provider connected)</Badge> : <Badge tone="green">AI live</Badge>}
      />
      <ErrorNote error={actionError} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Streak" value={`${data.stats.streak_days} day${data.stats.streak_days === 1 ? "" : "s"}`} />
        <Stat label="Questions (7 days)" value={data.stats.attempts} />
        <Stat label="Accuracy" value={pct(data.stats.accuracy)} />
        <Stat label="Study time (7 days)" value={`${data.stats.practice_minutes + data.stats.lesson_minutes} min`} />
      </div>

      {data.courses.length === 0 ? (
        <Empty title="You have not enrolled in a course yet">
          <ButtonLink href="/courses" className="mt-3">
            Choose a course
          </ButtonLink>
        </Empty>
      ) : (
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="space-y-6 lg:col-span-2">
            <Card title="Today's plan" action={<span className="text-sm text-muted">{data.plan.filter((p) => p.status === "todo").reduce((s, p) => s + p.minutes, 0)} min left</span>}>
              {data.plan.length === 0 ? (
                <p className="text-sm text-muted">Nothing scheduled. Pick any concept to practise, or take a mock test.</p>
              ) : (
                <ul className="divide-y divide-line">
                  {data.plan.map((item) => (
                    <li key={item.id} className="flex items-center gap-3 py-3">
                      <input
                        type="checkbox"
                        aria-label={`Mark "${item.title}" done`}
                        checked={item.status === "done"}
                        onChange={() => setStatus(item, item.status === "done" ? "todo" : "done")}
                        className="h-4 w-4 accent-brand-600"
                      />
                      <Badge tone={KIND_TONE[item.kind]}>{KIND_LABEL[item.kind]}</Badge>
                      <div className="min-w-0 flex-1">
                        <Link href={planHref(item, slugById[item.course_id])} className={item.status === "done" ? "text-muted line-through" : "font-medium hover:text-brand-600"}>
                          {item.title}
                        </Link>
                        <div className="truncate text-xs text-muted">{item.reason}</div>
                      </div>
                      <span className="text-sm tabular-nums text-muted">{item.minutes}m</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            {data.courses.map((c) => (
              <Card
                key={c.course_id}
                title={
                  <Link href={`/courses/${c.slug}`} className="hover:text-brand-600">
                    {c.title}
                  </Link>
                }
                action={<ButtonLink href={`/practice?course=${c.slug}`}>Practise</ButtonLink>}
              >
                <div className="mb-1 flex justify-between text-sm">
                  <span>Exam readiness</span>
                  <span className="font-semibold">{pct(c.readiness)}</span>
                </div>
                <ProgressBar value={c.readiness} label="Exam readiness" />
                <p className="mt-2 text-xs text-muted">{pct(c.coverage)} of concepts attempted</p>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  {c.modules.map((m) => (
                    <div key={m.node_id}>
                      <div className="mb-1 flex justify-between text-xs">
                        <span>{m.title}</span>
                        <span>{pct(m.mastery)}</span>
                      </div>
                      <ProgressBar value={m.mastery} label={m.title} />
                    </div>
                  ))}
                </div>
                {c.weak.length > 0 && (
                  <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
                    <span className="text-muted">Weak areas:</span>
                    {c.weak.map((w) => (
                      <Link key={w.concept_id} href={`/practice?concept=${w.concept_id}`} className="hover:underline">
                        <MasteryBadge label="weak" /> {w.title}
                      </Link>
                    ))}
                  </div>
                )}
              </Card>
            ))}
          </div>

          <div className="space-y-6">
            <Card title="Your mentor">
              {mentor ? (
                <div className="space-y-2 text-sm">
                  <p className="leading-relaxed">{mentor.message}</p>
                  {mentor.focus.length > 0 && <p className="text-muted">Focus: {mentor.focus.join(", ")}</p>}
                </div>
              ) : (
                <p className="text-sm text-muted">Get a short, honest note on what to prioritise today and why.</p>
              )}
              <Button variant="secondary" size="sm" className="mt-3" onClick={askMentor} busy={mentorBusy}>
                {mentor ? "Ask again" : "Get today's advice"}
              </Button>
            </Card>
            <Card title="Revision" action={<Link href="/reviews" className="text-sm text-brand-600 hover:underline">Open</Link>}>
              {data.due_reviews.length > 0 ? (
                <Notice tone="amber">
                  {data.due_reviews.length} concept{data.due_reviews.length === 1 ? "" : "s"} due for revision now.
                </Notice>
              ) : (
                <p className="text-sm text-muted">No revision due right now.</p>
              )}
              {data.upcoming_reviews.length > 0 && (
                <ul className="mt-3 space-y-1 text-sm">
                  {data.upcoming_reviews.slice(0, 5).map((r) => (
                    <li key={r.id} className="flex justify-between gap-2">
                      <span className="truncate">{r.concept.title}</span>
                      <span className="shrink-0 text-muted">{new Date(r.due_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

export default function DashboardPage() {
  return (
    <RequireAuth>
      <DashboardView />
    </RequireAuth>
  );
}
