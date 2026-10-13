"use client";

import { Badge, Card, Notice } from "@/components/ui";
import type { QuestionPattern, Shortcut, Strategy, StudyPack } from "@/lib/types";

const KIND_LABEL: Record<Shortcut["kind"], string> = {
  shortcut: "Short trick",
  alternative: "Alternative method",
  elimination: "Elimination",
  approximation: "Approximation",
  memory: "Memory trick",
};

const FREQUENCY_TONE: Record<QuestionPattern["frequency"], "red" | "amber" | "neutral"> = { high: "red", medium: "amber", low: "neutral", rare: "neutral" };

export const TIER_LABEL: Record<string, string> = { tier1: "Tier 1", tier2: "Tier 2" };

export function tierText(tiers: string[]) {
  return tiers.map((t) => TIER_LABEL[t] ?? t).join(" · ");
}

export function StrategyCard({ s }: { s: Strategy }) {
  return (
    <div className="space-y-2 rounded-lg border border-line p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{s.title}</span>
        {s.scope !== "course" && <Badge>{s.scope_title || s.scope}</Badge>}
      </div>
      {s.summary && <p className="text-sm text-muted">{s.summary}</p>}
      {(s.minutes || s.seconds_per_question || s.accuracy_target) && (
        <p className="text-xs text-muted">
          {[
            s.minutes && `${s.minutes} min`,
            s.seconds_per_question && `${s.seconds_per_question} s per question`,
            s.target_attempts && `aim for ${s.target_attempts} attempts`,
            s.accuracy_target && `${Math.round(s.accuracy_target * 100)}% accuracy`,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
      {s.attempt_order && s.attempt_order.length > 0 && (
        <ol className="ml-5 list-decimal space-y-0.5 text-sm">
          {s.attempt_order.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
      )}
      {s.tactics && s.tactics.length > 0 && (
        <ul className="ml-5 list-disc space-y-0.5 text-sm">
          {s.tactics.map((t, i) => (
            <li key={i}>{t}</li>
          ))}
        </ul>
      )}
      {s.avoid && s.avoid.length > 0 && (
        <ul className="space-y-1 text-sm">
          {s.avoid.map((t, i) => (
            <li key={i} className="rounded bg-rose-50 px-2 py-1 text-rose-900 dark:bg-rose-950/40 dark:text-rose-100">
              ✗ {t}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Formula sheet, shortcut sheet, exam patterns, PYQ history and strategy of one concept. */
export function StudyPackView({ pack }: { pack: StudyPack }) {
  const empty = !pack.formulas.length && !pack.shortcuts.length && !pack.patterns.length && !pack.strategies.length;
  if (empty) {
    return pack.reviewed_only ? (
      <Card title="Study pack">
        <p className="text-sm text-muted">The formula sheet, short tricks and exam patterns for this concept are being prepared and reviewed.</p>
      </Card>
    ) : null;
  }
  const years = Object.entries(pack.pyq.by_year);
  return (
    <div className="space-y-4">
      {pack.preview && <Notice tone="amber">Preview: includes items still in review.</Notice>}
      {pack.formulas.length > 0 && (
        <Card title="Formula sheet">
          <ul className="space-y-3">
            {pack.formulas.map((f) => (
              <li key={f.id} className="rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{f.name}</span>
                  {f.status !== "verified" && <Badge tone="amber">in review</Badge>}
                </div>
                <p className="mt-1 rounded bg-surface-2 px-2 py-1 font-mono text-sm">{f.expression}</p>
                {f.variables.length > 0 && (
                  <p className="mt-1 text-xs text-muted">
                    {f.variables.map((v) => `${v.symbol}: ${v.meaning}`).join("; ")}
                  </p>
                )}
                {f.conditions && <p className="mt-1 text-sm">{f.conditions}</p>}
                {f.example?.problem && (
                  <p className="mt-1 text-sm text-muted">
                    e.g. {f.example.problem} → <span className="text-ink">{f.example.solution}</span>
                  </p>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
      {pack.shortcuts.length > 0 && (
        <Card title="Short tricks">
          <ul className="space-y-3">
            {pack.shortcuts.map((s) => (
              <li key={s.id} className="rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{s.title}</span>
                  <Badge tone="green">{KIND_LABEL[s.kind] ?? s.kind}</Badge>
                  {s.example?.seconds_saved ? <span className="text-xs text-muted">saves ~{s.example.seconds_saved} s</span> : null}
                </div>
                <p className="mt-1 text-sm">{s.rule}</p>
                {s.when_to_use && <p className="mt-1 text-xs text-muted">When: {s.when_to_use}</p>}
                {s.steps.length > 0 && (
                  <ol className="mt-1 ml-5 list-decimal text-sm">
                    {s.steps.map((step, i) => (
                      <li key={i}>{step}</li>
                    ))}
                  </ol>
                )}
                {s.example?.problem && (
                  <div className="mt-2 grid gap-2 text-sm sm:grid-cols-2">
                    {s.example.standard && (
                      <div className="rounded bg-surface-2 p-2">
                        <div className="text-xs text-muted">Standard way</div>
                        {s.example.standard}
                      </div>
                    )}
                    <div className="rounded bg-emerald-50 p-2 dark:bg-emerald-950/40">
                      <div className="text-xs text-muted">{s.example.problem}</div>
                      {s.example.shortcut}
                    </div>
                  </div>
                )}
                {s.pitfalls.length > 0 && <p className="mt-1 text-xs text-rose-700 dark:text-rose-300">Watch out: {s.pitfalls.join(" ")}</p>}
              </li>
            ))}
          </ul>
        </Card>
      )}
      {pack.patterns.length > 0 && (
        <Card title="How the exam asks it">
          {pack.pyq.total > 0 && (
            <p className="mb-3 text-sm">
              Asked {pack.pyq.total} time{pack.pyq.total === 1 ? "" : "s"} in previous papers
              {pack.pyq.first_year && pack.pyq.last_year ? ` (${pack.pyq.first_year}–${pack.pyq.last_year})` : ""}
              {years.length > 1 && <span className="text-muted">: {years.map(([y, n]) => `${y}: ${n}`).join(", ")}</span>}.
            </p>
          )}
          <ul className="space-y-3">
            {pack.patterns.map((p) => (
              <li key={p.id} className="rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{p.title}</span>
                  <Badge tone={FREQUENCY_TONE[p.frequency]}>{p.frequency} frequency</Badge>
                  {p.tiers.length > 0 && <span className="text-xs text-muted">{tierText(p.tiers)}</span>}
                  <span className="text-xs text-muted">~{p.target_seconds} s</span>
                  {p.pyq_count > 0 && <Badge tone="brand">{p.pyq_count} PYQ</Badge>}
                </div>
                {p.description && <p className="mt-1 text-sm text-muted">{p.description}</p>}
                {p.example_stem && <p className="mt-1 text-sm italic">“{p.example_stem}”</p>}
              </li>
            ))}
          </ul>
        </Card>
      )}
      {pack.strategies.length > 0 && (
        <Card title="Exam strategy">
          <div className="space-y-3">
            {pack.strategies.map((s) => (
              <StrategyCard key={s.id} s={s} />
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
