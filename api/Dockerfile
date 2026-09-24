# Production image: dependencies are installed into a virtualenv in a
# throwaway builder stage; the runtime stage gets only that venv plus the
# app package - no pip cache, no tests, no dev dependencies, no source
# bind mount. See decisions/0013-production-mode-nginx-static-bundle.md.
# (Dev still uses Dockerfile.dev + uvicorn --reload.)

FROM python:3.12-slim AS build

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /venv
COPY requirements.txt .
RUN /venv/bin/pip install -r requirements.txt

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/venv/bin:$PATH

COPY --from=build /venv /venv

WORKDIR /app
COPY app ./app

EXPOSE 8080

# Exactly one worker: the JSON stores hold in-memory state and assume a
# single writer process (decisions/0004, 0014). --proxy-headers trusts
# nginx's X-Forwarded-* headers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*", "--no-access-log"]
