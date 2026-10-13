# Phase 2 implementation plan

Status: **approved** (2026-10-13). Each step below ships as its own PR; the next starts once the previous one is green.

Phase 2 takes EduVerse from "runs on a laptop" to an invite-only pilot of SSC CGL Quantitative Aptitude on managed hosting.

## Decisions

| # | Topic | Decision |
| --- | --- | --- |
| 1 | Job queue | PostgreSQL-backed persistent queue first, behind a backend interface so Redis can replace the transport later. |
| 2 | Email | Amazon SES, behind a mail-provider interface (console for dev, SMTP as a fallback). |
| 3 | Embeddings | Multilingual bge-m3 (1024-dim dense vectors) behind an embedding-provider interface. |
| 4 | Judge0 | Deployment deferred. Build the integration interface and contract tests now; deploy when the Python course launches. |
| 5 | Pilot course | SSC CGL Quantitative Aptitude. |
| 6 | Hosting | Managed services: web on Vercel, API and worker on AWS / Railway / Render, managed PostgreSQL. Keep the Docker images so the AWS ECS migration path stays open. |
| 7 | Registration | Invite-only beta. |

Why the job queue goes first: password-reset emails, document ingestion and AI generation all run as jobs, so everything else depends on it. The pilot does not depend on Judge0, because SSC Quant has no code questions.

## Order and estimates

Estimates are focused developer-days.

| PR | Scope | Depends on | Estimate |
| --- | --- | --- | --- |
| #2 | Job queue + worker service | – | 3–4 days |
| #3 | Mail (SES) + password reset + email verification + invite-only registration | #2 | 3–4 days |
| #4 | Production AI configuration: secrets, smoke check, spend caps, prompt caching | #2 | 2–3 days, plus 1–2 days for the eval set once keys exist |
| #5 | Content ingestion: async jobs, S3 storage, PostgreSQL full-text search, PYQ importer | #2 | 4–5 days |
| #6 | Pilot deployment: SSC CGL Quant | #2–#5 | 4–6 days, plus content review time |
| #7 | Embeddings (bge-m3) + hybrid retrieval | #5 | 2–3 days |
| #8 | Judge0 integration interface (no deployment) | #2 | 1–2 days |

The pilot path is #2 → #3 → #4 → #5 → #6, about 3–4 weeks. #7 and #8 can follow the pilot or run in parallel with it.

### Revised order (2026-10-13)

The owner widened the pilot from SSC CGL Quantitative Aptitude to the **complete SSC CGL course**
(all five subjects, Tier 1 and Tier 2) built on a generate-once, review, serve-many content engine.
The remaining PRs are now:

| PR | Scope | Status |
| --- | --- | --- |
| #5 | SSC CGL content engine foundation: complete syllabus as data, Tier 1 / Tier 2 profiles, concept-level content model (formulas, shortcuts, patterns, strategies), PYQ import, reviewed-only serving, coverage | done, see [content-engine.md](content-engine.md) |
| #6 | AI content generation engine: planner, batch jobs, grounded prompts, automatic checks, review at scale, document ingestion (S3, full-text search, moved here from the old #5), sectioned mocks | planned, see [content-engine.md](content-engine.md#pr-6-plan-ai-content-generation-engine) |
| #7 | Pilot deployment (section 5 below), for SSC CGL as its subjects reach full coverage | – |
| #8 | Embeddings (bge-m3) + hybrid retrieval | – |
| #9 | Judge0 integration interface (no deployment) | – |

Sections 4–6 below keep their original text; where they disagree with this table, the table wins.

---

## 1. Persistent job queue (PR #2)

**Problem.** Generation jobs run in FastAPI `BackgroundTasks` inside the API process. An API restart loses the running job, and long AI jobs tie up API workers.

### Architecture

- **Package.** A new `app/jobs/` package that every module uses through `app.jobs.enqueue(...)`. The `jobs` table is the single source of truth for status, results and errors. A `QueueBackend` interface owns only the transport, meaning how workers find and claim work.
- **Database backend** (the only backend for now):
  - **Claiming:** `SELECT … FOR UPDATE SKIP LOCKED`, then a compare-and-set update. Any number of workers can run safely; on SQLite the compare-and-set alone keeps claims correct.
  - **Wake-up:** `LISTEN/NOTIFY` on PostgreSQL wakes idle workers as soon as a job commits; otherwise workers poll.
  - **Transactional enqueue:** the job row commits in the same transaction as the change that caused it, so no job is lost or orphaned.
- **Redis path.** A future `RedisQueue` would push job ids to a Redis stream after commit and workers would claim from it. The `jobs` table, handlers and API stay unchanged.
- **Worker** (`python -m app.worker [--queues content,maintenance]`). It runs one job at a time; to scale, run more workers.
  - **Liveness:** a heartbeat thread keeps `heartbeat_at` fresh. Each claim gets a random lease token, so a worker that lost its job cannot write results.
  - **Crash recovery:** a reaper re-queues jobs whose worker stopped heart-beating. A job that has used up its attempts is marked failed.
  - **Retries:** exponential backoff with jitter for unexpected errors. Validation errors (`AppError`, `PermanentJobError`) fail at once.
  - **Checkpoints:** handlers commit progress item by item, in the same transaction as the content they create. A retried job skips finished items, so it never generates or pays for the same lesson twice.
  - **Cancellation:** a queued job is cancelled immediately. A running job stops at its next checkpoint.
  - **Graceful shutdown:** on SIGTERM the worker finishes the current item, then hands the job back to the queue without using up an attempt.
  - **Periodic jobs:** scheduled with bucketed dedupe keys, so many workers enqueue each run once. The first periodic job prunes old finished jobs and expired refresh tokens.
- **Embedded worker.** `EDU_JOBS_EMBEDDED_WORKER=true`, the default, runs a worker thread inside the API process. That suits local development, `docker run` demos and a single small instance. Compose and production run a dedicated `worker` service and set it to `false`.

### Database

- **New `jobs` table:**
  - Fields: `kind`, `queue`, `payload`, `status` (`queued` | `running` | `done` | `failed` | `cancelled`), `priority`, `run_at`, `attempts`, `max_attempts`.
  - Locking and progress: `locked_by`, `lease`, `heartbeat_at`, `cancel_requested`, `result`, `checkpoint`, `error`, `dedupe_key` (unique), `created_by`.
  - Timestamps: `created_at`, `started_at`, `finished_at`, `updated_at`.
  - Claim index on `(status, queue, run_at)`.
- **Migration `0002_jobs_queue`:**
  - Copies `generation_jobs` into `jobs`, keeping the ids so audit entries still resolve. `lessons` becomes `generate.lessons`, and so on for each kind. Jobs that were `running` are re-queued.
  - Drops `generation_jobs`. The downgrade reverses both steps.

### API

- **`POST /admin/generate`:** unchanged; returns 202 with the job id.
- **`GET /admin/jobs`:** gains `status`, `queue` and `kind` filters, and rows gain `attempts`, `max_attempts`, `run_at`, `started_at` and `cancel_requested`.
- **New endpoints:** `POST /admin/jobs/{id}/cancel` and `POST /admin/jobs/{id}/retry` (409 when the job is in the wrong state).
- **Web content studio:** shows attempts, retry times and cancel/retry buttons, and warns when jobs wait with no worker picking them up.

### Settings

`EDU_JOBS_EMBEDDED_WORKER`, `EDU_JOBS_POLL_SECONDS`, `EDU_JOBS_HEARTBEAT_SECONDS`, `EDU_JOBS_STALE_AFTER_SECONDS`, `EDU_JOBS_RETRY_BASE_SECONDS`, `EDU_JOBS_RETENTION_DAYS`.

## 2. Mail, password reset, email verification, invites (PR #3)

### Architecture

- **Mail layer:** `app/core/mail.py` with a `MailBackend` interface and three backends:
  - `console` for development: logs the message.
  - `smtp`.
  - `ses`: Amazon SES v2 `SendEmail` through boto3, in region `ap-south-1`.
  - Emails go out as `mail.send` jobs, so a provider outage means a retry rather than a lost email. Templates are in English and Telugu.
- **SES setup:**
  - Verify the sending domain with DKIM, SPF and DMARC, and request production access to leave the SES sandbox.
  - Route bounce and complaint notifications through SNS to an endpoint that suppresses those addresses.
- **Password reset:**
  - `forgot` returns the same 202 for unknown emails, so it cannot be used to discover accounts.
  - Tokens are 32 random bytes. The database stores only their SHA-256 hash; each token works once and expires after 30 minutes.
  - Requests are rate-limited per IP and per email.
- **After a successful reset:**
  - Every refresh-token family is revoked.
  - `token_version` is bumped, so access tokens already issued stop working at once.
  - The reset is written to the audit log, and a "your password changed" email goes out.
- **Email verification:** sent at registration. AI features can be gated on it.
- **Invite-only registration:**
  - With `EDU_REGISTRATION_MODE=invite`, registering requires a valid invite code, single-use or with a limited number of uses, optionally tied to an email address.
  - Admins create and revoke invites in the content studio.

### Database

- `users.email_verified_at` and `users.token_version` (the JWT carries `ver`).
- New `account_tokens` table: `user_id`, `purpose` (`reset` | `verify`), `token_hash` (unique), `expires_at`, `used_at`, `requested_ip`.
- New `invites` table: `code_hash`, `email`, `max_uses`, `uses`, `expires_at`, `created_by`, `revoked_at`.

### API

**Auth endpoints:**

| Endpoint | Response |
| --- | --- |
| `POST /auth/password/forgot` | 202 |
| `POST /auth/password/reset {token, new_password}` | 204 |
| `POST /auth/email/verify {token}` | – |
| `POST /auth/email/resend` | – |
| `POST /me/password {current_password, new_password}` | – |

**Invites:**
- `RegisterIn.invite_code`.
- Admin endpoints: `POST /admin/invites`, `GET /admin/invites`, `DELETE /admin/invites/{id}`.

**Web:**
- Pages `/forgot-password`, `/reset-password` and `/verify-email`, all with `Referrer-Policy: no-referrer`.
- A change-password form in the profile.
- An invite field on the register page.

**Settings:**
- `EDU_MAIL_BACKEND`, `EDU_MAIL_FROM`, `EDU_SES_REGION`, `EDU_SMTP_URL`.
- `EDU_PUBLIC_WEB_URL`, used to build links.
- `EDU_REGISTRATION_MODE`.

## 3. Production AI configuration (PR #4)

### Architecture

- **Secrets:**
  - Keys come from the platform's secret store: Render or Railway secrets, or AWS Secrets Manager on ECS.
  - A pydantic `secrets_dir` also reads `/run/secrets`.
  - A secondary key allows rotation without downtime.
- **Smoke check:** `python -m app.ai.check` makes one tiny call per tier to prove the key and model access. It runs on deploy, and an admin can trigger it from the web.
- **Per-task overrides:**
  - Model and effort can be set per task: the examiner on Opus 5.5, the tutor on Sonnet 5.5, mistake notes on Haiku 5.5.
  - Opus 5.5 starts at `effort: medium` and is raised only where the eval set shows it pays.
- **Cost controls:**
  - An organisation-wide daily spend cap switches to offline engines when reached, with an alert at 80%.
  - Prompt caching on the large static system prompt (preamble plus schema).
- **Structured outputs:** where the model supports them, they replace the JSON-repair round trip. Model support is checked when this PR is implemented.
- **Eval set:** a small golden set per engine (lesson, questions, examiner, tutor) runs whenever a prompt or model changes. This is the first job once keys are available.
- **Privacy:** learner names are pseudonymised in mentor prompts.

### Database

New `llm_calls` columns: `request_id`, `stop_reason`, `refusal_category`, `served_model` (to track fallbacks), `cache_read_tokens` and `cache_write_tokens`.

### API

- `GET /admin/ai/status`: tiers, models, budget used, and fallback and refusal rates.
- `POST /admin/ai/check`: staff only, rate-limited.

## 4. Content ingestion pipeline (PR #5, embeddings in PR #7)

### Architecture

- **Async uploads:** an upload returns 202 and starts an `ingest.document` job that parses, chunks and indexes the document, ending in `ready` or `failed`.
- **Storage:** files live in S3, with MinIO in compose for local runs, behind a small `ObjectStore` interface. A content hash dedupes re-uploads.
- **Extraction:**
  - pypdf first, with pdfplumber (MIT licence) as a fallback. PyMuPDF is avoided because of its AGPL licence.
  - DOCX and PPTX support.
  - An optional OCR job (`ocrmypdf` with Tesseract `eng` + `tel`) for scanned PDFs.
- **Retrieval, step 1:** PostgreSQL full-text search (`tsvector` + GIN) replaces in-process BM25 on PostgreSQL. SQLite keeps the current BM25.
- **Retrieval, step 2 (PR #7):**
  - An `EmbeddingProvider` interface whose first implementation calls a bge-m3 server: Hugging Face text-embeddings-inference, which speaks the OpenAI-compatible `/embeddings` API.
  - Vectors go in `chunks.embedding vector(1024)` with an HNSW index. Results are merged with full-text search by reciprocal rank fusion.
  - Each chunk records its embedding model, so a model change re-embeds through a job.
- **Chunk → concept tagging:** chunks are tagged with concepts, so lessons and questions are grounded in the right material.
- **PYQ importer:**
  - Reads CSV or JSON and reuses the seed loader's validators.
  - Dedupes on a hash of the question stem and checks the licence.
  - Every imported question goes through the review queue.
- **Quality gates:** AI-generated questions pass answer-key checks and duplicate detection before they reach review.

### Database

- `source_documents` gains `sha256`, `storage_key`, `size_bytes`, `version`, `ocr_status` and `language`.
- `chunks` gains `tsv` (generated), `lang`, and in PR #7 `embedding` and `embedding_model`.
- New tables: `chunk_concepts` and `question_imports`. `questions` gains an indexed `stem_hash`.
- `CREATE EXTENSION vector` in PR #7. The compose and CI images already ship pgvector, and managed PostgreSQL on AWS RDS, Render and Railway supports it.

### API

| Endpoint | Purpose |
| --- | --- |
| `POST /admin/documents` | Upload; returns 202 and a job |
| `GET /admin/documents/{id}` | Document status |
| `DELETE /admin/documents/{id}` | Delete a document |
| `POST /admin/documents/{id}/reprocess` | Parse and index again |
| `GET /admin/documents/{id}/chunks` | Inspect chunks |
| `POST /admin/questions/import` | Start an import job |
| `GET /admin/imports/{id}` | Import status |
| `GET /admin/search` | Debug retrieval |

## 5. Pilot deployment: SSC CGL Quantitative Aptitude (PR #6)

### Content

- Lessons for all 7 concepts: levels 1–3 in English and level 1 in Telugu, each verified by a reviewer.
- At least 40 questions per concept, including licensed PYQs.
- One full mock and three sectional mocks.
- Sign-off from a content reviewer.

### Hosting

- **Web: Vercel.**
  - `API_URL` is a build-time environment variable in the Vercel project, because Next.js resolves rewrites at build time.
  - `/api/*` rewrites to the API, so the refresh cookie stays first-party.
  - Two things to check before launch:
    - The proxy timeout for long AI requests.
    - How the API learns learners' IPs behind Vercel. Vercel's egress IPs are not fixed, so trust a forwarded header only with a shared secret added in Next.js middleware.
- **API and worker: Render, Railway or AWS.**
  - Two services from the same image: `api` runs `uvicorn …` and `worker` runs `python -m app.worker`.
  - Migrations run as a release or pre-deploy command (`alembic upgrade head`), not on every replica.
- **Database:** managed PostgreSQL 16 with pgvector, automated backups and point-in-time recovery. A restore drill happens before launch.
- **Redis:** managed, for shared rate limits.
- **Images:** pushed to GHCR (or ECR) by a release workflow on tag push.
- **ECS migration path:** the same two images become one task definition with two services (`api`, `worker`) behind an ALB, using RDS and ElastiCache. Secrets move to Secrets Manager. No code changes are needed.
- **Monitoring:** Sentry for the API, worker and web; an uptime check on `/api/v1/health`; structured JSON logs; and an alert when the job queue's oldest queued job is older than 5 minutes.

### Pilot operations

- Invite-only registration (from PR #3), with only the pilot course published.
- A cohort of 20–50 learners.
- Feedback through the existing content flags, plus a feedback form.
- Metrics: D7 retention, plan completion and accuracy trend.
- Privacy policy and terms pages.

### Database and API

- An optional `events` table for product analytics.
- The existing `courses.status` controls visibility.
- New endpoints: `POST /feedback` and `GET /admin/metrics/pilot`.

## 6. Judge0 integration interface (PR #8, deployment deferred)

Deployment is deferred until the Python course launches; this PR builds the interface and tests only.

### Architecture

- **Interface:** `CodeRunner` (`run(code, tests) -> RunResult`) with three implementations: `local` (development only), `judge0` and `disabled`.
- **Judge0 adapter:**
  - Base64 encoding.
  - Explicit CPU, wall-clock, memory and file-size limits.
  - Maps Judge0 statuses to results: time limit, runtime error and compile error.
  - An `X-Auth-Token` header.
  - The language id comes from settings. The current code hard-codes `71`, which is Python 3.8 on Judge0 CE; pin a current version from `/languages` at deploy time.
  - A circuit breaker: when Judge0 is down, learners get a friendly error.
- **Contract tests** run against a fake Judge0 HTTP server, so the adapter is ready when a Judge0 VM (or the hosted API) is provisioned.
- **Rate limit:** per-user code-run limit, `EDU_RATE_LIMIT_CODE`.
- **Already in place:** hidden-test expected values never reach the sandbox; the parent process compares results.

### Database

An optional `code_runs` audit table (user, question, runner, status, duration).

### API

- No contract change.
- `/health` reports the runner's status.
- Settings: `EDU_JUDGE0_URL`, `EDU_JUDGE0_AUTH_TOKEN`, `EDU_JUDGE0_PYTHON_LANGUAGE_ID`.
