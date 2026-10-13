"use client";

import { type KeyboardEvent, useState } from "react";

import { Badge, Button, cx, ErrorNote, Notice, pct, TextArea } from "@/components/ui";
import { api } from "@/lib/api";
import { speak, useSpeechRecognition } from "@/lib/speech";
import type { AttemptResult, CodeRun, Feedback, Question, Step } from "@/lib/types";

export type Response = Record<string, unknown>;

const CODE_HINT = /^( {2,}|\t)|\b(def |print\(|return |import |for .+ in |while |if .+:$)| = /m;

/** Question text: prose paragraphs, with code-looking paragraphs shown as code. */
export function Stem({ text }: { text: string }) {
  return (
    <div className="space-y-3">
      {text.split(/\n\s*\n/).map((para, i) =>
        CODE_HINT.test(para) && para.includes("\n") ? (
          <pre key={i} className="overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-sm">
            {para}
          </pre>
        ) : (
          <p key={i} className="whitespace-pre-wrap text-lg leading-relaxed">
            {para}
          </p>
        ),
      )}
    </div>
  );
}

export function isAnswered(q: Question, r: Response): boolean {
  switch (q.qtype) {
    case "multi":
      return Array.isArray(r.choices) && r.choices.length > 0;
    case "numerical":
      return String(r.value ?? "").trim() !== "";
    case "descriptive":
    case "interview":
      return String(r.text ?? "").trim() !== "";
    case "coding":
      return String(r.code ?? "").trim() !== "";
    case "speaking":
      return String(r.transcript ?? "").trim() !== "";
    default:
      return r.choice !== undefined && r.choice !== null;
  }
}

export function emptyResponse(q: Question): Response {
  if (q.qtype === "coding") return { code: q.payload.starter_code ?? "" };
  return {};
}

export function QuestionInput({ question: q, value, onChange, disabled }: { question: Question; value: Response; onChange: (r: Response) => void; disabled?: boolean }) {
  const p = q.payload;
  return (
    <div className="space-y-4">
      {p.passage && (
        <blockquote className="rounded-lg border-l-4 border-brand-500 bg-surface-2 p-4 text-sm leading-relaxed">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Read the case</div>
          {p.passage}
        </blockquote>
      )}
      <Stem text={q.stem.replace(/^Case study\.\s*/, "")} />
      {(q.qtype === "mcq" || q.qtype === "assertion_reason" || q.qtype === "case_study") && (
        <fieldset className="space-y-2" disabled={disabled}>
          <legend className="sr-only">Choose one answer</legend>
          {p.options?.map((o) => (
            <OptionRow key={o.id} id={o.id} text={o.text} type="radio" name={q.id} checked={value.choice === o.id} onChange={() => onChange({ choice: o.id })} />
          ))}
        </fieldset>
      )}
      {q.qtype === "multi" && (
        <fieldset className="space-y-2" disabled={disabled}>
          <legend className="text-sm text-muted">{p.select_count_hint ?? "Select all that apply"}</legend>
          {p.options?.map((o) => {
            const chosen = (value.choices as string[] | undefined) ?? [];
            return (
              <OptionRow
                key={o.id}
                id={o.id}
                text={o.text}
                type="checkbox"
                name={q.id}
                checked={chosen.includes(o.id)}
                onChange={() => onChange({ choices: chosen.includes(o.id) ? chosen.filter((c) => c !== o.id) : [...chosen, o.id].sort() })}
              />
            );
          })}
        </fieldset>
      )}
      {q.qtype === "numerical" && (
        <label className="flex max-w-xs items-center gap-2">
          <span className="sr-only">Your answer</span>
          <input
            inputMode="decimal"
            disabled={disabled}
            value={String(value.value ?? "")}
            onChange={(e) => onChange({ value: e.target.value })}
            placeholder="Your answer"
            className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-lg tabular-nums focus:border-brand-500 focus:outline-none"
          />
          {p.unit && <span className="text-muted">{p.unit}</span>}
        </label>
      )}
      {(q.qtype === "descriptive" || q.qtype === "interview") && <WrittenAnswer value={String(value.text ?? "")} onChange={(text) => onChange({ text })} wordLimit={p.word_limit} disabled={disabled} />}
      {q.qtype === "coding" && <CodeAnswer question={q} code={String(value.code ?? "")} onChange={(code) => onChange({ code })} disabled={disabled} />}
      {q.qtype === "speaking" && <SpeakingAnswer question={q} transcript={String(value.transcript ?? "")} onChange={(transcript) => onChange({ transcript })} disabled={disabled} />}
    </div>
  );
}

function OptionRow({ id, text, type, name, checked, onChange }: { id: string; text: string; type: "radio" | "checkbox"; name: string; checked: boolean; onChange: () => void }) {
  return (
    <label className={cx("flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors", checked ? "border-brand-500 bg-brand-50 dark:bg-brand-900/30" : "border-line hover:bg-surface-2")}>
      <input type={type} name={name} checked={checked} onChange={onChange} className="mt-1 accent-brand-600" />
      <span className="font-semibold uppercase text-muted">{id}</span>
      <span>{text}</span>
    </label>
  );
}

function WrittenAnswer({ value, onChange, wordLimit, disabled }: { value: string; onChange: (v: string) => void; wordLimit?: number; disabled?: boolean }) {
  const words = value.trim() ? value.trim().split(/\s+/).length : 0;
  return (
    <div>
      <TextArea rows={9} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)} placeholder="Write your answer. Use short paragraphs: introduction, points, conclusion." />
      <div className={cx("mt-1 text-right text-xs", wordLimit && words > wordLimit ? "text-rose-600" : "text-muted")}>
        {words} words{wordLimit ? ` / ${wordLimit} limit` : ""}
      </div>
    </div>
  );
}

function CodeAnswer({ question: q, code, onChange, disabled }: { question: Question; code: string; onChange: (v: string) => void; disabled?: boolean }) {
  const [run, setRun] = useState<CodeRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Tab") return;
    e.preventDefault(); // indent instead of leaving the editor
    const el = e.currentTarget;
    const { selectionStart: s, selectionEnd: end } = el;
    const next = code.slice(0, s) + "    " + code.slice(end);
    onChange(next);
    requestAnimationFrame(() => el.setSelectionRange(s + 4, s + 4));
  }

  async function runExamples() {
    setBusy(true);
    setError(null);
    try {
      setRun(await api<CodeRun>("/code/run", { body: { question_id: q.id, code } }));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      {q.payload.examples && q.payload.examples.length > 0 && (
        <div className="rounded-lg bg-surface-2 p-3 text-sm">
          <div className="mb-1 font-medium">Examples</div>
          <ul className="space-y-1 font-mono text-xs">
            {q.payload.examples.map((t, i) => (
              <li key={i}>
                {q.payload.function_name}({t.args.map((a) => JSON.stringify(a)).join(", ")}) → {JSON.stringify(t.expected)}
              </li>
            ))}
          </ul>
        </div>
      )}
      <textarea
        aria-label="Code editor"
        spellCheck={false}
        value={code}
        disabled={disabled}
        onKeyDown={onKeyDown}
        onChange={(e) => onChange(e.target.value)}
        rows={Math.max(10, code.split("\n").length + 2)}
        className="w-full rounded-lg border border-line bg-[#0f1220] p-3 font-mono text-sm leading-6 text-[#e6e9f5] focus:border-brand-500 focus:outline-none"
      />
      <div className="flex items-center gap-3">
        <Button type="button" variant="secondary" size="sm" onClick={runExamples} busy={busy} disabled={disabled}>
          Run examples
        </Button>
        <span className="text-xs text-muted">Submitting also runs hidden tests.</span>
      </div>
      <ErrorNote error={error} />
      {run && <RunResults run={run} />}
    </div>
  );
}

export function RunResults({ run }: { run: CodeRun }) {
  return (
    <div className="space-y-2 rounded-lg border border-line p-3 text-sm">
      {run.error ? (
        <p className="font-mono text-rose-600">{run.error}</p>
      ) : (
        <p className={run.passed === run.total ? "text-emerald-600" : "text-amber-600"}>
          Passed {run.passed} of {run.total} tests
        </p>
      )}
      <ul className="space-y-1 font-mono text-xs">
        {run.results.map((r, i) => (
          <li key={i} className={r.passed ? "text-emerald-700 dark:text-emerald-300" : "text-rose-700 dark:text-rose-300"}>
            {r.passed ? "✓" : "✗"}{" "}
            {r.hidden ? "hidden test" : `(${(r.args ?? []).map((a) => JSON.stringify(a)).join(", ")}) expected ${JSON.stringify(r.expected)}, got ${r.error ? r.error : JSON.stringify(r.got)}`}
          </li>
        ))}
      </ul>
      {run.stdout && <pre className="overflow-x-auto rounded bg-surface-2 p-2 text-xs">{run.stdout}</pre>}
    </div>
  );
}

function SpeakingAnswer({ question: q, transcript, onChange, disabled }: { question: Question; transcript: string; onChange: (v: string) => void; disabled?: boolean }) {
  const lang = q.payload.language ?? "en-IN";
  const speech = useSpeechRecognition(lang === "en-US" ? "en-IN" : lang);
  const heard = speech.listening ? speech.transcript : transcript || speech.transcript;
  return (
    <div className="space-y-3">
      <div className="rounded-xl bg-surface-2 p-5">
        <p className="text-xl font-medium leading-relaxed">{q.payload.sentence}</p>
        {q.payload.translation && (
          <p lang="te" className="mt-2 text-muted">
            {q.payload.translation}
          </p>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="secondary" size="sm" onClick={() => speak(q.payload.sentence ?? "", "en-IN")}>
          🔊 Listen
        </Button>
        {speech.supported ? (
          <Button
            type="button"
            size="sm"
            variant={speech.listening ? "danger" : "primary"}
            disabled={disabled}
            onClick={() => {
              if (speech.listening) {
                speech.stop();
                onChange(speech.transcript);
              } else speech.start();
            }}
          >
            {speech.listening ? "■ Stop" : "🎙 Speak"}
          </Button>
        ) : (
          <span className="text-sm text-muted">Voice input needs Chrome or Edge; you can type what you said instead.</span>
        )}
      </div>
      <ErrorNote error={speech.error || null} />
      <TextArea label="What we heard" rows={2} value={heard} disabled={disabled} onChange={(e) => onChange(e.target.value)} onBlur={() => speech.transcript && !transcript && onChange(speech.transcript)} />
    </div>
  );
}

// --------------------------------------------------------------------------- hints

export const STEP_LABELS: Record<string, string> = {
  hint: "Hint",
  concept: "Concept needed",
  approach: "Approach",
  solution: "Full solution",
  shortcut: "Shortcut",
  mistakes: "Common mistakes",
};

export function StepList({ steps }: { steps: Step[] }) {
  return (
    <ol className="space-y-2">
      {steps.map((s) => (
        <li key={s.step} className="rounded-lg bg-surface-2 p-3 text-sm">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{STEP_LABELS[s.kind] ?? s.kind}</div>
          <div className={cx("whitespace-pre-wrap", s.body.includes("\n    ") && "font-mono text-xs")}>{s.body}</div>
        </li>
      ))}
    </ol>
  );
}

/** Progressive help: one more step per click. Using hints lowers the mastery gain a little. */
export function HintPanel({ questionId }: { questionId: string }) {
  const [steps, setSteps] = useState<Step[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const next = steps.length + 1;
  const done = total !== null && steps.length >= total;

  async function more() {
    setBusy(true);
    try {
      const r = await api<{ steps: Step[]; total_steps: number }>(`/questions/${questionId}/steps/${next}`);
      setSteps(r.steps);
      setTotal(r.total_steps);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      {steps.length > 0 && <StepList steps={steps} />}
      <ErrorNote error={error} />
      {!done && (
        <Button type="button" variant="ghost" size="sm" onClick={more} busy={busy}>
          💡 {steps.length === 0 ? "Need a hint?" : `Show next step (${STEP_LABELS[["hint", "concept", "approach", "solution", "shortcut", "mistakes"][next - 1]] ?? "more"})`}
        </Button>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- feedback

export function describeAnswer(q: Question, answer: unknown): string {
  if (answer === null || answer === undefined) return "";
  const options = q.payload.options ?? [];
  const label = (id: unknown) => {
    const o = options.find((x) => x.id.toLowerCase() === String(id).toLowerCase());
    return o ? `(${o.id}) ${o.text}` : String(id);
  };
  if (Array.isArray(answer)) return answer.map(label).join(", ");
  if (q.qtype === "numerical") return `${answer}${q.payload.unit ? ` ${q.payload.unit}` : ""}`;
  return label(answer);
}

export function FeedbackView({ question: q, result }: { question: Question; result: AttemptResult }) {
  const fb: Feedback = result.feedback;
  const answer = describeAnswer(q, result.correct_answer);
  return (
    <div className="space-y-4">
      <div className={cx("rounded-xl p-4", result.is_correct ? "bg-emerald-50 text-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-100" : "bg-amber-50 text-amber-900 dark:bg-amber-950/50 dark:text-amber-100")}>
        <p className="text-lg font-semibold">{result.is_correct ? "Correct!" : result.score > 0 ? `Partly right (${pct(result.score)})` : "Not quite"}</p>
        {answer && !result.is_correct && <p className="mt-1">Correct answer: {answer}</p>}
        {fb.mistake_note && <p className="mt-2 text-sm">{fb.mistake_note}</p>}
      </div>
      {result.explanation && <p className="whitespace-pre-wrap leading-relaxed">{result.explanation}</p>}
      {fb.accuracy !== undefined && <SpeakingFeedback feedback={fb} />}
      {fb.run && <RunResults run={fb.run} />}
      {fb.review && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold">Code review</h3>
            <Badge tone="brand">{fb.review.score}/10</Badge>
            {fb.review_source === "offline" && <Badge>static analysis</Badge>}
          </div>
          <p className="text-sm text-muted">{fb.review.summary}</p>
          <ul className="space-y-2">
            {fb.review.findings.map((f, i) => (
              <li key={i} className="rounded-lg border border-line p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={f.severity === "error" ? "red" : f.severity === "warning" ? "amber" : "neutral"}>{f.severity}</Badge>
                  <span className="text-xs uppercase text-muted">{f.category}</span>
                  {f.line && <span className="text-xs text-muted">line {f.line}</span>}
                </div>
                <p className="mt-1">{f.message}</p>
                {f.suggestion && <p className="mt-1 text-muted">→ {f.suggestion}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {fb.evaluation && <EvaluationView feedback={fb} />}
      {result.mastery.length > 0 && (
        <div className="flex flex-wrap gap-2 text-sm">
          {result.mastery.map((m) => (
            <span key={m.concept_id} className="rounded-full bg-surface-2 px-3 py-1">
              Mastery {pct(m.before)} → <strong className={m.after >= m.before ? "text-emerald-600" : "text-rose-600"}>{pct(m.after)}</strong>
              {result.hints_used > 0 && <span className="text-muted"> · {result.hints_used} hint step(s) used</span>}
            </span>
          ))}
        </div>
      )}
      {result.steps.length > 0 && (
        <details className="rounded-lg border border-line p-3">
          <summary className="cursor-pointer font-medium">Step-by-step solution</summary>
          <div className="mt-3">
            <StepList steps={result.steps} />
          </div>
        </details>
      )}
    </div>
  );
}

function SpeakingFeedback({ feedback: fb }: { feedback: Feedback }) {
  return (
    <div className="space-y-2 rounded-lg border border-line p-3 text-sm">
      <p>
        Pronunciation match: <strong>{pct(fb.accuracy ?? 0)}</strong>
      </p>
      {fb.missed && fb.missed.length > 0 && <p>Missed words: {fb.missed.join(", ")}</p>}
      {fb.substitutions && fb.substitutions.length > 0 && (
        <ul>
          {fb.substitutions.map((s, i) => (
            <li key={i}>
              Expected “{s.expected}”, heard “{s.heard}”
            </li>
          ))}
        </ul>
      )}
      {fb.target && (
        <Button type="button" size="sm" variant="secondary" onClick={() => speak(fb.target ?? "")}>
          🔊 Hear it again
        </Button>
      )}
    </div>
  );
}

function EvaluationView({ feedback: fb }: { feedback: Feedback }) {
  const ev = fb.evaluation!;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <h3 className="font-semibold">Examiner’s evaluation</h3>
        <Badge tone="brand">
          {ev.total} / {ev.max_total}
        </Badge>
        {fb.evaluated_by === "offline" && <Badge>rubric matching</Badge>}
      </div>
      {fb.note && <Notice tone="amber">{fb.note}</Notice>}
      <table className="w-full text-sm">
        <tbody>
          {ev.criteria.map((c) => (
            <tr key={c.criterion} className="border-b border-line">
              <td className="py-2 pr-2">
                {c.criterion}
                {c.comment && <div className="text-xs text-muted">{c.comment}</div>}
              </td>
              <td className="py-2 text-right tabular-nums">
                {c.awarded} / {c.max_marks}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {ev.strengths.length > 0 && <BulletList title="What you did well" items={ev.strengths} />}
      {ev.improvements.length > 0 && <BulletList title="How to improve" items={ev.improvements} />}
      {ev.presentation_feedback && <p className="text-sm text-muted">{ev.presentation_feedback}</p>}
      {ev.model_answer && (
        <details className="rounded-lg border border-line p-3">
          <summary className="cursor-pointer font-medium">Model answer</summary>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">{ev.model_answer}</p>
        </details>
      )}
    </div>
  );
}

function BulletList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="text-sm font-medium">{title}</div>
      <ul className="ml-5 list-disc text-sm text-muted">
        {items.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ul>
    </div>
  );
}
