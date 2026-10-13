"use client";

import { type ReactNode, useState } from "react";

import { Mermaid } from "@/components/mermaid";
import { cx, Notice } from "@/components/ui";
import type { LessonBody } from "@/lib/types";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted">{title}</h3>
      {children}
    </section>
  );
}

export function LessonView({ body, locale }: { body: LessonBody; locale: string }) {
  const [revealed, setRevealed] = useState<Set<number>>(new Set());
  return (
    <div lang={locale} className="space-y-6">
      <p className="rounded-xl bg-brand-50 p-4 text-lg font-medium leading-relaxed text-brand-900 dark:bg-brand-900/30 dark:text-brand-100">{body.definition}</p>
      <div className="prose-lesson leading-relaxed">
        {body.explanation.split(/\n\s*\n/).map((p, i) => (
          <p key={i}>{p}</p>
        ))}
      </div>
      {body.diagram && (
        <Section title="Diagram">
          <Mermaid code={body.diagram} />
        </Section>
      )}
      {body.examples.length > 0 && (
        <Section title="Examples">
          <div className="grid gap-3 sm:grid-cols-2">
            {body.examples.map((ex, i) => (
              <div key={i} className="rounded-lg border border-line p-3">
                <div className="font-medium">{ex.title}</div>
                <p className={cx("mt-1 whitespace-pre-wrap text-sm text-muted", /\n {2,}|=|\(/.test(ex.body) && ex.body.includes("\n") && "font-mono text-xs")}>{ex.body}</p>
              </div>
            ))}
          </div>
        </Section>
      )}
      {body.key_points.length > 0 && (
        <Section title="Key points">
          <ul className="ml-5 list-disc space-y-1">
            {body.key_points.map((k, i) => (
              <li key={i}>{k}</li>
            ))}
          </ul>
        </Section>
      )}
      {(body.solving_method?.length ?? 0) > 0 && (
        <Section title="Solving method">
          <ol className="ml-5 list-decimal space-y-1">
            {body.solving_method?.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </Section>
      )}
      {body.common_mistakes.length > 0 && (
        <Section title="Common mistakes">
          <ul className="space-y-1">
            {body.common_mistakes.map((m, i) => (
              <li key={i} className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-900 dark:bg-rose-950/40 dark:text-rose-100">
                ✗ {m}
              </li>
            ))}
          </ul>
        </Section>
      )}
      {body.memory_technique && (
        <Section title="Remember it">
          <Notice tone="green">{body.memory_technique}</Notice>
        </Section>
      )}
      {body.exam_relevance && (
        <Section title="In the exam">
          <p className="text-sm">{body.exam_relevance}</p>
        </Section>
      )}
      {body.check_questions.length > 0 && (
        <Section title="Check yourself">
          <ul className="space-y-2">
            {body.check_questions.map((c, i) => (
              <li key={i} className="rounded-lg border border-line p-3">
                <p>{c.question}</p>
                {revealed.has(i) ? (
                  <p className="mt-1 font-medium text-emerald-700 dark:text-emerald-300">{c.answer}</p>
                ) : (
                  <button className="mt-1 text-sm text-brand-600 hover:underline" onClick={() => setRevealed(new Set(revealed).add(i))}>
                    Show answer
                  </button>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
