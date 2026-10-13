"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { useAuth } from "@/components/auth";
import { accent, Badge, Button, ButtonLink, Card, cx, ErrorNote, Loading, MasteryBadge, Notice, PageHeader, pct, ProgressBar } from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { StrategyCard, tierText } from "@/components/study-pack";
import type { CourseDetail, CourseProgress, ExamProfile, TestSummary, TreeNode } from "@/lib/types";

type Progress = Record<string, { mastery: number; label: string }>;

function countConcepts(nodes: TreeNode[]): number {
  return nodes.reduce((n, node) => n + node.concepts.length + countConcepts(node.children), 0);
}

/** A tier badge only where a part of the syllabus belongs to fewer exam stages than its parent. */
function TierBadge({ tiers, parent }: { tiers: string[]; parent: string[] }) {
  if (!tiers.length || tiers.length >= parent.length) return null;
  return <Badge tone="brand">{tierText(tiers)} only</Badge>;
}

function Tree({ nodes, progress, depth = 0, parentTiers, collapse }: { nodes: TreeNode[]; progress?: Progress; depth?: number; parentTiers: string[]; collapse: boolean }) {
  return (
    <ul className={cx(depth > 0 && "ml-1 border-l border-line pl-3 sm:ml-4 sm:pl-4")}>
      {nodes.map((n) => {
        const title = (
          <span className={cx("inline-flex flex-wrap items-center gap-2", depth === 0 ? "text-lg font-semibold" : depth === 1 ? "font-medium" : "text-sm text-muted")}>
            {n.title}
            <TierBadge tiers={n.tiers} parent={parentTiers} />
            {collapse && depth === 1 && <span className="text-xs font-normal text-muted">{countConcepts([n])} concepts</span>}
          </span>
        );
        const body = <NodeBody n={n} progress={progress} depth={depth} parentTiers={n.tiers.length ? n.tiers : parentTiers} collapse={collapse} />;
        return (
          <li key={n.id} className="py-1.5">
            {collapse && depth === 1 ? (
              <details>
                <summary className="cursor-pointer">{title}</summary>
                {body}
              </details>
            ) : (
              <>
                <div>{title}</div>
                {body}
              </>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function NodeBody({ n, progress, depth, parentTiers, collapse }: { n: TreeNode; progress?: Progress; depth: number; parentTiers: string[]; collapse: boolean }) {
  return (
    <>
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
                <TierBadge tiers={c.tiers} parent={parentTiers} />
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
      {n.children.length > 0 && <Tree nodes={n.children} progress={progress} depth={depth + 1} parentTiers={parentTiers} collapse={collapse} />}
    </>
  );
}

function ExamCard({ exam }: { exam: ExamProfile }) {
  const p = exam.pattern;
  const sections = p.sections ?? [];
  const totalQ = sections.reduce((n, s) => n + s.questions, 0);
  const totalMarks = sections.filter((s) => !s.qualifying).reduce((n, s) => n + s.marks, 0);
  return (
    <Card title={exam.name}>
      <p className="text-sm text-muted">
        {[exam.body, p.mode, p.duration_minutes && `${p.duration_minutes} min`, totalQ && `${totalQ} questions`].filter(Boolean).join(" · ")}
        {p.qualifying && " · qualifying stage"}
      </p>
      {p.marks_per_question !== undefined && (
        <p className="mt-2 text-sm">
          Marking: +{p.marks_per_question} per correct answer
          {p.negative_marks ? `, −${p.negative_marks} per wrong answer` : ", no negative marking"}.
        </p>
      )}
      {sections.length > 0 && (
        <table className="mt-3 w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th className="py-1 font-normal">Section</th>
              <th className="py-1 text-right font-normal">Qs</th>
              <th className="py-1 text-right font-normal">Marks</th>
            </tr>
          </thead>
          <tbody>
            {sections.map((s) => (
              <tr key={s.name} className="border-t border-line">
                <td className="py-1.5">
                  {s.name}
                  {s.qualifying && <span className="ml-1 text-xs text-muted">(qualifying)</span>}
                  {s.group && <div className="text-xs text-muted">{[s.session, s.group, s.module].filter(Boolean).join(" · ")}</div>}
                </td>
                <td className="py-1.5 text-right tabular-nums">{s.questions}</td>
                <td className="py-1.5 text-right tabular-nums">{s.marks}</td>
              </tr>
            ))}
            <tr className="border-t border-line font-medium">
              <td className="py-1.5">Counted towards the score</td>
              <td />
              <td className="py-1.5 text-right tabular-nums">{totalMarks}</td>
            </tr>
          </tbody>
        </table>
      )}
      {(p.components ?? []).map((c) => (
        <p key={c.name} className="mt-2 text-xs text-muted">
          + {c.name} ({c.duration_minutes} min{c.qualifying ? ", qualifying" : ""}){c.description ? `: ${c.description}` : ""}
        </p>
      ))}
      {(p.notes ?? []).length > 0 && (
        <ul className="mt-3 ml-4 list-disc space-y-1 text-xs text-muted">
          {p.notes?.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      )}
    </Card>
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
  const exams = c.exams?.length ? c.exams : c.exam_profile ? [c.exam_profile] : [];
  const stages = exams.map((e) => e.pattern.stage).filter((s): s is string => Boolean(s));
  const collapse = countConcepts(c.tree) > 60;

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
      {c.status !== "published" && <Notice tone="amber">Draft course: visible to staff only until its content is complete and reviewed.</Notice>}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card title="Syllabus" action={collapse ? <span className="text-xs text-muted">{countConcepts(c.tree)} concepts</span> : undefined}>
            <Tree nodes={c.tree} progress={byConcept} parentTiers={stages} collapse={collapse} />
          </Card>
          {c.strategies?.length > 0 && (
            <Card title="Exam strategy">
              <div className="space-y-3">
                {c.strategies.map((s) => (
                  <StrategyCard key={s.id} s={s} />
                ))}
              </div>
            </Card>
          )}
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
          {exams.map((e) => (
            <ExamCard key={e.id} exam={e} />
          ))}
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
