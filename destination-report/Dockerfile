# syntax=docker/dockerfile:1.7
#
# One non-root application image built from the repository's uv lock. Nothing is
# downloaded or synced at container start, no development tool is installed and the
# image contains no private evidence, credential or certificate.
#
# Base and builder images are pinned by digest so a rebuild cannot silently pick a
# different Python or uv binary.

FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv

FROM python:3.13-slim@sha256:57b29a7c050c4e679e4bea572e14b3965cf4b5839de2da49d55e49ffc4024f39 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

# The uv binary is copied from its pinned image; it is not a runtime dependency and is
# not on the application path used by the entry point.
COPY --from=uv /uv /usr/local/bin/uv

# Dependency layer: the lock is used exactly, without the project and without the dev
# group. A changed source file does not invalidate this layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project --no-cache

# The project itself, installed non-editable into the image environment. The image is
# immutable: a mounted source tree can never change the running code.
COPY src ./src
RUN uv sync --locked --no-dev --no-editable --no-cache

# Explicit host-side commands are shipped for one-shot import/health use, never as a
# startup sync.
COPY tools ./tools

RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app \
    && python -c "import household_report.app" \
    && ! command -v ruff \
    && ! command -v lefthook \
    && test ! -e /app/.venv \
    && rm -f /usr/local/bin/uv

USER 10001:10001

EXPOSE 8787

ENTRYPOINT ["python", "-m", "household_report.app"]
