"""Production refuses development defaults."""

import pytest

from app.core.config import Settings, check_production

SAFE = {
    "env": "production",
    "secret_key": "a-real-secret-key-0123456789-abcdefghijkl",
    "code_runner": "disabled",
    "database_url": "postgresql+psycopg://u:p@db/eduverse",
    "bcrypt_rounds": 12,
    "mail_backend": "ses",
    "mail_from": "EduVerse AI <no-reply@learn.example.com>",
    "public_web_url": "https://learn.example.com",
}


def test_safe_production_settings_pass():
    check_production(Settings(**SAFE))


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"secret_key": "dev-only-change-me-please-32-bytes-min"}, "EDU_SECRET_KEY"),
        ({"bcrypt_rounds": 4}, "EDU_BCRYPT_ROUNDS"),
        ({"code_runner": "local"}, "EDU_CODE_RUNNER"),
        ({"database_url": "sqlite:////app/data/eduverse.db"}, "EDU_DATABASE_URL"),
        ({"mail_backend": "console"}, "EDU_MAIL_BACKEND"),
        ({"mail_from": "EduVerse AI <no-reply@eduverse.local>"}, "EDU_MAIL_FROM"),
        ({"mail_backend": "smtp", "smtp_url": ""}, "EDU_SMTP_URL"),
        ({"public_web_url": "http://localhost:3000"}, "EDU_PUBLIC_WEB_URL"),
    ],
)
def test_unsafe_production_settings_are_refused(override, message):
    with pytest.raises(RuntimeError, match=message):
        check_production(Settings(**{**SAFE, **override}))


def test_development_allows_defaults():
    check_production(Settings(env="development", database_url="sqlite:///x.db", code_runner="local"))
