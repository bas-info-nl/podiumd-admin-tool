# check=error=true;skip=InvalidDefaultArgInFrom
# Build checks fail the build. InvalidDefaultArgInFrom is skipped on purpose:
# the base image versions have no default, so a build without the build args
# fails on an invalid image name instead of using a version written here.
#
# The PodiumD Admin Tool image (design D7, ADR 0007, ADR 0008): the built
# frontend and the backend in one image, served by uvicorn.
#
# Build it from the repository root; the Node.js and Python versions come from
# their single sources (README, "Tool versions"), never from this file:
#
#   docker build \
#     --build-arg NODE_BASE_VERSION="$(cat .nvmrc)" \
#     --build-arg PYTHON_BASE_VERSION="$(cat backend/.python-version)" \
#     --tag podiumd-admin:local .
#
# Base images are pinned by digest. The digest decides which image is used, so
# each build stage checks that its Node.js or Python matches the build arg:
# after a version bump the build fails until the digest is updated too. Look
# a digest up with `docker buildx imagetools inspect <image>:<tag>`.
# .github/scripts/check-dockerfile-versions.sh fails on a literal version here.
#
# At runtime the image runs as uid 1000 and needs only /tmp to be writable
# (an emptyDir in the Helm chart); the root filesystem can be read-only. The
# command is exec form, so no shell is involved.

ARG NODE_BASE_VERSION
ARG PYTHON_BASE_VERSION

# --- Frontend: the built SPA ---------------------------------------------------
FROM docker.io/library/node:${NODE_BASE_VERSION}-trixie-slim@sha256:5adad64f9a1fca2d51972caa65983634c8a774eb300d72b20f7f2a0f60368072 AS frontend
ARG NODE_BASE_VERSION
RUN test "$(node --version)" = "v${NODE_BASE_VERSION}" \
  || { echo "The node image digest is not Node.js ${NODE_BASE_VERSION} (.nvmrc): update the digest." >&2; exit 1; }
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- Python base, shared by the backend build and the runtime ----------------
FROM docker.io/library/python:${PYTHON_BASE_VERSION}-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS python

# --- Backend: the locked dependencies and the package in a virtualenv --------
FROM python AS backend
ARG PYTHON_BASE_VERSION
RUN python -I -c 'import os, platform, sys; want = os.environ["PYTHON_BASE_VERSION"]; have = platform.python_version(); sys.exit(0 if have == want else f"The python image digest is Python {have}, not {want} (backend/.python-version): update the digest.")'
# uv is pinned by digest only. It refuses to run the project unless it is the
# version in [tool.uv] required-version (backend/pyproject.toml), so a uv bump
# fails this build until the digest is updated too.
COPY --from=ghcr.io/astral-sh/uv@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
  UV_LINK_MODE=copy \
  UV_NO_CACHE=1 \
  UV_PYTHON_DOWNLOADS=never \
  UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/src ./src
RUN uv sync --locked --no-dev --no-editable

# --- Runtime -----------------------------------------------------------------
FROM python AS runtime
LABEL org.opencontainers.image.title="PodiumD Admin Tool" \
  org.opencontainers.image.source="https://github.com/infonl/podiumd-admin-tool" \
  org.opencontainers.image.licenses="EUPL-1.2"
# Debian updates are applied at build time: the pinned base image may predate
# a fixed package, and the Trivy scan fails on fixable HIGH or CRITICAL
# vulnerabilities. The base digest still fixes the starting point.
RUN apt-get update \
  && apt-get upgrade --yes \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/* \
  && groupadd --system --gid 1000 podiumd-admin \
  && useradd --system --uid 1000 --gid 1000 --no-create-home --home-dir /nonexistent \
    --shell /usr/sbin/nologin podiumd-admin
WORKDIR /app
# Owned by root and not writable for uid 1000.
COPY --from=backend /app/.venv /app/.venv
COPY --from=frontend /src/frontend/dist /app/static
# The migration Job runs `alembic upgrade head` from /app.
COPY backend/alembic.ini /app/alembic.ini
ENV PATH="/app/.venv/bin:${PATH}" \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  HOME=/tmp \
  TMPDIR=/tmp
USER 1000:1000
EXPOSE 8000
# --no-proxy-headers (issue #32): uvicorn would otherwise trust X-Forwarded-For
# from 127.0.0.1 (a mesh sidecar) and bypass trustedProxies; the app resolves
# the client IP itself. Guarded by .github/scripts/image-smoke-test.sh.
CMD ["uvicorn", "--factory", "--no-proxy-headers", "--host", "0.0.0.0", "--port", "8000", "podiumd_admin.main:create_app_from_environment"]
