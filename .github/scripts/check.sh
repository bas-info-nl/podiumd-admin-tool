#!/usr/bin/env bash
# Run the quality gates of one or more areas, with the commands CI runs.
#
# Usage:
#   check.sh AREA...               run the named areas
#   check.sh --changed BASE HEAD   run `hooks`, plus the areas that
#                                  changed-areas.sh says BASE..HEAD touches
#
# Areas:
#   backend    the `backend` job in .github/workflows/ci.yml
#   frontend   the `frontend` job: frontend/ and the e2e/ scaffold
#   image      the `image` job: hadolint, the Dockerfile version check, the
#              build, the smoke test and the Trivy scan (needs Docker)
#   hooks      the script tests, the agent setup tests (.claude/tests/) and
#              `pre-commit run --all-files`
#   hygiene    `hooks` plus gitleaks over the full history (the `hygiene` job)
#   all        backend, frontend, image and hygiene
#
# This script is the one list of local check commands: CLAUDE.md and the agent
# roles in .claude/agents/ point here instead of repeating them. ci.yml runs the
# same commands as separate steps; change the two together.
#
# The pre-commit fixer hooks rewrite files. Run `hooks` and `hygiene` on a tree
# you are allowed to change: your own worktree, or a scratch worktree when you
# are reviewing someone else's work.
#
# No tool version is set here; each tool reads its single source (see the
# README, "Tool versions"). The backend integration tests need a running Docker.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)

usage() {
  echo "usage: $0 AREA... | --changed BASE HEAD   (areas: backend frontend image hooks hygiene all)" >&2
  exit 2
}

# Print each command before running it, so a log shows what passed or failed.
step() {
  printf '\n+ %s\n' "$*" >&2
  "$@"
}

check_backend() (
  cd "$root/backend"
  step uv sync --locked
  step uv run ruff check .
  step uv run ruff format --check .
  step uv run mypy
  step uv run lint-imports --no-cache
  step uv run pytest
  step uv run coverage report \
    --include="src/podiumd_admin/domain/*,src/podiumd_admin/application/*" \
    --fail-under=85
  requirements=$(mktemp)
  trap 'rm -f "$requirements"' EXIT
  step uv export --quiet --locked --all-groups --no-emit-project \
    --format requirements-txt -o "$requirements"
  step uv run pip-audit --strict --disable-pip --require-hashes -r "$requirements"
)

check_frontend() (
  cd "$root/frontend"
  step npm ci
  step npm run lint
  step npm run format:check
  step npm run typecheck
  step npm run test:coverage
  step npm audit
  cd "$root/e2e"
  step npm ci
  step npm run typecheck
  step npm audit
)

check_image() (
  cd "$root"
  local image=podiumd-admin:check
  step uv run --project backend --locked pre-commit run hadolint --all-files
  step .github/scripts/check-dockerfile-versions.sh Dockerfile
  step docker build \
    --build-arg NODE_BASE_VERSION="$(cat .nvmrc)" \
    --build-arg PYTHON_BASE_VERSION="$(cat backend/.python-version)" \
    --tag "$image" .
  step .github/scripts/image-smoke-test.sh "$image"
  step .github/scripts/image-scan.sh "$image"
)

check_hooks() (
  cd "$root"
  step .github/scripts/test-changed-areas.sh
  step .github/scripts/test-wait-for-pr-feedback.sh
  step .github/scripts/test-check-dockerfile-versions.sh
  # pre-commit skips .claude/, so the agent setup has its own tests: the role
  # files, the shared settings and the control flow of the workflow script.
  step node --test ".claude/tests/*.test.mjs"
  # The ruff, prettier and eslint hooks use the locked backend and frontend tools.
  (cd backend && step uv sync --locked)
  (cd frontend && step npm ci)
  step uv run --project backend --locked pre-commit run --all-files --show-diff-on-failure
)

check_history() (
  cd "$root"
  step uv run --project backend --locked pre-commit run gitleaks-history --hook-stage manual
)

[[ $# -ge 1 ]] || usage

requested=()
if [[ $1 == --changed ]]; then
  [[ $# -eq 3 ]] || usage
  requested=(hooks)
  # changed-areas.sh fails open: when it cannot tell, it reports every area.
  touched=$("$root/.github/scripts/changed-areas.sh" "$2" "$3")
  while IFS='=' read -r area value; do
    if [[ $value == true && ($area == backend || $area == frontend || $area == image) ]]; then
      requested+=("$area")
    fi
  done <<<"$touched"
else
  requested=("$@")
fi

# Validate every name before running anything, and expand the group names.
backend=false frontend=false image=false hooks=false history=false
for area in "${requested[@]}"; do
  case $area in
    backend) backend=true ;;
    frontend) frontend=true ;;
    image) image=true ;;
    hooks) hooks=true ;;
    hygiene) hooks=true history=true ;;
    all) backend=true frontend=true image=true hooks=true history=true ;;
    *)
      echo "unknown area: ${area}" >&2
      usage
      ;;
  esac
done

if [[ $backend == true ]]; then check_backend; fi
if [[ $frontend == true ]]; then check_frontend; fi
if [[ $image == true ]]; then check_image; fi
if [[ $hooks == true ]]; then check_hooks; fi
if [[ $history == true ]]; then check_history; fi

printf '\ncheck.sh: all checks passed (%s)\n' "${requested[*]}" >&2
