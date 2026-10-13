"""Application settings, loaded from environment variables (prefix EDU_)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EDU_", env_file=".env", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    app_name: str = "EduVerse AI"
    api_prefix: str = "/api/v1"

    # Database: PostgreSQL in production, SQLite allowed for local/test runs.
    database_url: str = "sqlite:///./eduverse.db"

    # Auth
    secret_key: str = "dev-only-change-me-please-32-bytes-min"
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
    admin_password: str = ""

    # AI providers. Empty keys -> the offline provider is used.
    anthropic_api_key: str = ""
    openai_api_key: str = ""
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
    ai_daily_token_budget_learner: int = 200_000
    ai_daily_token_budget_staff: int = 5_000_000

    # Code runner: "local" runs Python in a resource-limited subprocess (dev only),
    # "judge0" calls an isolated Judge0 service, "disabled" turns execution off.
    code_runner: Literal["local", "judge0", "disabled"] = "local"
    judge0_url: str = ""
    code_timeout_seconds: float = 3.0

    # Uploads
    upload_dir: str = "./uploads"
    max_upload_mb: int = 25

    # Rate limits (requests per minute)
    rate_limit_auth: int = 20
    rate_limit_ai: int = 30

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production:
        if s.secret_key.startswith("dev-only"):
            raise RuntimeError("EDU_SECRET_KEY must be set in production")
        if s.bcrypt_rounds < 12:
            raise RuntimeError("EDU_BCRYPT_ROUNDS must be at least 12 in production")
        if s.code_runner == "local":
            raise RuntimeError("EDU_CODE_RUNNER=local is not allowed in production; use judge0 or disabled")
    return s
