"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { useAuth } from "@/components/auth";
import { accent, Badge, Button, ButtonLink, Card, cx, ErrorNote, Loading, MasteryBadge, PageHeader, pct, ProgressBar } from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { CourseDetail, CourseProgress, TestSummary, TreeNode } from "@/lib/types";

function Tree({ nodes, progress, depth = 0 }: { nodes: TreeNode[]; progress?: Record<string, { mastery: number; label: string }>; depth?: number }) {
  return (
    <ul className={cx(depth > 0 && "ml-1 border-l border-line pl-3 sm:ml-4 sm:pl-4")}>
      {nodes.map((n) => (
        <li key={n.id} className="py-1.5">
          <div className={cx(depth === 0 ? "text-lg font-semibold" : depth === 1 ? "font-medium" : "text-sm text-muted")}>{n.title}</div>
          {n.concepts.length > 0 && (
            <ul className="mt-2 space-y-1.5">
              {n.concepts.map((c) => {
                const p = progress?.[c.id];
                return (
                  <li key={c.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2">
                    <Link href={`/learn/${c.slug}`} className="min-w-0 basis-full font-medium hover:text-brand-600 sm:basis-auto sm:flex-1">
                      {c.title}
                    </Link>
                    {c.weight >= 2 && <Badge tone="amber">high weightage</Badge>}
                    {p && (
                      <span className="flex w-full items-center gap-2 sm:w-40">
                        <ProgressBar value={p.mastery} label={`${c.title} mastery`} />
                        <span className="w-9 text-right text-xs tabular-nums">{pct(p.mastery)}</span>
                      </span>
                    )}
                    {p && <MasteryBadge label={p.label} />}
                    <Link href={`/practice?concept=${c.id}`} className="text-sm text-brand-600 hover:underline">
                      Practise
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
          {n.children.length > 0 && <Tree nodes={n.children} progress={progress} depth={depth + 1} />}
        </li>
      ))}
    </ul>
  );
}

export default function CoursePage() {
  const { slug } = useParams<{ slug: string }>();
  const { me } = useAuth();
  const course = useApi<CourseDetail>(`/courses/${slug}`);
  const enrollments = useApi<{ slug: string }[]>(me ? "/me/enrollments" : null);
  const enrolled = Boolean(enrollments.data?.some((e) => e.slug === slug));
  const progress = useApi<CourseProgress>(me && enrolled ? `/me/courses/${slug}/progress` : null);
  const tests = useApi<TestSummary[]>(me ? `/courses/${slug}/tests` : null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (course.loading) return <Loading />;
  if (course.error || !course.data) return <ErrorNote error={course.error} />;
  const c = course.data;
  const byConcept = Object.fromEntries((progress.data?.concepts ?? []).map((p) => [p.concept_id, p]));
  const pattern = c.exam_profile?.pattern as { marks_per_question?: number; negative_marks?: number } | undefined;

  async function enroll() {
    setBusy(true);
    setError(null);
    try {
      await api(`/courses/${slug}/enroll`, { method: "POST" });
      await enrollments.reload();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className={cx("h-1.5 w-24 rounded-full", accent(c.color))} />
      <PageHeader
        title={c.title}
        subtitle={c.description}
        action={
          me ? (
            enrolled ? (
              <ButtonLink href={`/practice?course=${c.slug}`}>Practise adaptively</ButtonLink>
            ) : (
              <Button onClick={enroll} busy={busy}>
                Enroll and build my plan
              </Button>
            )
          ) : (
            <ButtonLink href={`/register`}>Sign up to start</ButtonLink>
          )
        }
      />
      <ErrorNote error={error} />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card title="Syllabus">
            <Tree nodes={c.tree} progress={byConcept} />
          </Card>
        </div>
        <div className="space-y-6">
          {progress.data && (
            <Card title="Your progress">
              <div className="mb-1 flex justify-between text-sm">
                <span>Exam readiness</span>
                <strong>{pct(progress.data.readiness)}</strong>
              </div>
              <ProgressBar value={progress.data.readiness} label="Exam readiness" />
              <p className="mt-2 text-xs text-muted">Readiness weights each concept by its exam importance.</p>
            </Card>
          )}
          {c.exam_profile && (
            <Card title={c.exam_profile.name}>
              <p className="text-sm text-muted">{c.exam_profile.body}</p>
              {pattern?.marks_per_question !== undefined && (
                <p className="mt-2 text-sm">
                  Marking: +{pattern.marks_per_question} per correct answer
                  {pattern.negative_marks ? `, −${pattern.negative_marks} per wrong answer` : ", no negative marking"}.
                </p>
              )}
            </Card>
          )}
          <Card title="Mock tests">
            <div id="tests" />
            {!me ? (
              <p className="text-sm text-muted">Sign in to take timed mock tests.</p>
            ) : tests.data?.length ? (
              <ul className="space-y-3">
                {tests.data.map((t) => (
                  <li key={t.id} className="rounded-lg border border-line p-3">
                    <div className="font-medium">{t.title}</div>
                    <div className="mt-1 text-xs text-muted">
                      {t.questions} questions · {t.duration_minutes} min · {t.max_marks} marks
                      {t.last_score !== null && ` · last score ${t.last_score}`}
                    </div>
                    <ButtonLink href={`/tests/${t.id}`} variant="secondary" className="mt-2 !px-3 !py-1.5 text-sm">
                      {t.last_score !== null ? "Retake" : "Start"}
                    </ButtonLink>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted">No mock tests yet.</p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
