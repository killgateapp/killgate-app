FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_ENV=production \
    PORT=8080 \
    WEB_CONCURRENCY=1

WORKDIR /app

# Install dependencies before source so normal code changes preserve the dependency layer.
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY app ./app
COPY scripts ./scripts
COPY .env.example README.md ./

# Runtime data is in Supabase in production. Keep the image filesystem unprivileged.
RUN useradd --create-home --uid 10001 killgate \
    && chown -R killgate:killgate /app
USER 10001:10001

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT','8080') + '/readyz', timeout=3).read()" || exit 1

CMD ["sh", "-c", "python scripts/check_production_readiness.py && exec uvicorn app.web:app --host 0.0.0.0 --port ${PORT:-8080} --workers ${WEB_CONCURRENCY:-1}"]
