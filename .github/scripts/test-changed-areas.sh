#!/usr/bin/env bash
# Tests for changed-areas.sh. Builds throwaway git repositories in a temporary
# directory and asserts the areas the script reports for each change.
#
# Usage: .github/scripts/test-changed-areas.sh   (exits non-zero on a failure)
set -euo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/changed-areas.sh"
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT

failures=0
all_true='backend=true frontend=true image=true codeql-python=true codeql-javascript-typescript=true'
all_false='backend=false frontend=false image=false codeql-python=false codeql-javascript-typescript=false'

git_() {
  git -c user.name=test -c user.email=test@example.invalid -c commit.gpgsign=false "$@"
}

# new_repo: a repository with one file per area on its first commit.
new_repo() {
  local repo="${work}/repo-$RANDOM$RANDOM"
  git init -q -b main "${repo}"
  mkdir -p "${repo}/backend" "${repo}/frontend" "${repo}/docs"
  echo base >"${repo}/backend/app.py"
  echo base >"${repo}/frontend/app.ts"
  echo base >"${repo}/docs/readme.md"
  git_ -C "${repo}" add -A
  git_ -C "${repo}" commit -q -m base
  echo "${repo}"
}

# run_script <repo> <env...> -- <args...>: the script's stdout as one line.
run_script() {
  local repo=$1
  shift
  local envs=()
  while [[ $# -gt 0 && $1 != "--" ]]; do
    envs+=("$1")
    shift
  done
  shift
  (cd "${repo}" && env -u GITHUB_OUTPUT -u GITHUB_EVENT_NAME ${envs[@]+"${envs[@]}"} "${script}" "$@" 2>/dev/null) | tr '\n' ' ' | sed 's/ $//'
}

check() {
  local name=$1 expected=$2 actual=$3
  if [[ "${actual}" == "${expected}" ]]; then
    echo "ok   ${name}"
  else
    echo "FAIL ${name}"
    echo "       expected: ${expected}"
    echo "       actual:   ${actual}"
    failures=$((failures + 1))
  fi
}

# commit_change <repo> <shell commands run in the repo>: prints the new HEAD.
commit_change() {
  local repo=$1
  (cd "${repo}" && eval "$2")
  git_ -C "${repo}" add -A
  git_ -C "${repo}" commit -q -m change
  git -C "${repo}" rev-parse HEAD
}

# --- explicit ranges --------------------------------------------------------

repo=$(new_repo)
head=$(commit_change "${repo}" 'echo x >docs/other.md')
check "docs only: nothing runs" "${all_false}" \
  "$(run_script "${repo}" -- "${head}^" "${head}")"

repo=$(new_repo)
head=$(commit_change "${repo}" 'echo x >backend/app.py')
check "backend change: backend, image and python" \
  'backend=true frontend=false image=true codeql-python=true codeql-javascript-typescript=false' \
  "$(run_script "${repo}" -- "${head}^" "${head}")"

repo=$(new_repo)
head=$(commit_change "${repo}" 'echo x >frontend/app.ts')
check "frontend change: frontend, image and javascript-typescript" \
  'backend=false frontend=true image=true codeql-python=false codeql-javascript-typescript=true' \
  "$(run_script "${repo}" -- "${head}^" "${head}")"

repo=$(new_repo)
head=$(commit_change "${repo}" 'echo x >Dockerfile')
check "Dockerfile change: only image" \
  'backend=false frontend=false image=true codeql-python=false codeql-javascript-typescript=false' \
  "$(run_script "${repo}" -- "${head}^" "${head}")"

repo=$(new_repo)
head=$(commit_change "${repo}" 'echo x >.dockerignore')
check ".dockerignore change: only image" \
  'backend=false frontend=false image=true codeql-python=false codeql-javascript-typescript=false' \
  "$(run_script "${repo}" -- "${head}^" "${head}")"

repo=$(new_repo)
head=$(commit_change "${repo}" 'echo x >.nvmrc')
check ".nvmrc change: frontend and image" \
  'backend=false frontend=true image=true codeql-python=false codeql-javascript-typescript=false' \
  "$(run_script "${repo}" -- "${head}^" "${head}")"

repo=$(new_repo)
head=$(commit_change "${repo}" 'echo x >backend/.python-version')
check "backend/.python-version change: backend, image and python" \
  'backend=true frontend=false image=true codeql-python=true codeql-javascript-typescript=false' \
  "$(run_script "${repo}" -- "${head}^" "${head}")"

for file in .github/tools/trivy/Dockerfile .github/scripts/image-smoke-test.sh \
  .github/scripts/image-scan.sh .github/scripts/check-dockerfile-versions.sh; do
  repo=$(new_repo)
  head=$(commit_change "${repo}" "mkdir -p \"\$(dirname '${file}')\" && echo x >'${file}'")
  check "${file} change: only image" \
    'backend=false frontend=false image=true codeql-python=false codeql-javascript-typescript=false' \
    "$(run_script "${repo}" -- "${head}^" "${head}")"
done

repo=$(new_repo)
head=$(commit_change "${repo}" 'mkdir -p .github/workflows && echo x >.github/workflows/ci.yml')
check "ci.yml change: backend, frontend and image" \
  'backend=true frontend=true image=true codeql-python=false codeql-javascript-typescript=false' \
  "$(run_script "${repo}" -- "${head}^" "${head}")"

repo=$(new_repo)
head=$(commit_change "${repo}" "echo x >'backend/é.py'")
check "non-ASCII backend path: backend, image and python" \
  'backend=true frontend=false image=true codeql-python=true codeql-javascript-typescript=false' \
  "$(run_script "${repo}" -- "${head}^" "${head}")"

repo=$(new_repo)
head=$(commit_change "${repo}" "echo x >'frontend/we\"ird.ts'")
check "quote in frontend path: frontend, image and javascript-typescript" \
  'backend=false frontend=true image=true codeql-python=false codeql-javascript-typescript=true' \
  "$(run_script "${repo}" -- "${head}^" "${head}")"

# The backend integration tests import the shared Keycloak realm from dev/.
repo=$(new_repo)
head=$(commit_change "${repo}" 'mkdir -p dev/keycloak && echo x >dev/keycloak/podiumd-admin-realm.json')
check "Keycloak realm change: backend only" \
  'backend=true frontend=false image=false codeql-python=false codeql-javascript-typescript=false' \
  "$(run_script "${repo}" -- "${head}^" "${head}")"

repo=$(new_repo)
head=$(commit_change "${repo}" "echo x >'backend/back\\slash.py'")
check "backslash in backend path: backend, image and python" \
  'backend=true frontend=false image=true codeql-python=true codeql-javascript-typescript=false' \
  "$(run_script "${repo}" -- "${head}^" "${head}")"

repo=$(new_repo)
head=$(commit_change "${repo}" 'git mv backend/app.py docs/app.txt')
check "rename out of backend: backend, image and python" \
  'backend=true frontend=false image=true codeql-python=true codeql-javascript-typescript=false' \
  "$(run_script "${repo}" -- "${head}^" "${head}")"

repo=$(new_repo)
check "unresolvable range: everything runs" "${all_true}" \
  "$(run_script "${repo}" -- does-not-exist HEAD)"

# --- CI mode (no arguments) -------------------------------------------------

for event in push schedule workflow_dispatch; do
  repo=$(new_repo)
  check "${event} event: everything runs" "${all_true}" \
    "$(run_script "${repo}" "GITHUB_EVENT_NAME=${event}" --)"
done

# A pull_request checkout is the merge commit refs/pull/N/merge: HEAD^1 is the
# base branch tip, HEAD^2 the PR head.
repo=$(new_repo)
git_ -C "${repo}" switch -q -c pr
commit_change "${repo}" 'echo x >frontend/app.ts' >/dev/null
git_ -C "${repo}" switch -q main
commit_change "${repo}" 'echo x >backend/app.py' >/dev/null
git_ -C "${repo}" merge -q --no-ff --no-edit pr
check "pull_request merge commit: only the PR's changes count" \
  'backend=false frontend=true image=true codeql-python=false codeql-javascript-typescript=true' \
  "$(run_script "${repo}" GITHUB_EVENT_NAME=pull_request --)"

repo=$(new_repo)
commit_change "${repo}" 'echo x >docs/other.md' >/dev/null
check "pull_request without a merge commit: everything runs" "${all_true}" \
  "$(run_script "${repo}" GITHUB_EVENT_NAME=pull_request --)"

repo=$(new_repo)
outfile="${work}/github-output"
(cd "${repo}" && GITHUB_EVENT_NAME=push GITHUB_OUTPUT="${outfile}" "${script}" >/dev/null 2>&1)
check "writes the areas to GITHUB_OUTPUT" "${all_true}" \
  "$(tr '\n' ' ' <"${outfile}" | sed 's/ $//')"

# --- tool failures fail open ------------------------------------------------

# stub <name> <body>: a directory holding an executable `name` with that body.
stub() {
  local dir="${work}/stub-$RANDOM$RANDOM"
  mkdir -p "${dir}"
  printf '#!/usr/bin/env bash\n%s\n' "$2" >"${dir}/$1"
  chmod +x "${dir}/$1"
  echo "${dir}"
}

real_git=$(command -v git)
repo=$(new_repo)
head=$(commit_change "${repo}" 'echo x >docs/other.md')
stubs=$(stub git "if [[ \$* == *diff* ]]; then exit 128; fi; exec '${real_git}' \"\$@\"")
check "git diff fails: everything runs" "${all_true}" \
  "$(run_script "${repo}" "PATH=${stubs}:${PATH}" -- "${head}^" "${head}")"

stubs=$(stub grep 'exit 2')
check "grep fails: every area counts as changed" "${all_true}" \
  "$(run_script "${repo}" "PATH=${stubs}:${PATH}" -- "${head}^" "${head}")"

if [[ ${failures} -gt 0 ]]; then
  echo "${failures} test(s) failed"
  exit 1
fi
echo "all tests passed"
