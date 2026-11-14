#!/usr/bin/env bash
# Decide which CI areas a change touches, for the path gates in
# .github/workflows/ci.yml and .github/workflows/codeql.yml.
#
# Usage:
#   changed-areas.sh               in CI (reads GITHUB_EVENT_NAME)
#   changed-areas.sh BASE HEAD     locally, for any commit range
#
# Prints one `area=true|false` line per area, and appends the same lines to
# $GITHUB_OUTPUT when it is set. Areas:
#   backend, frontend, image                  -> the ci.yml jobs
#   codeql-python, codeql-javascript-typescript -> the codeql.yml matrix legs
#
# Only pull requests are gated. Every other event (push to main, schedule,
# workflow_dispatch) runs every area. On a pull request, actions/checkout
# checks out the merge commit refs/pull/N/merge, so HEAD^1 is the base branch
# tip and `git diff HEAD^1 HEAD` is exactly what the PR changes against the
# code it will merge into (fetch-depth: 2 is enough). If the range cannot be
# resolved, every area runs: the gate fails open, never closed.
set -euo pipefail

areas=(backend frontend image codeql-python codeql-javascript-typescript)

# Files that change what every gated job does.
shared='^\.github/scripts/changed-areas\.sh$'

# Extended regexes per area; a changed path that matches turns the area on.
# backend: the backend project, the shared Keycloak realm in dev/keycloak/ that
# the backend integration tests import, and the root .gitignore that ruff
# respects.
backend_re="^backend/|^dev/keycloak/|^\.github/workflows/ci\.yml$|^\.gitignore$|${shared}"
# frontend: the frontend job also checks the e2e scaffold, reads .nvmrc and
# runs prettier with the root config, ignore files and .editorconfig.
frontend_re="^frontend/|^e2e/|^\.github/workflows/ci\.yml$|^\.nvmrc$|^\.prettierrc\.json$|^\.prettierignore$|^\.gitignore$|^\.editorconfig$|${shared}"
# image: the Dockerfile builds the frontend and the backend, takes its Node
# and Python versions from .nvmrc and backend/.python-version, and the job runs
# the Dockerfile version check, the smoke test and the Trivy scan.
image_re="^backend/|^frontend/|^Dockerfile$|^\.dockerignore$|^\.nvmrc$|^\.github/tools/trivy/|^\.github/scripts/(check-dockerfile-versions|image-smoke-test|image-scan)\.sh$|^\.github/workflows/ci\.yml$|${shared}"
# CodeQL analyses every file of its language in the repository, not only one
# directory, so any source file of that language turns its leg on.
codeql_python_re="^backend/|\.pyi?$|^\.github/workflows/codeql\.yml$|${shared}"
codeql_js_re="^frontend/|^e2e/|\.(js|jsx|mjs|cjs|ts|tsx|mts|cts|html?|vue)$|^\.github/workflows/codeql\.yml$|${shared}"

emit() {
  local line
  for line in "$@"; do
    echo "$line"
    if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
      echo "$line" >>"$GITHUB_OUTPUT"
    fi
  done
}

all_true() {
  local area lines=()
  echo "$1" >&2
  for area in "${areas[@]}"; do
    lines+=("${area}=true")
  done
  emit "${lines[@]}"
  exit 0
}

if [[ $# -eq 2 ]]; then
  base=$1
  head=$2
elif [[ $# -eq 0 ]]; then
  if [[ "${GITHUB_EVENT_NAME:-}" != "pull_request" ]]; then
    all_true "Event '${GITHUB_EVENT_NAME:-unknown}' is not a pull request: running every area."
  fi
  # Anything other than a merge commit means the checkout is not the PR merge
  # ref, so HEAD^1 would not be the base branch tip.
  if ! git rev-parse --verify --quiet "HEAD^2^{commit}" >/dev/null; then
    all_true "HEAD is not a pull request merge commit: running every area."
  fi
  base=HEAD^1
  head=HEAD
else
  echo "usage: $0 [BASE HEAD]" >&2
  exit 2
fi

if ! git rev-parse --verify --quiet "${base}^{commit}" >/dev/null ||
  ! git rev-parse --verify --quiet "${head}^{commit}" >/dev/null; then
  all_true "Cannot resolve ${base}..${head}: running every area."
fi

# --no-renames lists both the old and the new path of a moved file, so moving
# a file out of an area still counts as a change to that area. Paths are read
# raw (-z, core.quotePath=false): by default git quotes paths with non-ASCII
# bytes, quotes, backslashes or control characters, and a quoted path such as
# "backend/\303\251.py" would match no area. pipefail keeps a failing git diff
# visible to the `if`.
if ! changed=$(git -c core.quotePath=false diff --name-only --no-renames -z "$base" "$head" | tr '\0' '\n'); then
  all_true "git diff ${base} ${head} failed: running every area."
fi

echo "Changed files (${base}..${head}):" >&2
if [[ -n "$changed" ]]; then
  while IFS= read -r file; do
    echo "  ${file}"
  done <<<"$changed" >&2
else
  echo "  (none)" >&2
fi

# matches <regex>: true when a changed path matches. A grep error (status > 1)
# counts as a match, so a broken pattern runs the checks instead of skipping them.
matches() {
  local status=0
  if [[ -z "$changed" ]]; then
    echo false
    return
  fi
  grep -Eq "$1" <<<"$changed" || status=$?
  case $status in
    0) echo true ;;
    1) echo false ;;
    *)
      echo "grep failed with status ${status}: treating the area as changed." >&2
      echo true
      ;;
  esac
}

emit \
  "backend=$(matches "$backend_re")" \
  "frontend=$(matches "$frontend_re")" \
  "image=$(matches "$image_re")" \
  "codeql-python=$(matches "$codeql_python_re")" \
  "codeql-javascript-typescript=$(matches "$codeql_js_re")"
