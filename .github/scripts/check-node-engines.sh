#!/usr/bin/env bash
# .nvmrc is the one Node.js version for local development (nvm use) and CI
# (actions/setup-node node-version-file). npm cannot read it, so each
# package.json repeats it as "engines": {"node": "^<.nvmrc>"}, which
# engine-strict in the package's .npmrc enforces on npm install and npm ci.
# This check, run as a pre-commit hook, keeps the copies equal to .nvmrc.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
expected="^$(tr -d '[:space:]' <"${root}/.nvmrc")"
status=0

for package in frontend e2e; do
  actual=$(node -p "require(process.argv[1]).engines?.node ?? ''" "${root}/${package}/package.json")
  if [[ "${actual}" != "${expected}" ]]; then
    echo "${package}/package.json: engines.node is '${actual}', expected '${expected}' (from .nvmrc)." >&2
    status=1
  fi
  if ! grep -qx 'engine-strict=true' "${root}/${package}/.npmrc" 2>/dev/null; then
    echo "${package}/.npmrc: engine-strict=true is missing." >&2
    status=1
  fi
done

exit "${status}"
