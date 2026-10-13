"""Application settings, loaded from environment variables (prefix EDU_).

Secrets (keys, passwords, the JWT secret) are `SecretStr`, so they never appear in logs, reprs or
error pages; read them with `reveal()`. Each can also come from a file named after its variable
in EDU_SECRETS_DIR (default /run/secrets, where Docker/Compose and most platforms mount secrets),
e.g. /run/secrets/EDU_ANTHROPIC_API_KEY. Environment variables win over files.
"""

import os
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Effort = Literal["", "low", "medium", "high", "xhigh", "max"]  # "" = the model's own default


def reveal(value: SecretStr | str | None) -> str:
    """The plain value of a secret setting (tests may set plain strings)."""
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value or ""


class TaskOverride(BaseModel):
    """Per-task AI settings (EDU_AI_TASK_OVERRIDES), e.g. {"examiner.evaluate": {"effort": "high"}}."""

    model_config = ConfigDict(extra="forbid")

    tier: Literal["heavy", "standard", "light"] | None = None
    effort: Effort | None = None
    max_tokens: int | None = Field(default=None, ge=100, le=64_000)
    prompt_cache: bool | None = None


class Settings(BaseSettings):
    # Reads the repo-root .env (shared with docker compose) and then apps/api/.env, which wins.
    model_config = SettingsConfigDict(env_prefix="EDU_", env_file=("../../.env", ".env"), extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    app_name: str = "EduVerse AI"
    api_prefix: str = "/api/v1"

    # Database: PostgreSQL in production, SQLite allowed for local/test runs.
    database_url: str = "sqlite:///./eduverse.db"

    # Auth
    secret_key: SecretStr = SecretStr("dev-only-change-me-please-32-bytes-min")
    bcrypt_rounds: int = 12  # tests lower this; never below 12 in production
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    # A spent refresh token replayed within this window (two tabs refreshing at once) gets a
    # fresh pair instead of revoking the session; later replays are treated as theft.
    refresh_reuse_grace_seconds: int = 20
    cors_origins: list[str] = ["http://localhost:3000"]
    cookie_secure: bool = False

    # First admin account, created by `python -m app.seed` when both are set.
    admin_email: str = ""
    admin_password: SecretStr = SecretStr("")

    # AI providers. Empty keys -> the offline provider is used. To rotate a key without downtime,
    # put the new one in the secondary slot, deploy, then swap and revoke the old one: a request
    # the primary key fails to authenticate is retried once with the secondary.
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_api_key_secondary: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    ai_primary: Literal["anthropic", "openai", "offline"] = "anthropic"
    ai_fallback: Literal["anthropic", "openai", "offline"] = "openai"
    anthropic_model_heavy: str = "claude-opus-5-5"
    anthropic_model_standard: str = "claude-sonnet-5-5"
    anthropic_model_light: str = "claude-haiku-5-5"
    openai_model_heavy: str = "gpt-4.1"
    openai_model_standard: str = "gpt-4.1-mini"
    openai_model_light: str = "gpt-4.1-mini"
    # Re-run declined requests server-side on Anthropic's recommended fallback model.
    anthropic_server_fallbacks: bool = True
    ai_timeout_seconds: float = 120.0
    # Thinking depth and spend per tier (Claude's `output_config.effort`). Opus 5.5 and Haiku 5.5
    # default to medium, Sonnet 5.5 to high; raise a tier only where the eval set shows it pays.
    anthropic_effort_heavy: Effort = "medium"
    anthropic_effort_standard: Effort = "medium"
    anthropic_effort_light: Effort = "low"
    # Cache each task's static system prompt (preamble + instructions + schema) on the provider.
    # Reads cost 0.05-0.1x input; a write costs 1.25x, so it pays when a task repeats within 5 min.
    ai_prompt_caching: bool = True
    # Constrain Claude's answer to the task's JSON schema (fewer repair round trips). A schema
    # the API rejects is retried once without it and then sent plain for that process's lifetime.
    ai_structured_outputs: bool = True
    ai_task_overrides: dict[str, TaskOverride] = {}
    # Limits. Per-user tokens per 24 h (input + cache writes + output; cache reads are nearly
    # free and not counted). The organisation-wide spend cap (USD per 24 h, 0 = none) switches
    # every AI feature to the offline engines when reached; admins get an email at the alert ratio.
    ai_daily_token_budget_learner: int = 200_000
    ai_daily_token_budget_staff: int = 5_000_000
    ai_daily_spend_cap_usd: float = 0.0
    ai_spend_alert_ratio: float = Field(default=0.8, gt=0, le=1)
    # Longest prompt (estimated tokens) sent to a provider; older chat turns are dropped first.
    ai_max_input_tokens: int = 30_000

    # Code runner: "local" runs Python in a resource-limited subprocess (dev only),
    # "judge0" calls an isolated Judge0 service, "disabled" turns execution off.
    code_runner: Literal["local", "judge0", "disabled"] = "local"
    judge0_url: str = ""
    code_timeout_seconds: float = 3.0

    # Background jobs. The API enqueues into the `jobs` table; workers (`python -m app.worker`)
    # claim and run them. With jobs_embedded_worker the API process also runs a worker thread,
    # which suits development, demos and single-instance deployments; set it to false when a
    # separate worker service runs (docker compose does).
    jobs_backend: Literal["database"] = "database"
    jobs_embedded_worker: bool = True
    jobs_poll_seconds: float = 5.0  # idle wait between checks (PostgreSQL wakes workers sooner)
    jobs_heartbeat_seconds: float = 15.0
    jobs_stale_after_seconds: float = 300.0  # no heartbeat for this long: the job is re-queued
    jobs_retry_base_seconds: float = 30.0  # first retry delay; doubles per attempt
    jobs_retention_days: int = 30  # finished jobs older than this are pruned
    jobs_health_file: str = ""  # touched by the worker loop, read by `--healthcheck`
    # Soft cap on jobs running at once per queue across all workers, e.g. {"content": 2} keeps
    # AI generation within provider rate limits and spend however many workers run.
    jobs_queue_concurrency: dict[str, int] = {}

    # Email (see app/core/mail.py). Production refuses the console backend.
    mail_backend: Literal["console", "smtp", "ses"] = "console"
    mail_from: str = "EduVerse AI <no-reply@eduverse.local>"  # with SES: a verified identity
    mail_reply_to: str = ""
    smtp_url: SecretStr = SecretStr("")  # smtp://user:pass@host:587 (STARTTLS) or smtps://user:pass@host:465
    ses_region: str = "ap-south-1"
    ses_configuration_set: str = ""  # optional: SES event publishing (bounces, complaints)
    mail_outbox_dir: str = ""  # console backend: also save each email here as JSON
    # Where learners open links from emails (reset, verify, invite). https:// in production.
    public_web_url: str = "http://localhost:3000"

    # Accounts. "invite" makes registration require an invite code from an admin.
    registration_mode: Literal["open", "invite"] = "open"
    password_reset_minutes: int = 30
    email_verify_hours: int = 48
    account_emails_per_hour: int = 3  # reset / verification emails per account per hour

    # Uploads
    upload_dir: str = "./uploads"
    max_upload_mb: int = 25

    # Rate limits (requests per minute). With a Redis URL the limits are shared by all API
    # replicas; without one each process counts on its own.
    redis_url: str = ""
    rate_limit_auth: int = 20
    rate_limit_ai: int = 30

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def check_production(s: Settings) -> None:
    """Refuse to start production with development defaults."""
    if not s.is_production:
        return
    if reveal(s.secret_key).startswith("dev-only"):
        raise RuntimeError("EDU_SECRET_KEY must be set in production")
    if s.bcrypt_rounds < 12:
        raise RuntimeError("EDU_BCRYPT_ROUNDS must be at least 12 in production")
    if s.code_runner == "local":
        raise RuntimeError("EDU_CODE_RUNNER=local is not allowed in production; use judge0 or disabled")
    if s.database_url.startswith("sqlite"):
        raise RuntimeError("EDU_DATABASE_URL must point to PostgreSQL in production")
    if s.mail_backend == "console":
        raise RuntimeError("EDU_MAIL_BACKEND must be ses or smtp in production (console only logs emails)")
    if "@eduverse.local" in s.mail_from:
        raise RuntimeError("EDU_MAIL_FROM must be a real sender address in production (with SES, a verified identity)")
    if s.mail_backend == "smtp" and not reveal(s.smtp_url):
        raise RuntimeError("EDU_SMTP_URL is required with EDU_MAIL_BACKEND=smtp")
    if not s.public_web_url.startswith("https://"):
        raise RuntimeError("EDU_PUBLIC_WEB_URL must be the site's https:// address in production")


def secrets_dir() -> str | None:
    path = os.environ.get("EDU_SECRETS_DIR", "/run/secrets")
    return path if path and os.path.isdir(path) else None


@lru_cache
def get_settings() -> Settings:
    s = Settings(_secrets_dir=secrets_dir())
    check_production(s)
    return s
