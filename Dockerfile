# syntax=docker/dockerfile:1
#
# One image for every project in this repository. Each project has its own console script
# (see [project.scripts] in pyproject.toml), so the image has no default command: the Kubernetes
# Job/CronJob sets it, e.g. `publisher-ldap`.
#
#   docker build --target test .                       # run the test suite
#   docker build -t mono-cis .                         # runtime image
#   docker run --rm --env-file .env mono-cis publisher-ldap
#
# The Python version tracks .python-version / requires-python; the uv version tracks mise.toml.

ARG PYTHON_VERSION=3.14
ARG UV_VERSION=0.12.12

# --- uv: a named stage, because `COPY --from=` does not expand build args -----------------------------
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# --- builder: resolve and install the locked dependencies, then the project itself ------------------
FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=uv /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first so they cache independently of source changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# The project, installed as a regular (non-editable) package so the runtime stage only needs .venv.
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# --- test: the same command as `mise run test`, against the installed package ------------------------
FROM builder AS test
ENV PATH="/app/.venv/bin:${PATH}"
COPY tests ./tests
RUN python -m unittest discover -s tests -t .

# --- runtime: just the interpreter and the populated virtualenv, as an unprivileged user -------------
FROM python:${PYTHON_VERSION}-slim AS runtime
LABEL org.opencontainers.image.title="mono-cis"

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1

USER app

# No CMD on purpose; see the header. Configuration is environment variables only
# (docs/publishers/ldap.md lists them for the LDAP publisher).
