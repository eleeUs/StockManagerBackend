# ---------------------------------------------------------------------------
# Stage 1 — builder
# Compiles wheels for packages with C extensions (psycopg2, argon2-cffi's
# build fallback) into an isolated prefix, kept out of the runtime image.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ARG REQUIREMENTS=development

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libffi-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/ requirements/

RUN pip install --upgrade pip \
    && pip install --prefix=/install -r requirements/${REQUIREMENTS}.txt


# ---------------------------------------------------------------------------
# Stage 2 — runtime
# No apt packages needed here: psycopg2-binary bundles libpq, and
# argon2-cffi ships prebuilt binary wheels for this platform.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Re-declared: Docker requires ARG to be redeclared in each stage that uses it.
ARG REQUIREMENTS=development

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH=/usr/local/bin:$PATH

WORKDIR /app

COPY --from=builder /install /usr/local

COPY . .

EXPOSE 8000

# Development: runserver with auto-reload (source mounted as a volume).
# Production: CMD is overridden by docker-compose.prod.yml to run gunicorn.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
