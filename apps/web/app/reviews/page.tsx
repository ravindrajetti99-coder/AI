"use client";

import Link from "next/link";
import { useState } from "react";

import { RequireAuth } from "@/components/auth";
import { emptyResponse, FeedbackView, isAnswered, QuestionInput, type Response } from "@/components/question";
import { Badge, Button, Card, Empty, ErrorNote, Loading, Notice, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { AttemptResult, Question, ReviewRow } from "@/lib/types";

type Reviews = { due: ReviewRow[]; upcoming: ReviewRow[]; ladder: { stage: number; name: string; day: number }[] };
type Pack = { review_id: string; started_at: string; questions: Question[] };
type Done = { success: boolean; correct: number | null; total: number | null; completed: boolean; next_due: string; stage: number };

function ReviewSession({ review, onDone }: { review: ReviewRow; onDone: () => void }) {
  const pack = useApi<Pack>(`/me/reviews/${review.id}/questions`);
  const [index, setIndex] = useState(0);
  const [response, setResponse] = useState<Response>({});
  const [result, setResult] = useState<AttemptResult | null>(null);
  const [done, setDone] = useState<Done | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function finish(selfRating?: "remembered" | "forgot") {
    setBusy(true);
    try {
      setDone(await api<Done>(`/me/reviews/${review.id}/complete`, { body: selfRating ? { self_rating: selfRating } : { started_at: pack.data?.started_at } }));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  if (pack.loading) return <Loading />;
  if (pack.error || !pack.data) return <ErrorNote error={pack.error} />;
  if (done)
    return (
      <Card title={review.concept.title}>
        <Notice tone={done.success ? "green" : "amber"}>
          {done.completed
            ? "Ladder complete: this concept is in long-term memory."
            : done.success
              ? `Well remembered${done.total ? ` (${done.correct}/${done.total})` : ""}. Next revision: ${new Date(done.next_due).toLocaleDateString()}.`
              : `This needs another pass${done.total ? ` (${done.correct}/${done.total})` : ""}. The ladder restarts; next revision ${new Date(done.next_due).toLocaleDateString()}.`}
        </Notice>
        <div className="mt-4 flex gap-3">
          {!done.success && (
            <Link href={`/learn/${review.concept.slug}`} className="text-brand-600 hover:underline">
              Re-read the lesson
            </Link>
          )}
          <Button variant="secondary" onClick={onDone}>
            Back to revision list
          </Button>
        </div>
      </Card>
    );

  const questions = pack.data.questions;
  if (questions.length === 0)
    return (
      <Card title={review.concept.title}>
        <p className="text-sm text-muted">No quick-check questions for this concept. Recall it from memory, then rate yourself honestly.</p>
        <div className="mt-4 flex gap-3">
          <Button onClick={() => finish("remembered")} busy={busy}>
            I remembered it
          </Button>
          <Button variant="secondary" onClick={() => finish("forgot")} busy={busy}>
            I forgot
          </Button>
        </div>
      </Card>
    );

  const q = questions[index];
  const last = index === questions.length - 1;
  return (
    <Card title={`${review.concept.title}: quick check ${index + 1} of ${questions.length}`}>
      <QuestionInput key={q.id} question={q} value={Object.keys(response).length ? response : emptyResponse(q)} onChange={setResponse} disabled={Boolean(result)} />
      <ErrorNote error={error} className="mt-3" />
      <div className="mt-6">
        {!result ? (
          <Button
            busy={busy}
            disabled={!isAnswered(q, response)}
            onClick={async () => {
              setBusy(true);
              try {
                setResult(await api<AttemptResult>("/attempts", { body: { question_id: q.id, response } }));
              } catch (e) {
                setError(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            Check
          </Button>
        ) : (
          <div className="space-y-4">
            <FeedbackView question={q} result={result} />
            {last ? (
              <Button onClick={() => finish()} busy={busy}>
                Finish revision
              </Button>
            ) : (
              <Button
                onClick={() => {
                  setIndex(index + 1);
                  setResponse({});
                  setResult(null);
                }}
              >
                Next question →
              </Button>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

function ReviewsView() {
  const { data, error, loading, reload } = useApi<Reviews>("/me/reviews");
  const [active, setActive] = useState<ReviewRow | null>(null);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorNote error={error} />;
  if (active)
    return (
      <ReviewSession
        review={active}
        onDone={() => {
          setActive(null);
          void reload();
        }}
      />
    );

  return (
    <div className="space-y-6">
      <PageHeader title="Revision" subtitle={`Spaced revision on day ${data.ladder.map((l) => l.day).join(", ")} after you learn a concept: the forgetting curve, beaten on schedule.`} />
      <Card title={`Due now (${data.due.length})`}>
        {data.due.length === 0 ? (
          <Empty title="Nothing due. Nice work.">Revisions appear here as concepts reach their next day on the ladder.</Empty>
        ) : (
          <ul className="divide-y divide-line">
            {data.due.map((r) => (
              <li key={r.id} className="flex items-center gap-3 py-3">
                <div className="flex-1">
                  <div className="font-medium">{r.concept.title}</div>
                  <div className="text-xs text-muted">
                    Stage: {r.stage_name.replace("_", " ")} (day {r.stage_day}){r.last_result && ` · last time: ${r.last_result}`}
                  </div>
                </div>
                <Button size="sm" onClick={() => setActive(r)}>
                  Revise now
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title="Coming up (30 days)">
        {data.upcoming.length === 0 ? (
          <p className="text-sm text-muted">Learn or practise a concept to start its revision ladder.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {data.upcoming.map((r) => (
              <li key={r.id} className="flex items-center justify-between gap-3">
                <span>{r.concept.title}</span>
                <span className="flex items-center gap-2 text-muted">
                  <Badge>{r.stage_name.replace("_", " ")}</Badge>
                  {new Date(r.due_at).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

export default function ReviewsPage() {
  return (
    <RequireAuth>
      <ReviewsView />
    </RequireAuth>
  );
}
