# syntax=docker/dockerfile:1
# EduVerse API: FastAPI on uvicorn. Migrations run at start-up (docker-entrypoint.sh).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so this layer is reused until pyproject.toml changes.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini docker-entrypoint.sh ./

RUN useradd --create-home --uid 10001 eduverse \
    && mkdir -p /app/uploads \
    && chown eduverse:eduverse /app/uploads \
    && chmod +x docker-entrypoint.sh
USER eduverse

ENV EDU_UPLOAD_DIR=/app/uploads
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)" || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
# --proxy-headers trusts X-Forwarded-For only from FORWARDED_ALLOW_IPS (uvicorn reads that env var),
# so per-IP rate limits see the learner's address behind the web proxy.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
