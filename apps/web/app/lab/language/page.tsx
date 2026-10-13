"use client";

import { type FormEvent, useState } from "react";

import { RequireAuth } from "@/components/auth";
import { FeedbackView, isAnswered, QuestionInput, type Response } from "@/components/question";
import { Badge, Button, Card, cx, Empty, ErrorNote, Loading, PageHeader, Select, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { speak, useSpeechRecognition } from "@/lib/speech";
import type { AttemptResult, Question } from "@/lib/types";

type Correction = { original: string; corrected: string; explanation: string };
type Turn = { role: "user" | "assistant"; content: string; corrections?: Correction[]; vocabulary?: { word: string; meaning: string }[] };
type ChatReply = { conversation_id: string; reply: string; corrections: Correction[]; vocabulary: { word: string; meaning: string }[]; next_prompt: string; provider: string };

const SCENARIOS = ["Everyday conversation", "Introducing yourself in an interview", "Ordering food at a restaurant", "Calling customer care about a problem", "Asking for directions"];

function Conversation() {
  const [level, setLevel] = useState("A2");
  const [scenario, setScenario] = useState(SCENARIOS[0]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conversation, setConversation] = useState<string | null>(null);
  const [hint, setHint] = useState("");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const speech = useSpeechRecognition("en-IN");

  async function send(message: string) {
    if (!message.trim()) return;
    setBusy(true);
    setError(null);
    setDraft("");
    setTurns((t) => [...t, { role: "user", content: message }]);
    try {
      const r = await api<ChatReply>("/language/chat", { body: { message, level, scenario, target_language: "English", conversation_id: conversation } });
      setConversation(r.conversation_id);
      setTurns((t) => {
        const copy = [...t];
        copy[copy.length - 1] = { ...copy[copy.length - 1], corrections: r.corrections };
        return [...copy, { role: "assistant", content: r.reply, vocabulary: r.vocabulary }];
      });
      setHint(r.next_prompt);
      speak(r.reply);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="mb-4 grid gap-3 sm:grid-cols-2">
        <Select
          label="Scenario"
          value={scenario}
          onChange={(e) => {
            setScenario(e.target.value);
            setTurns([]);
            setConversation(null);
          }}
        >
          {SCENARIOS.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </Select>
        <Select label="Your level (CEFR)" value={level} onChange={(e) => setLevel(e.target.value)}>
          {["A1", "A2", "B1", "B2", "C1", "C2"].map((l) => (
            <option key={l}>{l}</option>
          ))}
        </Select>
      </div>
      <div className="min-h-48 space-y-3" aria-live="polite">
        {turns.length === 0 && <p className="text-sm text-muted">Say hello, or describe your day. Your partner replies and gently corrects mistakes.</p>}
        {turns.map((t, i) => (
          <div key={i} className={cx("max-w-[85%] space-y-2", t.role === "user" ? "ml-auto" : "")}>
            <div className={cx("rounded-2xl px-4 py-2", t.role === "user" ? "bg-brand-600 text-white" : "bg-surface-2")}>{t.content}</div>
            {t.corrections?.map((c, j) => (
              <div key={j} className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100">
                <span className="line-through opacity-70">{c.original}</span> → <strong>{c.corrected}</strong>
                <div className="text-xs">{c.explanation}</div>
              </div>
            ))}
            {t.vocabulary && t.vocabulary.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {t.vocabulary.map((v) => (
                  <Badge key={v.word} tone="brand">
                    {v.word}: {v.meaning}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      {hint && <p className="mt-3 text-sm text-muted">Try saying: {hint}</p>}
      <ErrorNote error={error || speech.error || null} className="mt-2" />
      <form
        className="mt-4 flex gap-2"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          void send(draft || speech.transcript);
        }}
      >
        <input
          value={speech.listening ? speech.transcript : draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Type or speak in English"
          aria-label="Your message"
          className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2"
          maxLength={2000}
        />
        {speech.supported && (
          <Button
            type="button"
            variant={speech.listening ? "danger" : "secondary"}
            onClick={() => {
              if (speech.listening) {
                speech.stop();
                setDraft(speech.transcript);
              } else speech.start();
            }}
            aria-label={speech.listening ? "Stop recording" : "Speak"}
          >
            {speech.listening ? "■" : "🎙"}
          </Button>
        )}
        <Button type="submit" busy={busy}>
          Send
        </Button>
      </form>
    </Card>
  );
}

function SpeakingDrills() {
  const items = useApi<Question[]>("/language/speaking", { language: "en-IN" });
  const [index, setIndex] = useState(0);
  const [response, setResponse] = useState<Response>({});
  const [result, setResult] = useState<AttemptResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (items.loading) return <Loading />;
  if (items.error) return <ErrorNote error={items.error} />;
  if (!items.data?.length) return <Empty title="No speaking drills yet" />;
  const q = items.data[index % items.data.length];

  return (
    <Card title={`Drill ${(index % items.data.length) + 1} of ${items.data.length}`}>
      <QuestionInput key={q.id} question={q} value={response} onChange={setResponse} disabled={Boolean(result)} />
      <ErrorNote error={error} className="mt-3" />
      <div className="mt-4 space-y-4">
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
            Score my pronunciation
          </Button>
        ) : (
          <>
            <FeedbackView question={q} result={result} />
            <Button
              onClick={() => {
                setIndex(index + 1);
                setResponse({});
                setResult(null);
              }}
            >
              Next sentence →
            </Button>
          </>
        )}
      </div>
    </Card>
  );
}

function LanguageLab() {
  const [tab, setTab] = useState<"chat" | "speak">("chat");
  return (
    <div className="space-y-6">
      <PageHeader title="Language lab" subtitle="Practise spoken English: a patient conversation partner, and pronunciation drills scored from your voice." />
      <Tabs
        tabs={[
          { id: "chat", label: "Conversation" },
          { id: "speak", label: "Pronunciation drills" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "chat" ? <Conversation /> : <SpeakingDrills />}
    </div>
  );
}

export default function LanguageLabPage() {
  return (
    <RequireAuth>
      <LanguageLab />
    </RequireAuth>
  );
}
