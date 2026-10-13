# EduVerse AI

An AI learning operating system: one platform that acts as **teacher, mentor, examiner, coding assistant, language partner and career guide**, for competitive exams (SSC), school boards (CBSE), professional courses (CA Foundation), programming (Python), spoken English for Telugu speakers, and job interviews.

It works **with or without AI keys**. Every AI feature has a deterministic offline engine, so the whole product runs locally with no API key; add an Anthropic (and/or OpenAI) key to switch the same features to live models.

## What it does

| Role | How |
| --- | --- |
| Teacher | Every concept at 4 levels (beginner → expert), English and Telugu, Mermaid diagrams, examples, common mistakes, memory techniques, check questions, flashcards, and a tutor chat grounded in the lesson on screen. |
| Mentor | Elo/IRT-style mastery per concept, prerequisite-gap detection, a daily plan that fits the learner's minutes, and spaced revision on days 3 → 7 → 15 → 30. |
| Examiner | Adaptive practice aimed at ~70% success, 6-step progressive hints, timed mock tests with the exam's marking scheme (e.g. SSC +2/−0.5), and rubric scoring of written and interview answers. |
| Coding assistant | Python in the browser, visible examples plus hidden tests, and a code review (quality, performance, security). |
| Language partner | Conversation practice with corrections tuned to Indian-English errors, and pronunciation drills scored from the microphone (Web Speech API). |
| Career guide | Realistic paths for a stated goal, mapped to platform courses. |

Accounts have email verification, password reset by email, password change (which signs out every other device) and an **invite-only mode** for the beta, with invite codes managed in the content studio. Email goes through Amazon SES, SMTP, or (in development) the console.

Staff get a **content studio**: upload source PDFs, generate lessons/questions/flashcards/notes/mock tests with AI, and approve or edit every AI draft before learners see it. AI usage, cost and cache hits are metered per feature.

## Architecture

```
apps/api   FastAPI · SQLAlchemy 2 · Pydantic v2 · Alembic     (Python 3.12+)
apps/web   Next.js 16 · React 19 · Tailwind 4                 (Node 22)
infra/     docker-compose: PostgreSQL 16 + pgvector, Redis, api, worker, web
docs/      plans (docs/phase-2-plan.md)
```

- **Modular monolith.** `identity`, `catalog`, `content`, `assessment`, `learning`, `ingest`, `admin`, `labs`. Modules call each other's `service.py`, never each other's tables.
- **AI gateway** (`app/ai/gateway.py`) is the only code that calls model providers. A task is a prompt, a Pydantic output schema and an offline fallback. The gateway handles caching, provider fallback (Anthropic → OpenAI → offline), one JSON-repair retry, per-user daily token budgets, refusal handling and metering into `llm_calls`.
- **Background jobs** (`app/jobs/`) live in a PostgreSQL `jobs` table. The API enqueues in the same transaction as the change that caused the job; workers (`python -m app.worker`) claim with `SELECT … FOR UPDATE SKIP LOCKED` and are woken by `LISTEN/NOTIFY`. Heartbeats let any worker recover jobs from a dead one, transient errors retry with backoff, and handlers save checkpoints, so a retried AI job never regenerates (or pays for) finished work. Staff can cancel and retry jobs from the content studio.
- **Retrieval** is BM25 over chunks of uploaded documents; pgvector is the documented upgrade path.
- **Web → API.** The browser only talks to the web origin, and Next.js rewrites `/api/*` to the API, so the httpOnly refresh cookie stays first-party. Access tokens live in memory only (15 min); refresh tokens rotate with reuse detection.

## Quick start (Docker)

```bash
cp .env.example .env          # set EDU_ADMIN_PASSWORD; add AI keys if you have them
docker compose --env-file .env -f infra/docker-compose.yml up --build
```

Open http://localhost:3000. Sign in with `EDU_ADMIN_EMAIL` / `EDU_ADMIN_PASSWORD` for the content studio, or register as a learner. The API container runs `alembic upgrade head` and (with `SEED_ON_START=true`) loads the seed courses on start; the `worker` container runs generation jobs (add more with `--scale worker=3`). API docs are at http://localhost:8000/api/v1/docs.

## Local development

```bash
# API (SQLite by default; tables auto-created in development)
cd apps/api
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
EDU_ADMIN_EMAIL=admin@example.com EDU_ADMIN_PASSWORD=change-me-long-password python -m app.seed
uvicorn app.main:app --reload                 # http://localhost:8000/api/v1/docs

# Web (in another terminal)
cd apps/web
npm install
npm run dev                                   # http://localhost:3000 (proxies /api to :8000)
```

`python -m app.seed` is idempotent: re-run it after editing anything in `app/seed/`. It upserts by stable keys, retires removed questions and never resets passwords. Use `--only <course-slug>` to load one course.

Exam courses are kept as syllabus data (YAML) under `app/seed/syllabus/data/`: the complete SSC CGL course (Tier 1 and Tier 2, five subjects) loads as a staff-only draft whose content is generated once, reviewed and then served to every learner. `python -m app.seed.syllabus` validates the files without a database. See [docs/content-engine.md](docs/content-engine.md).

In development the API runs background jobs itself (`EDU_JOBS_EMBEDDED_WORKER=true`, the default). To run them the way production does, set it to `false` and start a worker:

```bash
cd apps/api
python -m app.worker                          # all queues; or --queues content,maintenance
python -m app.worker --once                   # run whatever is due, then exit
```

## Tests

```bash
cd apps/api && pytest                         # 244 tests, SQLite, offline AI (~20 s)
EDU_TEST_POSTGRES_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres pytest
                                              # same suite on PostgreSQL, schema from migrations
cd apps/web && npm run lint && npm run typecheck && npm run build
cd apps/web && npx playwright test            # 10 browser tests against a seeded API + production build
```

CI (`.github/workflows/ci.yml`) runs all of the above, checks that migrations match the models, and builds both Docker images.

## Database migrations

Production never auto-creates tables. After changing a model:

```bash
cd apps/api
alembic revision --autogenerate -m "describe the change"   # then read the generated file
alembic upgrade head
alembic check                                               # fails if models and migrations differ
```

A development database created by auto-create (no `alembic_version` table) can be adopted with `alembic stamp head`.

## Configuration

All API settings are environment variables prefixed `EDU_` (see `.env.example` and `apps/api/app/core/config.py`). Notable ones:

| Variable | Default | Notes |
| --- | --- | --- |
| `EDU_ENV` | `development` | `production` refuses the dev secret key, SQLite, the local code runner and bcrypt cost < 12. |
| `EDU_DATABASE_URL` | `sqlite:///./eduverse.db` | Must be PostgreSQL in production: `postgresql+psycopg://…` |
| `EDU_REDIS_URL` | empty | Shared rate limits across API replicas; without it each process counts alone. |
| `EDU_ANTHROPIC_API_KEY` / `EDU_OPENAI_API_KEY` | empty | Empty means offline engines. Models per tier: `claude-opus-5-5` / `claude-sonnet-5-5` / `claude-haiku-5-5`. Prefer a secrets file (see below). `EDU_ANTHROPIC_API_KEY_SECONDARY` takes over when the primary is rejected, for rotation. |
| `EDU_ANTHROPIC_EFFORT_HEAVY` / `_STANDARD` / `_LIGHT` | `medium` / `medium` / `low` | Thinking depth per tier (`low` … `max`). |
| `EDU_AI_PROMPT_CACHING` / `EDU_AI_STRUCTURED_OUTPUTS` | `true` / `true` | Cache each task's static system prompt; constrain answers to the task's JSON schema. |
| `EDU_AI_TASK_OVERRIDES` | `{}` | Per task: `{"examiner.evaluate": {"effort": "high", "max_tokens": 3000}}` (tier, effort, max_tokens, prompt_cache). |
| `EDU_AI_DAILY_SPEND_CAP_USD` | `0` (none) | Organisation-wide USD per 24 h; at the cap AI answers come from the offline engines, and admins get an email at 80%. |
| `EDU_ANTHROPIC_SERVER_FALLBACKS` | `true` | On a safety decline, Anthropic re-runs the request on its recommended fallback model. |
| `EDU_MAIL_BACKEND` | `console` | `ses` (Amazon SES, `EDU_SES_REGION`, AWS credentials from the standard chain) or `smtp` (`EDU_SMTP_URL`). Production refuses `console`. |
| `EDU_MAIL_FROM` | `EduVerse AI <no-reply@eduverse.local>` | With SES, a verified identity (domain with DKIM/SPF/DMARC). |
| `EDU_PUBLIC_WEB_URL` | `http://localhost:3000` | Base of the links in emails; must be `https://` in production. |
| `EDU_REGISTRATION_MODE` | `open` | `invite`: sign-up needs an invite code (admins create them under Content studio → Invites). |
| `EDU_JOBS_EMBEDDED_WORKER` | `true` | The API process also runs a job worker. Set `false` when a separate `python -m app.worker` service runs (docker compose does). |
| `EDU_JOBS_STALE_AFTER_SECONDS` | `300` | A running job whose worker has not heart-beaten for this long is retried by another worker. |
| `EDU_CODE_RUNNER` | `local` | `local` is a resource-limited subprocess for development only; use `judge0` (with `EDU_JUDGE0_URL`) or `disabled` in production. |
| `EDU_ADMIN_EMAIL` / `EDU_ADMIN_PASSWORD` | empty | First admin, created by the seed loader. |

## AI in production

- **Secrets.** Every key and password is a `SecretStr` (never in logs, reprs or errors). Each can also be read from a file named after its variable in `EDU_SECRETS_DIR` (default `/run/secrets`), e.g. `/run/secrets/EDU_ANTHROPIC_API_KEY`, which is where Docker/Compose secrets land; platforms such as Render, Railway and ECS (Secrets Manager) can inject them as variables instead. A variable that is set, even empty, wins over the file.
- **Rotation.** Put the new key in `EDU_ANTHROPIC_API_KEY_SECONDARY`, deploy, then make it the primary and revoke the old one. A request the primary key fails to authenticate is retried once with the secondary.
- **Smoke check.** `python -m app.ai.check` proves each provider's key and each tier's model with free calls (Anthropic token counting); `--live` sends one tiny real request per tier; `--require` fails when no provider is configured. Admins can run the same check from Content studio → AI usage, which also shows the configuration, 24-hour spend against the cap, prompt-cache hit ratio, refusals and fallbacks.
- **Cost tracking.** `llm_calls` records input, output, cache-read and cache-write tokens, effort, the provider's request id, stop reason, refusal category, and the requested versus serving model (server-side fallbacks); cost uses per-model prices, including cache pricing and Haiku's long-context rate.

## Security notes

- Passwords: bcrypt over a SHA-256 prehash. Refresh tokens are stored hashed, rotate on every use, and a replay outside a 20-second grace window revokes the whole session family.
- Password-reset and email-verification links carry single-use random tokens; only their SHA-256 is stored, and they never pass through the jobs table (the worker creates the token and sends the email in one step). Reset links last 30 minutes, at most 3 emails per account per hour, and "forgot password" answers the same for unknown addresses. A reset or password change revokes every refresh token and bumps the user's token version, so old access tokens stop working at once. Invite codes are stored hashed too and shown once.
- Learner code never sees hidden test expectations. The runner compares results in the parent process, so a forged report cannot pass hidden tests. The local runner adds CPU, memory and file-size limits and no network (when user namespaces are available), but it is not a sandbox: production needs Judge0 or another isolated runner.
- Uploaded sources are fenced as data in prompts, and AI drafts are invisible to learners until a reviewer approves them.
- The API trusts `X-Forwarded-For` only from `FORWARDED_ALLOW_IPS`. Keep the API port private and expose only the web app (or your own reverse proxy).

## Repository layout

```
apps/api/app/core         config, db, security, deps (auth, rate limits), errors
apps/api/app/jobs         job queue: model, queue backend, worker, maintenance jobs
apps/api/app/worker.py    `python -m app.worker`
apps/api/app/modules      identity, catalog, content, assessment, learning, ingest, admin, labs
apps/api/app/ai           gateway, providers, retrieval, engines (teacher, questions, examiner,
                          code_review, language, mentor/career)
apps/api/app/seed         seed loader, parametric generators, 6 seed courses, syllabus/ (exam
                          courses as YAML: SSC CGL)
apps/api/migrations       Alembic migrations
apps/web/app              Next.js routes (dashboard, courses, learn, practice, tests, reviews,
                          lab/code, lab/language, career, profile, admin)
apps/web/components       UI kit, question renderer, practice session, lesson view
apps/web/e2e              Playwright tests
infra/                    docker-compose.yml
docs/                     phase-2-plan.md, content-engine.md
```
