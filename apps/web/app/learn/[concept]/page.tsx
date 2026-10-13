"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { RequireAuth, useAuth } from "@/components/auth";
import { LessonView } from "@/components/lesson";
import { StudyPackView } from "@/components/study-pack";
import { Badge, Button, ButtonLink, Card, cx, ErrorNote, Loading, Notice, PageHeader, Tabs, TextArea } from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { ConceptDetail, Lesson, StudyPack } from "@/lib/types";

const LEVELS = [
  { id: "1", label: "Beginner" },
  { id: "2", label: "Intermediate" },
  { id: "3", label: "Advanced" },
  { id: "4", label: "Expert" },
] as const;
type LevelId = (typeof LEVELS)[number]["id"];

function Flashcards({ concept }: { concept: string }) {
  const { data } = useApi<{ id: string; front: string; back: string }[]>(`/concepts/${concept}/flashcards`);
  const [i, setI] = useState(0);
  const [flipped, setFlipped] = useState(false);
  if (!data?.length) return null;
  const card = data[i % data.length];
  return (
    <Card title={`Flashcards (${(i % data.length) + 1}/${data.length})`}>
      <button onClick={() => setFlipped(!flipped)} className="grid min-h-28 w-full place-items-center rounded-lg bg-surface-2 p-4 text-center" aria-label="Flip card">
        <span className={flipped ? "font-semibold text-emerald-700 dark:text-emerald-300" : "font-medium"}>{flipped ? card.back : card.front}</span>
      </button>
      <div className="mt-3 flex justify-between">
        <span className="text-xs text-muted">Tap the card to flip</span>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            setI(i + 1);
            setFlipped(false);
          }}
        >
          Next card
        </Button>
      </div>
    </Card>
  );
}

type Msg = { role: "user" | "assistant"; content: string };

function Tutor({ concept, locale, level }: { concept: string; locale: string; level: number }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [conversation, setConversation] = useState<string | null>(null);
  const [followUps, setFollowUps] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [draft, setDraft] = useState("");

  async function ask(question: string) {
    if (!question.trim()) return;
    setBusy(true);
    setError(null);
    setMessages((m) => [...m, { role: "user", content: question }]);
    setDraft("");
    try {
      const r = await api<{ conversation_id: string; reply: string; follow_up_questions: string[] }>(`/concepts/${concept}/ask`, {
        body: { question, conversation_id: conversation, locale, level },
      });
      setConversation(r.conversation_id);
      setMessages((m) => [...m, { role: "assistant", content: r.reply }]);
      setFollowUps(r.follow_up_questions);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Ask your tutor">
      <div className="max-h-80 space-y-2 overflow-y-auto" aria-live="polite">
        {messages.length === 0 && <p className="text-sm text-muted">Stuck on something in this lesson? Ask in your own words.</p>}
        {messages.map((m, i) => (
          <div key={i} className={cx("rounded-lg px-3 py-2 text-sm", m.role === "user" ? "ml-8 bg-brand-600 text-white" : "mr-8 bg-surface-2")}>
            {m.content}
          </div>
        ))}
      </div>
      {followUps.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {followUps.map((f) => (
            <button key={f} onClick={() => ask(f)} className="rounded-full border border-line px-3 py-1 text-xs hover:bg-surface-2" disabled={busy}>
              {f}
            </button>
          ))}
        </div>
      )}
      <ErrorNote error={error} className="mt-2" />
      <form
        className="mt-3 flex gap-2"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          void ask(draft);
        }}
      >
        <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Type a question" aria-label="Question for the tutor" className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm" maxLength={2000} />
        <Button type="submit" size="sm" busy={busy}>
          Ask
        </Button>
      </form>
    </Card>
  );
}

function FlagButton({ lessonId }: { lessonId: string }) {
  const [open, setOpen] = useState(false);
  const [sent, setSent] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  if (sent) return <span className="text-sm text-muted">Thanks, a reviewer will check it.</span>;
  if (!open)
    return (
      <button className="text-sm text-muted hover:text-ink" onClick={() => setOpen(true)}>
        ⚑ Report a problem
      </button>
    );
  return (
    <form
      className="w-full space-y-2"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await api("/content/flags", { body: { asset_type: "lesson", asset_id: lessonId, reason } });
          setSent(true);
        } catch (err) {
          setError(err);
        }
      }}
    >
      <TextArea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="What is wrong or unclear?" minLength={3} required />
      <ErrorNote error={error} />
      <Button size="sm" type="submit" variant="secondary">
        Send report
      </Button>
    </form>
  );
}

function LearnView() {
  const { concept } = useParams<{ concept: string }>();
  const { me } = useAuth();
  const detail = useApi<ConceptDetail>(`/concepts/${concept}`);
  const [level, setLevel] = useState<LevelId>("1");
  const [locale, setLocale] = useState(me?.preferred_locale === "te" ? "te" : "en");
  const lesson = useApi<Lesson>(`/concepts/${concept}/lesson`, { level, locale });
  const staff = me?.role === "admin" || me?.role === "reviewer";
  const [preview, setPreview] = useState(false);
  const pack = useApi<StudyPack>(`/concepts/${concept}/study-pack`, preview ? { preview: true } : undefined);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<unknown>(null);
  const [completed, setCompleted] = useState(false);
  const opened = useRef(0);

  useEffect(() => {
    opened.current = Date.now();
  }, [concept, level]);

  if (detail.loading) return <Loading />;
  if (detail.error || !detail.data) return <ErrorNote error={detail.error} />;
  const d = detail.data;
  const hasTelugu = Boolean(d.lesson_levels.te?.length);

  async function generate() {
    setGenerating(true);
    setGenError(null);
    try {
      lesson.setData(await api<Lesson>(`/concepts/${concept}/lesson`, { query: { level, locale, generate: true } }));
    } catch (e) {
      setGenError(e);
    } finally {
      setGenerating(false);
    }
  }

  async function markComplete() {
    const seconds = Math.min(36000, Math.round((Date.now() - opened.current) / 1000));
    await api("/me/lessons/progress", { body: { concept_id: d.id, lesson_id: lesson.data?.id ?? null, level: Number(level), seconds, completed: true } });
    setCompleted(true);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={d.title}
        subtitle={d.summary}
        action={
          <div className="flex gap-2">
            <ButtonLink href={`/practice?concept=${d.id}`}>Practise ({d.question_count})</ButtonLink>
          </div>
        }
      />
      <div className="flex flex-wrap items-center gap-3">
        <Tabs tabs={LEVELS.map((l) => ({ id: l.id, label: l.label }))} value={level} onChange={setLevel} />
        {(hasTelugu || locale === "te") && <Tabs tabs={[{ id: "en", label: "English" }, { id: "te", label: "తెలుగు" }]} value={locale} onChange={setLocale} />}
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card>
            {lesson.loading ? (
              <Loading label="Loading lesson" />
            ) : lesson.error ? (
              <ErrorNote error={lesson.error} />
            ) : lesson.data?.body ? (
              <>
                {lesson.data.note && (
                  <div className="mb-4">
                    <Notice tone="amber">{lesson.data.note}</Notice>
                  </div>
                )}
                {!lesson.data.verified && lesson.data.status === "in_review" && !lesson.data.note && (
                  <div className="mb-4">
                    <Badge tone="amber">Draft awaiting review</Badge>
                  </div>
                )}
                <LessonView body={lesson.data.body} locale={lesson.data.locale} />
                <div className="mt-8 flex flex-wrap items-center gap-4 border-t border-line pt-4">
                  {completed ? (
                    <Notice tone="green">Marked as learned. Your first revision is scheduled for day 3.</Notice>
                  ) : (
                    <Button variant="secondary" onClick={markComplete}>
                      ✓ I have learned this
                    </Button>
                  )}
                  {lesson.data.id && <FlagButton lessonId={lesson.data.id} />}
                </div>
              </>
            ) : lesson.data?.can_generate === false ? (
              <div className="space-y-2 py-6 text-center">
                <p className="font-medium">The {LEVELS.find((l) => l.id === level)?.label.toLowerCase()} lesson is on its way.</p>
                <p className="text-sm text-muted">{lesson.data.note ?? "It is being prepared and reviewed by the content team."} Practice and the study pack below are available meanwhile.</p>
              </div>
            ) : (
              <div className="space-y-3 py-6 text-center">
                <p className="font-medium">No {LEVELS.find((l) => l.id === level)?.label.toLowerCase()} lesson yet.</p>
                <p className="text-sm text-muted">Generate a draft from the course material. It is marked as unverified until a reviewer approves it.</p>
                <ErrorNote error={genError} />
                <Button onClick={generate} busy={generating}>
                  Generate a draft lesson
                </Button>
              </div>
            )}
          </Card>
          {staff && (
            <label className="flex items-center gap-2 text-sm text-muted">
              <input type="checkbox" checked={preview} onChange={(e) => setPreview(e.target.checked)} />
              Preview study pack items still in review
            </label>
          )}
          {pack.error ? <ErrorNote error={pack.error} /> : pack.data ? <StudyPackView pack={pack.data} /> : null}
        </div>
        <div className="space-y-4">
          {(d.prerequisites.length > 0 || d.unlocks.length > 0) && (
            <Card title="Where this fits">
              {d.prerequisites.length > 0 && (
                <div className="mb-3 text-sm">
                  <div className="mb-1 text-muted">Builds on</div>
                  {d.prerequisites.map((p) => (
                    <Link key={p.id} href={`/learn/${p.slug}`} className="mr-2 inline-block text-brand-600 hover:underline">
                      {p.title}
                    </Link>
                  ))}
                </div>
              )}
              {d.unlocks.length > 0 && (
                <div className="text-sm">
                  <div className="mb-1 text-muted">Unlocks</div>
                  {d.unlocks.map((p) => (
                    <Link key={p.id} href={`/learn/${p.slug}`} className="mr-2 inline-block text-brand-600 hover:underline">
                      {p.title}
                    </Link>
                  ))}
                </div>
              )}
            </Card>
          )}
          <Flashcards concept={d.id} />
          <Tutor concept={d.id} locale={locale} level={Number(level)} />
        </div>
      </div>
    </div>
  );
}

export default function LearnPage() {
  return (
    <RequireAuth>
      <LearnView />
    </RequireAuth>
  );
}
