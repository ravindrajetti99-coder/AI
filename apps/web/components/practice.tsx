"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { emptyResponse, FeedbackView, HintPanel, isAnswered, QuestionInput, type Response } from "@/components/question";
import { Badge, Button, Card, Empty, ErrorNote, Loading, MasteryBadge, pct } from "@/components/ui";
import { api } from "@/lib/api";
import type { AttemptResult, NextQuestion } from "@/lib/types";

const REASONS: Record<string, string> = {
  "revision due": "Revision is due for this concept",
  "next in syllabus": "Next concept in your syllabus",
  "keep building": "Keep building this concept",
  "weak area": "This is one of your weak areas",
  "maintenance practice": "Keeping a strong concept fresh",
  "chosen concept": "The concept you picked",
};

/** One question at a time, chosen adaptively by the API (about 70% expected success). */
export function PracticeSession({ course, concept, types }: { course?: string; concept?: string; types?: string }) {
  const [next, setNext] = useState<NextQuestion | null>(null);
  const [response, setResponse] = useState<Response>({});
  const [result, setResult] = useState<AttemptResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [count, setCount] = useState({ answered: 0, correct: 0 });
  const seen = useRef<string[]>([]);
  const shownAt = useRef(0);

  const fetchNext = useCallback(
    () => api<NextQuestion>("/practice/next", { query: { course, concept, types, exclude: seen.current.slice(-20).join(",") } }),
    [course, concept, types],
  );

  const show = useCallback((n: NextQuestion) => {
    setNext(n);
    setResponse(n.question ? emptyResponse(n.question) : {});
    setResult(null);
    setError(null);
    setLoading(false);
    shownAt.current = Date.now();
  }, []);

  const fail = useCallback((e: unknown) => {
    setError(e);
    setLoading(false);
  }, []);

  useEffect(() => {
    let live = true;
    fetchNext().then(
      (n) => live && show(n),
      (e) => live && fail(e),
    );
    return () => {
      live = false;
    };
  }, [fetchNext, show, fail]);

  function advance() {
    setLoading(true);
    fetchNext().then(show, fail);
  }

  async function submit() {
    if (!next?.question) return;
    setSubmitting(true);
    setError(null);
    try {
      const seconds = Math.min(36000, Math.round((Date.now() - shownAt.current) / 1000));
      const r = await api<AttemptResult>("/attempts", { body: { question_id: next.question.id, response, seconds } });
      setResult(r);
      seen.current.push(next.question.id);
      setCount((c) => ({ answered: c.answered + 1, correct: c.correct + (r.is_correct ? 1 : 0) }));
    } catch (e) {
      setError(e);
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <Loading label="Choosing your next question" />;
  if (!next) return <ErrorNote error={error} />;
  const q = next.question;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <Link href={`/learn/${next.concept.slug ?? next.concept.id}`} className="font-semibold hover:text-brand-600">
          {next.concept.title}
        </Link>
        {next.concept.label && <MasteryBadge label={next.concept.label} />}
        {next.concept.mastery !== undefined && <span className="text-muted">mastery {pct(next.concept.mastery)}</span>}
        <span className="text-muted">· {REASONS[next.reason] ?? next.reason.replace(/^prerequisite gap behind/, "Fixing the base behind")}</span>
        {count.answered > 0 && (
          <span className="ml-auto text-muted">
            This session: {count.correct}/{count.answered}
          </span>
        )}
      </div>
      {!q ? (
        <Empty title="No questions for this concept yet">
          <Link href={`/learn/${next.concept.slug ?? next.concept.id}`} className="text-brand-600 hover:underline">
            Read the lesson instead
          </Link>
        </Empty>
      ) : (
        <Card>
          <div className="mb-4 flex flex-wrap gap-2">
            <Badge>{q.qtype.replace("_", " ")}</Badge>
            <Badge>{q.difficulty}</Badge>
            {q.pyq_year && <Badge tone="amber">Previous year {q.pyq_year}</Badge>}
          </div>
          <QuestionInput question={q} value={response} onChange={setResponse} disabled={Boolean(result) || submitting} />
          <ErrorNote error={error} className="mt-4" />
          {!result ? (
            <div className="mt-6 space-y-4">
              <div className="flex flex-wrap gap-3">
                <Button onClick={submit} busy={submitting} disabled={!isAnswered(q, response)}>
                  {q.qtype === "coding" ? "Submit (runs hidden tests)" : "Check answer"}
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => {
                    seen.current.push(q.id);
                    advance();
                  }}
                >
                  Skip
                </Button>
              </div>
              {q.qtype !== "speaking" && <HintPanel key={q.id} questionId={q.id} />}
            </div>
          ) : (
            <div className="mt-6 space-y-6 border-t border-line pt-6">
              <FeedbackView question={q} result={result} />
              <Button onClick={advance}>Next question →</Button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
