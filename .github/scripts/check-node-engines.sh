#!/usr/bin/env bash
# .nvmrc is the one Node.js version for local development (nvm use) and CI
# (actions/setup-node node-version-file). npm cannot read it, so each
# package.json repeats it as "engines": {"node": "^<.nvmrc>"}; npm warns
# (EBADENGINE) when the running Node.js does not satisfy that. This check, run
# as a pre-commit hook, keeps the copies equal to .nvmrc.
#
# engine-strict is deliberately not set: Dependabot's npm updater runs an
# older Node.js and would fail every update for /frontend and /e2e.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
nvmrc=$(tr -d '[:space:]' <"${root}/.nvmrc")
expected="^${nvmrc#v}"
status=0

for package in frontend e2e; do
  for file in package.json package-lock.json; do
    if [[ "${file}" == package.json ]]; then
      query="require(process.argv[1]).engines?.node ?? ''"
    else
      # The lockfile records the root package's engines under packages[""].
      query="require(process.argv[1]).packages?.['']?.engines?.node ?? ''"
    fi
    actual=$(node -p "${query}" "${root}/${package}/${file}")
    if [[ "${actual}" != "${expected}" ]]; then
      echo "${package}/${file}: engines.node is '${actual}', expected '${expected}' (from .nvmrc)." >&2
      status=1
    fi
  done
done

exit "${status}"
