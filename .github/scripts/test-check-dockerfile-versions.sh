#!/usr/bin/env bash
# Tests for check-dockerfile-versions.sh. Writes small Dockerfiles to a
# temporary directory and asserts whether the check accepts them.
#
# Usage: .github/scripts/test-check-dockerfile-versions.sh   (exits non-zero on a failure)
set -euo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/check-dockerfile-versions.sh"
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT

failures=0
digest="sha256:$(printf 'a%.0s' {1..64})"

# expect <pass|fail> <name> <Dockerfile content>
expect() {
  local want=$1 name=$2 content=$3 file status=0
  file="${work}/Dockerfile-$RANDOM$RANDOM"
  printf '%s\n' "${content}" >"${file}"
  "${script}" "${file}" >/dev/null 2>&1 || status=$?
  if [[ ${want} == pass && ${status} -eq 0 ]] || [[ ${want} == fail && ${status} -eq 1 ]]; then
    echo "ok   ${name}"
  else
    echo "FAIL ${name} (wanted ${want}, exit status ${status})"
    failures=$((failures + 1))
  fi
}

expect pass "version from a build arg, pinned by digest" "ARG NODE_BASE_VERSION
FROM docker.io/library/node:\${NODE_BASE_VERSION}-trixie-slim@${digest} AS frontend
ARG NODE_BASE_VERSION
RUN node --version"

expect pass "\${VAR} and \$VAR spellings, --platform, lower-case instructions" "ARG PYTHON_BASE_VERSION
from --platform=\$BUILDPLATFORM python:\$PYTHON_BASE_VERSION-slim@${digest} as python"

expect pass "a later stage builds on an earlier stage by name" "ARG PYTHON_BASE_VERSION
FROM python:\${PYTHON_BASE_VERSION}-slim@${digest} AS python
FROM python AS runtime"

expect pass "COPY --from an image pinned by digest only" "FROM scratch
COPY --from=ghcr.io/astral-sh/uv@${digest} /uv /usr/local/bin/uv"

expect pass "COPY --from an earlier stage" "ARG PYTHON_BASE_VERSION
FROM python:\${PYTHON_BASE_VERSION}-slim@${digest} AS build
FROM build AS runtime
COPY --from=build /app /app
COPY --from=0 /app /app"

expect pass "versions in comments are ignored" "# Built on Python 3.12 and Node.js 26.
FROM scratch"

expect pass "ARG without a default, or with a non-version default" "ARG NODE_BASE_VERSION
ARG APP_PORT=8000
FROM scratch"

expect fail "literal version in the FROM tag" "FROM docker.io/library/node:26.13.0-trixie-slim@${digest}"

expect fail "literal major version in the FROM tag" "FROM python:3-slim@${digest}"

expect fail "literal version next to a build arg" "ARG V
FROM python:\${V}-slim-3.12@${digest}"

expect fail "FROM without a digest" "ARG V
FROM python:\${V}-slim"

expect fail "FROM with a short digest" "ARG V
FROM python:\${V}-slim@sha256:abc"

expect fail "FROM without a digest after --platform" "FROM --platform=linux/amd64 python"

expect fail "COPY --from an image with a literal version" "FROM scratch
COPY --from=ghcr.io/astral-sh/uv:0.13.7@${digest} /uv /uv"

expect fail "COPY --from an image without a digest" "FROM scratch
COPY --from=ghcr.io/astral-sh/uv /uv /uv"

expect fail "RUN --mount from an image without a digest" "FROM scratch
RUN --mount=type=bind,from=ghcr.io/astral-sh/uv,source=/uv,target=/uv /uv --version"

expect fail "ARG with a literal version default" "ARG NODE_BASE_VERSION=26.13.0
FROM scratch"

expect fail "ARG with a quoted literal version default" 'ARG PYTHON_BASE_VERSION="3.12"
FROM scratch'

status=0
"${script}" "${work}/does-not-exist" >/dev/null 2>&1 || status=$?
if [[ ${status} -eq 1 ]]; then
  echo "ok   a missing file fails"
else
  echo "FAIL a missing file fails (exit status ${status})"
  failures=$((failures + 1))
fi

if [[ ${failures} -gt 0 ]]; then
  echo "${failures} test(s) failed"
  exit 1
fi
echo "all tests passed"
