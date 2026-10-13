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

Staff get a **content studio**: upload source PDFs, generate lessons/questions/flashcards/notes/mock tests with AI, and approve or edit every AI draft before learners see it. AI usage, cost and cache hits are metered per feature.

## Architecture

```
apps/api   FastAPI · SQLAlchemy 2 · Pydantic v2 · Alembic     (Python 3.12+)
apps/web   Next.js 16 · React 19 · Tailwind 4                 (Node 22)
infra/     docker-compose: PostgreSQL 16 + pgvector, Redis, api, web
```

- **Modular monolith.** `identity`, `catalog`, `content`, `assessment`, `learning`, `ingest`, `admin`, `labs`. Modules call each other's `service.py`, never each other's tables.
- **AI gateway** (`app/ai/gateway.py`) is the only code that calls model providers. A task is a prompt, a Pydantic output schema and an offline fallback. The gateway handles caching, provider fallback (Anthropic → OpenAI → offline), one JSON-repair retry, per-user daily token budgets, refusal handling and metering into `llm_calls`.
- **Retrieval** is BM25 over chunks of uploaded documents; pgvector is the documented upgrade path.
- **Web → API.** The browser only talks to the web origin, and Next.js rewrites `/api/*` to the API, so the httpOnly refresh cookie stays first-party. Access tokens live in memory only (15 min); refresh tokens rotate with reuse detection.

## Quick start (Docker)

```bash
cp .env.example .env          # set EDU_ADMIN_PASSWORD; add AI keys if you have them
docker compose --env-file .env -f infra/docker-compose.yml up --build
```

Open http://localhost:3000. Sign in with `EDU_ADMIN_EMAIL` / `EDU_ADMIN_PASSWORD` for the content studio, or register as a learner. The API container runs `alembic upgrade head` and (with `SEED_ON_START=true`) loads the seed courses on start. API docs are at http://localhost:8000/api/v1/docs.

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

## Tests

```bash
cd apps/api && pytest                         # 143 tests, SQLite, offline AI (~15 s)
EDU_TEST_POSTGRES_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres pytest
                                              # same suite on PostgreSQL, schema from migrations
cd apps/web && npm run lint && npm run typecheck && npm run build
cd apps/web && npx playwright test            # 7 browser tests against a seeded API + production build
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
| `EDU_ENV` | `development` | `production` refuses the dev secret key, the local code runner and bcrypt cost < 12. |
| `EDU_DATABASE_URL` | `sqlite:///./eduverse.db` | PostgreSQL in production: `postgresql+psycopg://…` |
| `EDU_REDIS_URL` | empty | Shared rate limits across API replicas; without it each process counts alone. |
| `EDU_ANTHROPIC_API_KEY` / `EDU_OPENAI_API_KEY` | empty | Empty means offline engines. Models per tier: `claude-opus-5-5` / `claude-sonnet-5-5` / `claude-haiku-5-5`. |
| `EDU_ANTHROPIC_SERVER_FALLBACKS` | `true` | On a safety decline, Anthropic re-runs the request on its recommended fallback model. |
| `EDU_CODE_RUNNER` | `local` | `local` is a resource-limited subprocess for development only; use `judge0` (with `EDU_JUDGE0_URL`) or `disabled` in production. |
| `EDU_ADMIN_EMAIL` / `EDU_ADMIN_PASSWORD` | empty | First admin, created by the seed loader. |

## Security notes

- Passwords: bcrypt over a SHA-256 prehash. Refresh tokens are stored hashed, rotate on every use, and a replay outside a 20-second grace window revokes the whole session family.
- Learner code never sees hidden test expectations. The runner compares results in the parent process, so a forged report cannot pass hidden tests. The local runner adds CPU, memory and file-size limits and no network (when user namespaces are available), but it is not a sandbox: production needs Judge0 or another isolated runner.
- Uploaded sources are fenced as data in prompts, and AI drafts are invisible to learners until a reviewer approves them.
- The API trusts `X-Forwarded-For` only from `FORWARDED_ALLOW_IPS`. Keep the API port private and expose only the web app (or your own reverse proxy).

## Repository layout

```
apps/api/app/core         config, db, security, deps (auth, rate limits), errors
apps/api/app/modules      identity, catalog, content, assessment, learning, ingest, admin, labs
apps/api/app/ai           gateway, providers, retrieval, engines (teacher, questions, examiner,
                          code_review, language, mentor/career)
apps/api/app/seed         seed loader, parametric generators, 6 seed courses
apps/api/migrations       Alembic migrations
apps/web/app              Next.js routes (dashboard, courses, learn, practice, tests, reviews,
                          lab/code, lab/language, career, profile, admin)
apps/web/components       UI kit, question renderer, practice session, lesson view
apps/web/e2e              Playwright tests
infra/                    docker-compose.yml
```
