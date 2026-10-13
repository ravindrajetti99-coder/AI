# EduVerse AI — handoff for Claude Code

AI Learning Operating System (teacher, mentor, examiner, coding assistant, language partner, career guide).
Architecture doc: see the EduVerse AI architecture PDF (Phase 1). Owner: Ravindra (prefers Tenglish, brief updates).

## Decisions already made
- Monorepo: `apps/api` (Python 3.12+, FastAPI, SQLAlchemy 2, Pydantic v2, Alembic), `apps/web` (Next.js 16 + React 19 + Tailwind 4), `infra/`, `docs/`.
- Modular monolith; modules talk via `service.py`, never each other's tables.
- DB: PostgreSQL in prod (production refuses SQLite), SQLite allowed for dev/tests (`JSONType` = JSONB on Postgres). Dev auto-creates tables in `main.py` lifespan; prod runs `alembic upgrade head` (Docker entrypoint does it). Constraint naming convention lives on `Base.metadata`.
- Auth: bcrypt (sha256-prehashed), JWT access 15 min (carries `ver` = `users.token_version`; bumped on password reset/change so old access tokens die at once), rotating refresh tokens with reuse detection (20 s grace for concurrent tabs), httpOnly cookie + body token. Roles: learner, reviewer, admin. Web keeps the access token in memory only.
- Accounts: email verification + password reset via single-use hashed `account_tokens` (the `account.*` job creates the token and sends the email itself, so raw tokens never touch the jobs table); per-account 3 emails/hour; forgot-password always 202 (no enumeration). `EDU_REGISTRATION_MODE=invite` requires an `invites` code (hashed, shown once, optional email binding, learner|reviewer role, atomic use counting). Mail: `app/core/mail.py` `MailBackend` (console/smtp/ses via boto3 sesv2), `MailError(permanent=)`; generic `mail.send` job drops the body from the payload when done. Production refuses console mail and a non-https `EDU_PUBLIC_WEB_URL`.
- Web talks only to its own origin; Next.js rewrites `/api/*` → API. Rewrites are resolved at **build** time, so `API_URL` is a build arg.
- AI: `app/ai/gateway.py` is the only provider caller. Task = prompt + Pydantic schema + offline fallback (keep `Task.system` free of per-request data: it is prompt-cached). Primary Anthropic (`claude-opus-5-5` / `claude-sonnet-5-5` / `claude-haiku-5-5` by tier; `output_config.effort` per tier medium/medium/low; system prompt sent as one block with `cache_control`; structured outputs via `anthropic.transform_schema` with a one-time retry without the schema on 400; server-side refusal fallbacks except Haiku; refusal/max_tokens → ProviderError with request id and refusal category), fallback OpenAI, then deterministic offline engines. Response cache (`ai_cache`), JSON repair retry, per-task overrides (`EDU_AI_TASK_OVERRIDES`), per-user daily token budget (cache reads excluded), org-wide 24 h spend cap with an 80% admin email, prompt trimming (`fit_messages`), metering in `llm_calls` (cache read/write tokens, effort, request id, stop reason, refusal category, requested vs served model) priced by `PRICES` (cache reads/writes, Haiku long-context). Secrets are `SecretStr` (`config.reveal()`), also read from `EDU_SECRETS_DIR` files; `EDU_ANTHROPIC_API_KEY_SECONDARY` for rotation. Smoke check: `python -m app.ai.check` / `POST /admin/ai/check`; status: `GET /admin/ai/status`.
- Retrieval: BM25 over `chunks` (no embeddings yet); pgvector is the documented upgrade path.
- Learner model: Elo/IRT mastery (`learning/mastery.py`), revision ladder day 1/3/7/15/30, adaptive question choice targets ~70% success, prerequisite-gap detection, deterministic daily plan.
- Code runner: `labs/runner.py` local subprocess with rlimits + `unshare -n` (dev only; config refuses `local` in production), Judge0 adapter for prod. The child never sees expected values; the parent compares results.
- Rate limits: in-process sliding window, or Redis (`EDU_REDIS_URL`) shared by replicas with per-process fallback.
- Jobs: `app/jobs/` — PostgreSQL `jobs` table, enqueued in the caller's transaction (`jobs.service.enqueue`), claimed with `FOR UPDATE SKIP LOCKED` + compare-and-set, woken by `LISTEN/NOTIFY` (SQLite: in-process wake + polling). `QueueBackend` abstracts the transport for a later Redis move. Workers: `python -m app.worker` (compose `worker` service) or a thread in the API (`EDU_JOBS_EMBEDDED_WORKER`, default true; compose sets false). Per-claim lease token fences every write; heartbeats + reaper recover dead workers' jobs; AppError/PermanentJobError fail at once, other errors retry with backoff; handlers call `ctx.save()` per unit of work (checkpoint commits with the content), so retries never redo finished items; cancel stops at the next checkpoint; SIGTERM hands the job back without using an attempt. Handlers register with `@registry.handler(kind, queue=...)` and must be listed in `registry.HANDLER_MODULES`. Generation handlers: `modules/ingest/jobs.py`; periodic `maintenance.prune` hourly.
- Seed: `python -m app.seed` upserts by stable keys (`Question.external_key`), retires removed questions, validates answer keys, bootstraps the admin from `EDU_ADMIN_EMAIL`/`EDU_ADMIN_PASSWORD`, builds one mock per course. Quant/physics/accounting drills come from parametric generators (`seed/generators.py`).

## Status (Phases 2-4 done; Phase 2 plan approved, see `docs/phase-2-plan.md`)
- Seed loader + 6 courses: SSC quant, Class 10 Electricity, CA Foundation Depreciation, Python, Spoken English (Telugu), Interview Skills (reuses the self-introduction concept).
- API: 244 pytest tests, passing on SQLite and on PostgreSQL 16 (`EDU_TEST_POSTGRES_URL`), plus migration drift check. Provider adapters are also tested through the real Anthropic/OpenAI SDKs over a mock HTTP transport. Bugs found by the suite are fixed (see commit "Add pytest suite and fix the bugs it found").
- Alembic `0001_initial_schema` (36 tables), `0002_jobs_queue` (`jobs` replaces `generation_jobs`, data copied both ways) and `0003_account_access` (`account_tokens`, `invites`, `users.email_verified_at`/`token_version`) and `0004_ai_metering` (llm_calls metering columns), verified on PostgreSQL 16.
- Phase 2 PR #2 (job queue + worker) on branch `claude/phase-2-job-queue`, stacked on PR #1; PR #3 (SES mail, password reset, email verification, invites) on `claude/phase-2-account-access`, stacked on PR #2; PR #4 (production AI configuration) on `claude/phase-2-ai-config`, stacked on PR #3.
- Web: all learner pages + staff content studio (incl. Invites tab), forgot/reset/verify-email pages; lint/typecheck/build clean; 10 Playwright e2e tests pass against a seeded API + production build (emails read from `EDU_MAIL_OUTBOX_DIR`).
- Docker images for api and web build and run (verified in production mode against Postgres + Redis); `infra/docker-compose.yml`; `.env.example`; GitHub Actions CI; README.
- Not yet run: the full `docker compose up` (sandbox had no Docker Hub pulls), and any live AI provider calls (no keys here; adapters are unit-tested with stubs).

## Next steps (Phase 2, approved; details and decisions in `docs/phase-2-plan.md`, one PR each)
1. With API keys: run `python -m app.ai.check --live`, then build a small eval set per engine (lesson, questions, examiner, tutor) before tuning effort or prompts.
2. PR #5: content ingestion: async `ingest.document` jobs, S3 storage, PostgreSQL full-text search, PYQ importer.
3. PR #6: pilot deployment of SSC CGL Quant: web on Vercel, API + worker on Render/Railway/AWS, managed PostgreSQL; keep the ECS path.
4. PR #7: bge-m3 embeddings (provider interface) + hybrid retrieval. PR #8: Judge0 integration interface only (deploy when the Python course launches).
5. Still to do once: `docker compose up` on a real machine; observability (structured logs, Sentry, queue-age alert).

## Commands
```
# API
cd apps/api
pip install -e ".[dev]"
python -m app.seed                                  # idempotent; --only <slug>, --no-tests
EDU_ENV=development uvicorn app.main:app --reload   # docs at /api/v1/docs; runs jobs in-process by default
python -m app.worker                                # job worker (--queues a,b; --once; --healthcheck)
python -m app.ai.check                              # AI keys/models smoke check (--live, --require)
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
