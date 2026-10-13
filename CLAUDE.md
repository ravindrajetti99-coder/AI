# EduVerse AI — handoff for Claude Code

AI Learning Operating System (teacher, mentor, examiner, coding assistant, language partner, career guide).
Architecture doc: see the EduVerse AI architecture PDF (Phase 1). Owner: Ravindra (prefers Tenglish, brief updates).

## Decisions already made
- Monorepo: `apps/api` (Python 3.12+, FastAPI, SQLAlchemy 2, Pydantic v2, Alembic), `apps/web` (Next.js 16 + React 19 + Tailwind 4), `infra/`, `docs/`.
- Modular monolith; modules talk via `service.py`, never each other's tables.
- DB: PostgreSQL in prod, SQLite allowed for tests (`JSONType` = JSONB on Postgres). Dev auto-creates tables in `main.py` lifespan; prod runs `alembic upgrade head` (Docker entrypoint does it). Constraint naming convention lives on `Base.metadata`.
- Auth: bcrypt (sha256-prehashed), JWT access 15 min, rotating refresh tokens with reuse detection (20 s grace for concurrent tabs), httpOnly cookie + body token. Roles: learner, reviewer, admin. Web keeps the access token in memory only.
- Web talks only to its own origin; Next.js rewrites `/api/*` → API. Rewrites are resolved at **build** time, so `API_URL` is a build arg.
- AI: `app/ai/gateway.py` is the only provider caller. Task = prompt + Pydantic schema + offline fallback. Primary Anthropic (`claude-opus-5-5` / `claude-sonnet-5-5` / `claude-haiku-5-5` by tier, server-side refusal fallbacks except Haiku, refusal/max_tokens → ProviderError), fallback OpenAI, then deterministic offline engines. Cache, JSON repair retry, per-user daily token budget, metering in `llm_calls` (per-model prices in `PRICE_PER_MTOK`).
- Retrieval: BM25 over `chunks` (no embeddings yet); pgvector is the documented upgrade path.
- Learner model: Elo/IRT mastery (`learning/mastery.py`), revision ladder day 1/3/7/15/30, adaptive question choice targets ~70% success, prerequisite-gap detection, deterministic daily plan.
- Code runner: `labs/runner.py` local subprocess with rlimits + `unshare -n` (dev only; config refuses `local` in production), Judge0 adapter for prod. The child never sees expected values; the parent compares results.
- Rate limits: in-process sliding window, or Redis (`EDU_REDIS_URL`) shared by replicas with per-process fallback.
- Seed: `python -m app.seed` upserts by stable keys (`Question.external_key`), retires removed questions, validates answer keys, bootstraps the admin from `EDU_ADMIN_EMAIL`/`EDU_ADMIN_PASSWORD`, builds one mock per course. Quant/physics/accounting drills come from parametric generators (`seed/generators.py`).

## Status (Phases 2-4 done; see git log)
- Seed loader + 6 courses: SSC quant, Class 10 Electricity, CA Foundation Depreciation, Python, Spoken English (Telugu), Interview Skills (reuses the self-introduction concept).
- API: 143 pytest tests, passing on SQLite and on PostgreSQL 16 (`EDU_TEST_POSTGRES_URL`), plus migration drift check. Bugs found by the suite are fixed (see commit "Add pytest suite and fix the bugs it found").
- Alembic `0001_initial_schema` (36 tables), verified on PostgreSQL 16.
- Web: all learner pages + staff content studio; lint/typecheck/build clean; 7 Playwright e2e tests pass against a seeded API + production build.
- Docker images for api and web build and run (verified in production mode against Postgres + Redis); `infra/docker-compose.yml`; `.env.example`; GitHub Actions CI; README.
- Not yet run: the full `docker compose up` (sandbox had no Docker Hub pulls), and any live AI provider calls (no keys here; adapters are unit-tested with stubs).

## Next steps (suggested order)
1. Run CI on GitHub and `docker compose up` once on a real machine; fix anything environment-specific.
2. Account basics: email verification and password reset (no endpoints yet).
3. Move generation jobs from FastAPI `BackgroundTasks` to a Redis-backed worker (Arq/RQ) so long AI jobs survive restarts.
4. Production code runner: Judge0 service (compose profile) and `EDU_CODE_RUNNER=judge0`.
5. With API keys: try every AI task live, tune prompts, and add a small eval set per engine (lesson, questions, examiner, tutor).
6. pgvector embeddings + BM25 hybrid retrieval; PYQ (previous-year question) import tooling; more courses and Telugu lessons; Telugu UI strings.
7. Observability: structured logs, error tracking, request metrics.

## Commands
```
# API
cd apps/api
pip install -e ".[dev]"
python -m app.seed                                  # idempotent; --only <slug>, --no-tests
EDU_ENV=development uvicorn app.main:app --reload   # docs at /api/v1/docs
pytest                                              # SQLite; EDU_TEST_POSTGRES_URL=... for PostgreSQL
ruff check app tests && ruff format app tests
alembic revision --autogenerate -m "..." && alembic upgrade head && alembic check

# Web
cd apps/web
npm install && npm run dev                          # proxies /api to API_URL (default http://localhost:8000)
npm run lint && npm run typecheck && npm run build
npx playwright test                                 # needs python with the API installed (PYTHON=...)

# Everything
docker compose --env-file .env -f infra/docker-compose.yml up --build
```
