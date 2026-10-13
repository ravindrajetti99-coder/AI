"use client";

import { describeAnswer } from "@/components/question";
import { Badge, Card, pct, Stat } from "@/components/ui";
import type { TestReport } from "@/lib/types";

export function clock(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function ReportView({ report }: { report: TestReport }) {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Score" value={`${report.score} / ${report.max_score}`} hint={`${report.percent}%`} />
        <Stat label="Accuracy" value={pct(report.accuracy)} hint="of attempted questions" />
        <Stat label="Attempted" value={`${report.attempted} / ${report.questions}`} />
        <Stat label="Time" value={clock(report.time_taken_seconds * 1000)} hint="minutes" />
      </div>
      <Card title="Sections">
        <table className="w-full text-sm">
          <thead className="text-left text-muted">
            <tr>
              <th className="py-1">Section</th>
              <th className="text-right">Score</th>
              <th className="text-right">Correct</th>
              <th className="text-right">Wrong</th>
              <th className="text-right">Skipped</th>
            </tr>
          </thead>
          <tbody>
            {report.sections.map((s) => (
              <tr key={s.section} className="border-t border-line">
                <td className="py-2">{s.section}</td>
                <td className="text-right tabular-nums">
                  {s.score} / {s.max}
                </td>
                <td className="text-right text-emerald-600 tabular-nums">{s.correct}</td>
                <td className="text-right text-rose-600 tabular-nums">{s.wrong}</td>
                <td className="text-right tabular-nums text-muted">{s.unattempted}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {report.weak_concepts.length > 0 && <p className="mt-3 text-sm">Revise next: {report.weak_concepts.join(", ")}</p>}
      </Card>
      <Card title="Question-by-question review">
        <ol className="space-y-4">
          {report.review.map((r, i) => (
            <li key={r.question.id} className="rounded-lg border border-line p-4">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
                <span className="font-semibold">Q{i + 1}</span>
                <Badge tone={!r.answered ? "neutral" : r.is_correct ? "green" : "red"}>{!r.answered ? "skipped" : r.is_correct ? "correct" : "wrong"}</Badge>
                <span className="tabular-nums text-muted">
                  {r.marks > 0 ? "+" : ""}
                  {r.marks} / {r.max_marks}
                </span>
              </div>
              <p className="whitespace-pre-wrap">{r.question.stem}</p>
              {r.answered && !r.is_correct && (
                <p className="mt-2 text-sm text-rose-700 dark:text-rose-300">
                  Your answer: {describeAnswer(r.question, r.response.choice ?? r.response.choices ?? r.response.value)}
                </p>
              )}
              <p className="mt-1 text-sm text-emerald-700 dark:text-emerald-300">Correct: {describeAnswer(r.question, r.correct_answer)}</p>
              {r.explanation && <p className="mt-2 text-sm text-muted">{r.explanation}</p>}
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}
