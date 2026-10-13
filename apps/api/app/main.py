"""EduVerse AI API entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import models  # noqa: F401  (registers all tables)
from app.ai import gateway
from app.core.config import get_settings
from app.core.db import Base, SessionLocal, engine
from app.core.errors import install_error_handlers
from app.jobs.worker import start_embedded
from app.modules.admin.router import router as admin_router
from app.modules.assessment.pyq_router import router as pyq_router
from app.modules.assessment.router import router as assessment_router
from app.modules.catalog.router import router as catalog_router
from app.modules.content.router import router as content_router
from app.modules.identity.router import router as identity_router
from app.modules.learning.router import router as learning_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    if not s.is_production:
        # Dev/test convenience. Production runs `alembic upgrade head` before starting.
        Base.metadata.create_all(engine)
    embedded = start_embedded() if s.jobs_embedded_worker else None
    yield
    if embedded:
        worker, thread = embedded
        worker.stop()  # a running job goes back to the queue at its next checkpoint
        thread.join(timeout=10)


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title=s.app_name,
        version="0.1.0",
        description="AI Learning Operating System: teacher, mentor, examiner, coding assistant, language partner, career guide.",
        lifespan=lifespan,
        docs_url=f"{s.api_prefix}/docs",
        openapi_url=f"{s.api_prefix}/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    install_error_handlers(app)
    for r in (identity_router, catalog_router, content_router, assessment_router, learning_router, admin_router, pyq_router):
        app.include_router(r, prefix=s.api_prefix)

    @app.get(f"{s.api_prefix}/health", tags=["ops"])
    def health():
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok", "ai": gateway.ai_status(), "env": s.env}

    return app


app = create_app()
