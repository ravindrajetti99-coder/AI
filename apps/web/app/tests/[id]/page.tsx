"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { RequireAuth } from "@/components/auth";
import { isAnswered, QuestionInput, type Response } from "@/components/question";
import { clock, ReportView } from "@/components/report";
import { Badge, Button, Card, cx, ErrorNote, Loading, Notice, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { TestReport, TestRun } from "@/lib/types";

function TestRunner() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<TestRun | null>(null);
  const [answers, setAnswers] = useState<Record<string, Response>>({});
  const [flagged, setFlagged] = useState<Set<string>>(new Set());
  const [current, setCurrent] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [report, setReport] = useState<TestReport | null>(null);
  const [saving, setSaving] = useState<"idle" | "saving" | "saved">("idle");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const pending = useRef<Record<string, Promise<unknown>>>({});
  const submittedRef = useRef(false);

  useEffect(() => {
    let live = true;
    api<TestRun>(`/tests/${id}/start`, { method: "POST" }).then(
      (r) => {
        if (!live) return;
        setRun(r);
        setAnswers(r.answers ?? {});
      },
      (e) => live && setError(e),
    );
    return () => {
      live = false;
    };
  }, [id]);

  const submit = useCallback(async () => {
    if (!run || submittedRef.current) return;
    submittedRef.current = true;
    setSubmitting(true);
    try {
      Object.values(timers.current).forEach(clearTimeout);
      await Promise.allSettled(Object.values(pending.current));
      setReport(await api<TestReport>(`/test-attempts/${run.test_attempt_id}/submit`, { method: "POST" }));
    } catch (e) {
      submittedRef.current = false;
      setError(e);
    } finally {
      setSubmitting(false);
    }
  }, [run]);

  const remaining = run ? new Date(run.ends_at).getTime() - now : 0;

  useEffect(() => {
    if (!run || report) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [run, report]);

  useEffect(() => {
    if (run && !report && remaining <= 0) {
      const t = setTimeout(() => void submit(), 0); // time is up: hand in what was saved
      return () => clearTimeout(t);
    }
  }, [run, report, remaining, submit]);

  function answer(questionId: string, response: Response) {
    setAnswers((a) => ({ ...a, [questionId]: response }));
    clearTimeout(timers.current[questionId]);
    setSaving("saving");
    timers.current[questionId] = setTimeout(() => {
      pending.current[questionId] = api(`/test-attempts/${run!.test_attempt_id}/answers`, { method: "PUT", body: { question_id: questionId, response } })
        .then(() => setSaving("saved"))
        .catch((e) => {
          if (e instanceof ApiError && e.status === 409) void submit();
          else setError(e);
        });
    }, 600);
  }

  if (error && !run) return <ErrorNote error={error} />;
  if (!run) return <Loading label="Preparing your test" />;
  if (report)
    return (
      <>
        <PageHeader title={report.title} subtitle="Your result" />
        <ReportView report={report} />
      </>
    );

  const item = run.items[current];
  const answeredCount = run.items.filter((it) => answers[it.question.id] && isAnswered(it.question, answers[it.question.id])).length;
  const lowTime = remaining < 60_000;

  return (
    <div className="space-y-4">
      <div className="sticky top-14 z-20 -mx-4 flex flex-wrap items-center gap-3 border-b border-line bg-canvas/95 px-4 py-3 backdrop-blur">
        <h1 className="font-semibold">{run.title}</h1>
        <span className={cx("rounded-md px-2 py-1 font-mono text-lg tabular-nums", lowTime ? "bg-rose-600 text-white" : "bg-surface-2")} aria-live="polite" aria-label="Time remaining">
          {clock(remaining)}
        </span>
        <span className="text-sm text-muted">
          {answeredCount}/{run.items.length} answered{saving === "saving" ? " · saving…" : saving === "saved" ? " · saved" : ""}
        </span>
        <Button
          className="ml-auto"
          variant="danger"
          busy={submitting}
          onClick={() => {
            const left = run.items.length - answeredCount;
            if (window.confirm(left ? `${left} question(s) unanswered. Submit anyway?` : "Submit the test?")) void submit();
          }}
        >
          Submit test
        </Button>
      </div>
      {run.instructions && <Notice>{run.instructions}</Notice>}
      <ErrorNote error={error} />
      <div className="grid gap-6 lg:grid-cols-4">
        <Card className="lg:col-span-3">
          <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
            <span className="font-semibold">
              Question {current + 1} of {run.items.length}
            </span>
            <Badge>{item.section}</Badge>
            <span className="text-muted">
              +{item.marks}
              {item.negative_marks ? ` / −${item.negative_marks}` : ""}
            </span>
            <label className="ml-auto flex items-center gap-2 text-muted">
              <input
                type="checkbox"
                className="accent-amber-500"
                checked={flagged.has(item.question.id)}
                onChange={() => {
                  const next = new Set(flagged);
                  if (next.has(item.question.id)) next.delete(item.question.id);
                  else next.add(item.question.id);
                  setFlagged(next);
                }}
              />
              Mark for review
            </label>
          </div>
          <QuestionInput key={item.question.id} question={item.question} value={answers[item.question.id] ?? {}} onChange={(r) => answer(item.question.id, r)} />
          <div className="mt-6 flex justify-between">
            <Button variant="secondary" disabled={current === 0} onClick={() => setCurrent(current - 1)}>
              ← Previous
            </Button>
            {answers[item.question.id] && (
              <Button variant="ghost" onClick={() => answer(item.question.id, {})}>
                Clear answer
              </Button>
            )}
            <Button variant="secondary" disabled={current === run.items.length - 1} onClick={() => setCurrent(current + 1)}>
              Next →
            </Button>
          </div>
        </Card>
        <Card title="Questions">
          <div className="grid grid-cols-5 gap-2">
            {run.items.map((it, i) => {
              const done = answers[it.question.id] && isAnswered(it.question, answers[it.question.id]);
              return (
                <button
                  key={it.question.id}
                  onClick={() => setCurrent(i)}
                  aria-label={`Question ${i + 1}${done ? ", answered" : ""}${flagged.has(it.question.id) ? ", marked for review" : ""}`}
                  className={cx(
                    "relative h-9 rounded-md text-sm font-medium tabular-nums",
                    i === current && "ring-2 ring-brand-500",
                    done ? "bg-emerald-500 text-white" : "bg-surface-2",
                  )}
                >
                  {i + 1}
                  {flagged.has(it.question.id) && <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-amber-500" />}
                </button>
              );
            })}
          </div>
          <p className="mt-3 text-xs text-muted">Green: answered · dot: marked for review. Unanswered questions score zero; wrong answers may lose marks.</p>
        </Card>
      </div>
    </div>
  );
}

export default function TestPage() {
  return (
    <RequireAuth>
      <TestRunner />
    </RequireAuth>
  );
}
