"use client";

import { type FormEvent, useEffect, useState } from "react";

import { RequireAuth, useAuth } from "@/components/auth";
import { LessonView } from "@/components/lesson";
import { STEP_LABELS } from "@/components/question";
import { Badge, Button, Card, Empty, ErrorNote, Field, Loading, Notice, PageHeader, Select, Stat, Tabs, TextArea } from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Course, CourseDetail, LessonBody, Option, TreeNode, User } from "@/lib/types";

type Tab = "overview" | "review" | "generate" | "documents" | "flags" | "usage" | "users";

// --------------------------------------------------------------------------- overview

function Overview() {
  const { data, error } = useApi<Record<string, number>>("/admin/stats");
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const labels: Record<string, string> = {
    users: "Users",
    courses: "Courses",
    concepts: "Concepts",
    questions_verified: "Verified questions",
    lessons_verified: "Verified lessons",
    in_review: "Waiting for review",
    enrollments: "Enrollments",
    attempts_7d: "Attempts (7 days)",
    documents: "Documents",
  };
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
      {Object.entries(labels).map(([k, label]) => (
        <Stat key={k} label={label} value={data[k] ?? 0} />
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------- review queue

type QueueItem = {
  asset_type: "lesson" | "question" | "flashcard" | "note";
  id: string;
  concept: string;
  source: string;
  level?: number;
  locale?: string;
  qtype?: string;
  content: Record<string, unknown>;
};

function editableContent(item: QueueItem) {
  if (item.asset_type === "question") {
    const c = item.content as { stem: string; explanation: string; difficulty: string; payload: unknown };
    return { stem: c.stem, explanation: c.explanation, difficulty: c.difficulty, payload: c.payload };
  }
  return item.content;
}

function QuestionPreview({ content }: { content: Record<string, unknown> }) {
  const c = content as { stem: string; payload: { options?: Option[]; answer?: string; answers?: string[] }; explanation: string; difficulty: string; steps: { kind: string; body: string }[] };
  const correct = new Set([c.payload.answer, ...(c.payload.answers ?? [])].filter(Boolean).map((x) => String(x).toLowerCase()));
  return (
    <div className="space-y-3 text-sm">
      <p className="whitespace-pre-wrap text-base">{c.stem}</p>
      {c.payload.options && (
        <ul className="space-y-1">
          {c.payload.options.map((o) => (
            <li key={o.id} className={correct.has(o.id.toLowerCase()) ? "font-semibold text-emerald-700 dark:text-emerald-300" : ""}>
              ({o.id}) {o.text} {correct.has(o.id.toLowerCase()) && "✓"}
            </li>
          ))}
        </ul>
      )}
      {!c.payload.options && <pre className="overflow-x-auto rounded bg-surface-2 p-2 text-xs">{JSON.stringify(c.payload, null, 2)}</pre>}
      {c.explanation && <p className="text-muted">{c.explanation}</p>}
      {c.steps?.length > 0 && (
        <ol className="space-y-1">
          {c.steps.map((s) => (
            <li key={s.kind}>
              <span className="font-medium">{STEP_LABELS[s.kind] ?? s.kind}:</span> {s.body}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function ReviewCard({ item, onDecided }: { item: QueueItem; onDecided: () => void }) {
  const [editing, setEditing] = useState(false);
  const [edits, setEdits] = useState(() => JSON.stringify(editableContent(item), null, 2));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function decide(decision: "approve" | "reject") {
    setBusy(true);
    setError(null);
    try {
      const body: { decision: string; edits?: unknown } = { decision };
      if (editing && decision === "approve") body.edits = JSON.parse(edits);
      await api(`/admin/assets/${item.asset_type}/${item.id}/decision`, { body });
      onDecided();
    } catch (e) {
      setError(e instanceof SyntaxError ? new Error(`Edits are not valid JSON: ${e.message}`) : e);
      setBusy(false);
    }
  }

  return (
    <Card
      title={
        <span className="flex flex-wrap items-center gap-2">
          <Badge tone="brand">{item.asset_type}</Badge>
          {item.concept}
          {item.level && <Badge>level {item.level}</Badge>}
          {item.locale && <Badge>{item.locale}</Badge>}
          {item.qtype && <Badge>{item.qtype}</Badge>}
          <Badge tone={item.source === "ai" ? "amber" : "neutral"}>{item.source}</Badge>
        </span>
      }
    >
      {editing ? (
        <TextArea aria-label="Edits (JSON)" rows={14} value={edits} onChange={(e) => setEdits(e.target.value)} className="font-mono text-xs" />
      ) : item.asset_type === "lesson" ? (
        <div className="max-h-96 overflow-y-auto rounded-lg border border-line p-4">
          <LessonView body={item.content as unknown as LessonBody} locale={item.locale ?? "en"} />
        </div>
      ) : item.asset_type === "question" ? (
        <QuestionPreview content={item.content} />
      ) : (
        <dl className="space-y-2 text-sm">
          {Object.entries(item.content).map(([k, v]) => (
            <div key={k}>
              <dt className="font-medium capitalize">{k}</dt>
              <dd className="whitespace-pre-wrap text-muted">{String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      <ErrorNote error={error} className="mt-3" />
      <div className="mt-4 flex flex-wrap gap-2">
        <Button size="sm" onClick={() => decide("approve")} busy={busy}>
          {editing ? "Save edits and approve" : "Approve"}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => setEditing(!editing)}>
          {editing ? "Cancel editing" : "Edit"}
        </Button>
        <Button size="sm" variant="danger" onClick={() => decide("reject")} busy={busy}>
          Reject
        </Button>
      </div>
    </Card>
  );
}

function ReviewQueue() {
  const [type, setType] = useState("");
  const { data, error, loading, reload } = useApi<QueueItem[]>("/admin/review-queue", { asset_type: type || undefined });
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Select aria-label="Asset type" value={type} onChange={(e) => setType(e.target.value)} className="w-48">
          <option value="">All assets</option>
          <option value="lesson">Lessons</option>
          <option value="question">Questions</option>
          <option value="flashcard">Flashcards</option>
          <option value="note">Notes</option>
        </Select>
        <span className="text-sm text-muted">AI drafts stay invisible to learners until approved.</span>
      </div>
      <ErrorNote error={error} />
      {loading ? <Loading /> : !data?.length ? <Empty title="The review queue is empty" /> : data.map((item) => <ReviewCard key={item.id} item={item} onDecided={reload} />)}
    </div>
  );
}

// --------------------------------------------------------------------------- generation

type Job = {
  id: string;
  kind: string;
  queue: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  payload: Record<string, unknown>;
  result: { created?: unknown[]; skipped?: number; providers?: string[] };
  error: string;
  attempts: number;
  max_attempts: number;
  cancel_requested: boolean;
  created_at: string;
  run_at: string;
  started_at: string | null;
  finished_at: string | null;
};
const JOB_TONES = { queued: "amber", running: "brand", done: "green", failed: "red", cancelled: "neutral" } as const;
/** Queued this long without a first attempt: probably no worker is running. */
const NO_WORKER_MS = 60_000;
type Doc = { id: string; title: string; filename: string; status: string; pages: number; chunks: number; error: string; course_id: string | null; created_at: string };

function flatConcepts(nodes: TreeNode[]): { id: string; title: string }[] {
  return nodes.flatMap((n) => [...n.concepts.map((c) => ({ id: c.id, title: c.title })), ...flatConcepts(n.children)]);
}

function Generate() {
  const courses = useApi<Course[]>("/courses");
  const docs = useApi<Doc[]>("/admin/documents");
  const jobs = useApi<Job[]>("/admin/jobs", { queue: "content" });
  const [kind, setKind] = useState("lessons");
  const [courseSlug, setCourseSlug] = useState("");
  const detail = useApi<CourseDetail>(courseSlug ? `/courses/${courseSlug}` : null);
  const [concepts, setConcepts] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [now, setNow] = useState(() => Date.now());
  const active = jobs.data?.some((j) => j.status === "queued" || j.status === "running");
  const waiting = jobs.data?.some((j) => j.status === "queued" && j.attempts === 0 && now - Date.parse(j.run_at) > NO_WORKER_MS);
  const reloadJobs = jobs.reload;

  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => {
      void reloadJobs();
      setNow(Date.now());
    }, 2000);
    return () => clearInterval(t);
  }, [active, reloadJobs]);

  async function jobAction(run: () => Promise<unknown>) {
    setError(null);
    try {
      await run();
      await jobs.reload();
    } catch (err) {
      setError(err);
    }
  }

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await api("/admin/generate", {
        body: {
          kind,
          course_id: detail.data?.id ?? null,
          concept_ids: concepts,
          document_id: f.get("document_id") || null,
          levels: f.getAll("levels").map(Number),
          locale: f.get("locale") ?? "en",
          qtype: f.get("qtype") ?? "mcq",
          difficulty: f.get("difficulty") ?? "medium",
          count: Number(f.get("count") ?? 5),
          title: f.get("title") || null,
        },
      });
      await jobs.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="New generation job">
        <form onSubmit={submit} className="space-y-4">
          <Select label="What to generate" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="lessons">Lessons</option>
            <option value="questions">Questions</option>
            <option value="flashcards">Flashcards</option>
            <option value="notes">Revision notes from a document</option>
            <option value="mock_test">Mock test</option>
          </Select>
          {kind !== "notes" && (
            <Select label="Course" value={courseSlug} onChange={(e) => (setCourseSlug(e.target.value), setConcepts([]))} required={kind === "mock_test"}>
              <option value="">Choose a course</option>
              {courses.data?.map((c) => (
                <option key={c.slug} value={c.slug}>
                  {c.title}
                </option>
              ))}
            </Select>
          )}
          {detail.data && kind !== "mock_test" && kind !== "notes" && (
            <fieldset className="max-h-48 space-y-1 overflow-y-auto rounded-lg border border-line p-3 text-sm">
              <legend className="px-1 text-xs text-muted">Concepts (none = whole course)</legend>
              {flatConcepts(detail.data.tree).map((c) => (
                <label key={c.id} className="flex items-center gap-2">
                  <input type="checkbox" checked={concepts.includes(c.id)} onChange={() => setConcepts(concepts.includes(c.id) ? concepts.filter((x) => x !== c.id) : [...concepts, c.id])} />
                  {c.title}
                </label>
              ))}
            </fieldset>
          )}
          {kind === "lessons" && (
            <div className="flex flex-wrap items-center gap-4 text-sm">
              {[1, 2, 3, 4].map((l) => (
                <label key={l} className="flex items-center gap-1">
                  <input type="checkbox" name="levels" value={l} defaultChecked={l <= 2} /> Level {l}
                </label>
              ))}
              <Select name="locale" aria-label="Language" defaultValue="en" className="w-32">
                <option value="en">English</option>
                <option value="te">Telugu</option>
                <option value="hi">Hindi</option>
              </Select>
            </div>
          )}
          {kind === "questions" && (
            <div className="grid grid-cols-2 gap-3">
              <Select label="Type" name="qtype" defaultValue="mcq">
                <option value="mcq">MCQ</option>
                <option value="multi">Multiple correct</option>
                <option value="assertion_reason">Assertion-reason</option>
                <option value="numerical">Numerical</option>
                <option value="descriptive">Descriptive</option>
              </Select>
              <Select label="Difficulty" name="difficulty" defaultValue="medium">
                {["beginner", "easy", "medium", "hard", "expert"].map((d) => (
                  <option key={d}>{d}</option>
                ))}
              </Select>
            </div>
          )}
          {(kind === "questions" || kind === "flashcards" || kind === "mock_test") && <Field label="How many" name="count" type="number" min={1} max={50} defaultValue={kind === "mock_test" ? 20 : 5} />}
          {kind === "mock_test" && <Field label="Title (optional)" name="title" />}
          {kind === "notes" && (
            <Select label="Document" name="document_id" required>
              <option value="">Choose a document</option>
              {docs.data
                ?.filter((d) => d.status === "chunked")
                .map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.title}
                  </option>
                ))}
            </Select>
          )}
          <ErrorNote error={error} />
          <Button type="submit" busy={busy}>
            Start job
          </Button>
        </form>
      </Card>
      <Card title="Recent jobs">
        {waiting && (
          <div className="mb-3">
            <Notice tone="amber">
              Jobs are waiting but no worker has picked them up. Start one with <code>python -m app.worker</code>, or run the API with{" "}
              <code>EDU_JOBS_EMBEDDED_WORKER=true</code>.
            </Notice>
          </div>
        )}
        {!jobs.data?.length ? (
          <p className="text-sm text-muted">No jobs yet.</p>
        ) : (
          <ul className="divide-y divide-line text-sm">
            {jobs.data.map((j) => (
              <li key={j.id} className="py-2">
                <div className="flex items-center gap-2">
                  <Badge tone={JOB_TONES[j.status] ?? "neutral"}>{j.status === "running" && j.cancel_requested ? "cancelling" : j.status}</Badge>
                  <span className="font-medium">{j.kind.replace(/^generate\./, "").replace("_", " ")}</span>
                  <span className="ml-auto text-xs text-muted">{new Date(j.created_at).toLocaleString()}</span>
                  {(j.status === "queued" || (j.status === "running" && !j.cancel_requested)) && (
                    <Button size="sm" variant="ghost" onClick={() => void jobAction(() => api(`/admin/jobs/${j.id}/cancel`, { method: "POST" }))}>
                      Cancel
                    </Button>
                  )}
                  {(j.status === "failed" || j.status === "cancelled") && (
                    <Button size="sm" variant="secondary" onClick={() => void jobAction(() => api(`/admin/jobs/${j.id}/retry`, { method: "POST" }))}>
                      Retry
                    </Button>
                  )}
                </div>
                {(j.status === "done" || (j.status === "cancelled" && j.result.created?.length)) && (
                  <p className="mt-1 text-xs text-muted">
                    Created {j.result.created?.length ?? 0}
                    {j.result.skipped ? `, skipped ${j.result.skipped} invalid` : ""} · via {j.result.providers?.join(", ") || "n/a"}
                  </p>
                )}
                {j.status === "queued" && j.attempts > 0 && (
                  <p className="mt-1 text-xs text-muted">
                    Attempt {j.attempts} of {j.max_attempts} failed; retrying at {new Date(j.run_at).toLocaleTimeString()}
                  </p>
                )}
                {j.error && (j.status === "failed" || j.status === "queued") && <p className="mt-1 text-xs text-rose-600">{j.error}</p>}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

// --------------------------------------------------------------------------- documents

function Documents() {
  const docs = useApi<Doc[]>("/admin/documents");
  const courses = useApi<Course[]>("/courses");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function upload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    if (!form.get("course_id")) form.delete("course_id");
    setBusy(true);
    setError(null);
    try {
      await api("/admin/documents", { form });
      (e.target as HTMLFormElement).reset();
      await docs.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Upload source material">
        <form onSubmit={upload} className="space-y-4">
          <label className="block text-sm">
            <span className="mb-1 block font-medium">File (PDF, TXT or Markdown)</span>
            <input type="file" name="file" accept=".pdf,.txt,.md" required className="block w-full text-sm" />
          </label>
          <Field label="Title" name="title" placeholder="Defaults to the file name" />
          <Select label="Course (used to ground AI lessons)" name="course_id" defaultValue="">
            <option value="">No course</option>
            {courses.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </Select>
          <Select label="Licence" name="licence" defaultValue="owned">
            <option value="owned">We own it</option>
            <option value="licensed">Licensed to us</option>
            <option value="open">Open licence</option>
          </Select>
          <Notice tone="amber">Only upload material you have the right to use. Scanned PDFs need OCR first.</Notice>
          <ErrorNote error={error} />
          <Button type="submit" busy={busy}>
            Upload and index
          </Button>
        </form>
      </Card>
      <Card title="Documents">
        {!docs.data?.length ? (
          <p className="text-sm text-muted">Nothing uploaded yet.</p>
        ) : (
          <ul className="divide-y divide-line text-sm">
            {docs.data.map((d) => (
              <li key={d.id} className="py-2">
                <div className="flex items-center gap-2">
                  <Badge tone={d.status === "chunked" ? "green" : d.status === "failed" ? "red" : "amber"}>{d.status}</Badge>
                  <span className="font-medium">{d.title}</span>
                </div>
                <p className="mt-1 text-xs text-muted">
                  {d.filename} · {d.pages} page(s) · {d.chunks} chunk(s)
                </p>
                {d.error && <p className="text-xs text-rose-600">{d.error}</p>}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

// --------------------------------------------------------------------------- flags, usage, users

function Flags() {
  const { data, error, reload } = useApi<{ id: string; asset_type: string; asset_id: string; reason: string; created_at: string }[]>("/admin/flags");
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  if (!data.length) return <Empty title="No open flags" />;
  return (
    <Card>
      <ul className="divide-y divide-line text-sm">
        {data.map((f) => (
          <li key={f.id} className="flex items-start gap-3 py-3">
            <Badge>{f.asset_type}</Badge>
            <div className="flex-1">
              <p>{f.reason}</p>
              <p className="text-xs text-muted">
                {f.asset_id} · {new Date(f.created_at).toLocaleString()}
              </p>
            </div>
            <Button
              size="sm"
              variant="secondary"
              onClick={async () => {
                await api(`/admin/flags/${f.id}/resolve`, { method: "POST" });
                await reload();
              }}
            >
              Resolve
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

type Usage = {
  status: { providers: string[]; mode: string };
  since: string;
  rows: { feature: string; provider: string; calls: number; input_tokens: number; output_tokens: number; cost_usd: number; avg_latency_ms: number; cache_hits: number }[];
};

function AiUsage() {
  const { data, error } = useApi<Usage>("/admin/ai-usage", { days: 30 });
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const total = data.rows.reduce((s, r) => s + r.cost_usd, 0);
  return (
    <Card title={`AI usage (last 30 days) · estimated $${total.toFixed(2)}`} action={<Badge tone={data.status.mode === "live" ? "green" : "neutral"}>{data.status.mode === "live" ? data.status.providers.join(", ") : "offline engines only"}</Badge>}>
      {!data.rows.length ? (
        <p className="text-sm text-muted">No AI calls yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-muted">
              <tr>
                <th className="py-1">Feature</th>
                <th>Provider</th>
                <th className="text-right">Calls</th>
                <th className="text-right">Cache hits</th>
                <th className="text-right">Tokens in / out</th>
                <th className="text-right">Avg latency</th>
                <th className="text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={`${r.feature}-${r.provider}`} className="border-t border-line tabular-nums">
                  <td className="py-2">{r.feature}</td>
                  <td>{r.provider}</td>
                  <td className="text-right">{r.calls}</td>
                  <td className="text-right">{r.cache_hits}</td>
                  <td className="text-right">
                    {r.input_tokens.toLocaleString()} / {r.output_tokens.toLocaleString()}
                  </td>
                  <td className="text-right">{r.avg_latency_ms} ms</td>
                  <td className="text-right">${r.cost_usd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function Users() {
  const [q, setQ] = useState("");
  const { data, error, reload } = useApi<(User & { status?: string })[]>("/admin/users", { q });
  const [rowError, setRowError] = useState<unknown>(null);
  async function patch(id: string, body: Record<string, string>) {
    try {
      await api(`/admin/users/${id}`, { method: "PATCH", body });
      await reload();
    } catch (e) {
      setRowError(e);
    }
  }
  return (
    <Card>
      <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by email" aria-label="Search users" className="mb-4 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm sm:w-80" />
      <ErrorNote error={error || rowError} />
      <ul className="divide-y divide-line text-sm">
        {data?.map((u) => (
          <li key={u.id} className="flex flex-wrap items-center gap-3 py-2">
            <div className="min-w-0 flex-1">
              <div className="font-medium">{u.name}</div>
              <div className="truncate text-xs text-muted">{u.email}</div>
            </div>
            <Select aria-label={`Role of ${u.email}`} value={u.role} onChange={(e) => patch(u.id, { role: e.target.value })} className="w-36">
              <option value="learner">learner</option>
              <option value="reviewer">reviewer</option>
              <option value="admin">admin</option>
            </Select>
            <Button size="sm" variant="secondary" onClick={() => patch(u.id, { status: "suspended" })}>
              Suspend
            </Button>
            <Button size="sm" variant="ghost" onClick={() => patch(u.id, { status: "active" })}>
              Reactivate
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Admin() {
  const { me } = useAuth();
  const [tab, setTab] = useState<Tab>("overview");
  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "review", label: "Review queue" },
    { id: "generate", label: "Generate" },
    { id: "documents", label: "Documents" },
    { id: "flags", label: "Flags" },
    { id: "usage", label: "AI usage" },
    ...(me?.role === "admin" ? [{ id: "users" as Tab, label: "Users" }] : []),
  ];
  return (
    <div className="space-y-6">
      <PageHeader title="Content studio" subtitle="Generate, review and publish learning content; watch AI usage and cost." />
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === "overview" && <Overview />}
      {tab === "review" && <ReviewQueue />}
      {tab === "generate" && <Generate />}
      {tab === "documents" && <Documents />}
      {tab === "flags" && <Flags />}
      {tab === "usage" && <AiUsage />}
      {tab === "users" && <Users />}
    </div>
  );
}

export default function AdminPage() {
  return (
    <RequireAuth roles={["reviewer", "admin"]}>
      <Admin />
    </RequireAuth>
  );
}
