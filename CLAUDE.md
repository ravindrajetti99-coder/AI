# EduVerse AI — handoff for Claude Code

AI Learning Operating System (teacher, mentor, examiner, coding assistant, language partner, career guide).
Architecture doc: see the EduVerse AI architecture PDF (Phase 1). Owner: Ravindra (prefers Tenglish, brief updates).

## Decisions already made
- Monorepo: `apps/api` (Python 3.12+, FastAPI, SQLAlchemy 2, Pydantic v2), `apps/web` (Next.js + Tailwind, NOT started), `infra/`, `docs/`.
- Modular monolith; modules talk via `service.py`, never each other's tables.
- DB: PostgreSQL in prod, SQLite allowed for tests (`JSONType` = JSONB on Postgres). Dev auto-creates tables in `main.py` lifespan; prod must use Alembic (NOT set up yet).
- Auth: bcrypt (sha256-prehashed), JWT access 15 min, rotating refresh tokens with reuse detection, httpOnly cookie + body token. Roles: learner, reviewer, admin.
- AI: `app/ai/gateway.py` is the only provider caller. Task = prompt + Pydantic schema + offline fallback. Primary Anthropic (`claude-opus-5-5` / `claude-sonnet-5-5` / `claude-haiku-5-5` by tier), fallback OpenAI, then deterministic offline engines so the app works with no API keys. Cache, JSON repair retry, per-user daily token budget, metering in `llm_calls`.
- Retrieval: BM25 over `chunks` (no embeddings yet); pgvector is the documented upgrade path.
- Learner model: Elo/IRT mastery (`learning/mastery.py`), revision ladder day 1/3/7/15/30, adaptive question choice targets ~70% success, prerequisite-gap detection, deterministic daily plan.
- Code runner: `labs/runner.py` local subprocess with rlimits + `unshare -n` (dev only; config refuses `local` in production), Judge0 adapter for prod.
- Seed questions for quant/physics/accounting come from parametric generators (`seed/generators.py`) so answer keys are correct by construction.

## Status (stopped mid Phase 2-4)
Done (written, lint-clean, imports OK, NOT yet tested):
- `app/core/*` config, db, security, deps (rate limiter), errors
- Models for all modules (36 tables)
- Routers: identity (auth/me/admin users), catalog, content (lessons, flashcards, notes, tutor ask, flags), assessment (practice/next, steps, attempts, code run, tests start/answer/submit), learning (enroll, dashboard, progress, plan, mentor, reviews, lesson progress, language chat, speaking items, career), admin (uploads, generation jobs, review queue, decisions, questions, flags, ai-usage, stats)
- AI engines: teacher (lesson/tutor/flashcards/notes), questions (+cloze offline), examiner (rubric coverage offline), code_review (AST offline), language (Indian-English error rules offline), mentor/career
- Seed data written: `seed/generators.py`, `seed/helpers.py`, `seed/courses/ssc_quant.py`, `python_basics.py`, `spoken_english.py`

## Next steps (in order)
1. `seed/loader.py`: idempotent upsert of exam profiles, courses, tree, concepts, prereq edges, lessons, flashcards, questions (generators via `random.Random(slug)`, `extra`/`questions` lists), rubrics; admin bootstrap from `EDU_ADMIN_EMAIL`/`EDU_ADMIN_PASSWORD`; build one mock test per course with `ingest.service.build_mock_test`. CLI: `python -m app.seed`.
2. Remaining seed courses: Class 10 Physics Electricity (generators ohms_law, resistance_combo, electric_power + descriptive with rubric), CA Foundation Depreciation (depreciation_slm/wdv), Interview Skills (career domain).
3. pytest suite (`apps/api/tests`, SQLite via `EDU_DATABASE_URL`, `EDU_ENV=test`): scoring, mastery maths, auth + refresh reuse, catalog, practice → attempt → mastery → review, test submit with negative marking, grading of coding/speaking/descriptive (offline), gateway with a fake provider (cache, repair, fallback, budget), ingestion + generation jobs + review approve. Fix bugs found.
4. Alembic init + first migration; verify on real PostgreSQL.
5. `apps/web`: Next.js app (rewrites `/api/*` → API): login/register, dashboard, catalog, course tree, lesson viewer (levels 1-4, Mermaid, en/te), practice with step-by-step hints, mock tests, reviews, code lab, language lab (Web Speech API → speaking attempts), career guide, admin panel.
6. Dockerfiles, `infra/docker-compose.yml` (postgres+pgvector, redis, api, web), `.env.example`, GitHub Actions CI, README.

## Commands
```
cd apps/api
pip install fastapi "sqlalchemy>=2" pydantic-settings bcrypt PyJWT email-validator python-multipart pypdf anthropic openai "psycopg[binary]" httpx pytest ruff
EDU_ENV=development uvicorn app.main:app --reload   # docs at /api/v1/docs
ruff check app && ruff format app
```
