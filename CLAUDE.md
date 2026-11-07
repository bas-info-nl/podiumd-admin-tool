# CLAUDE.md

Guidance for AI coding agents (and humans) working in this repository.

## Read first

- [CONTEXT.md](CONTEXT.md) is the domain glossary. Use its terms exactly
  (Environment, Component, Script, Script Run, Audit Entry, Viewer, Operator,
  ...) in code, tests, specs and docs, and avoid the listed alternatives.
- [docs/adr/](docs/adr/) holds the architecture decisions. Do not contradict an
  ADR; propose a new or superseding ADR instead.
- [docs/development-requirements.md](docs/development-requirements.md) describes
  testing, quality gates and the local development loop.
- [docs/research/podiumd.md](docs/research/podiumd.md) holds the PodiumD facts
  the design relies on.
- Work is planned as OpenSpec changes in [openspec/changes/](openspec/changes/).
  Implement only the tasks you were asked to implement.

## Rules

- **Test-first (TDD).** Domain and application logic is written red, green,
  refactor: a failing pytest test first, then the smallest change that passes,
  then clean up. Frontend logic follows the same loop with Vitest.
- **Hexagonal backend (ADR 0009).** `domain/` and `application/` never import
  FastAPI, SQLAlchemy or Authlib. import-linter enforces this; do not weaken the
  contracts in `backend/pyproject.toml`.
- **Language.** The UI is Dutch (`nl`, with `en` for development) through
  react-i18next; never put literal text in JSX. Code, comments and docs are in
  English.
- **Quality gates.** Every check that CI runs must pass locally before you
  commit (see the README). Never disable a rule to make a check pass without a
  comment explaining why.
- **Git.** `main` is protected and only accepts PRs. Work on a feature branch.

## Commands

Backend (in `backend/`):

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run lint-imports
uv run pytest
```

Frontend (in `frontend/`):

```sh
npm ci
npm run lint && npm run format:check && npm run typecheck && npm run test:coverage
```

End-to-end tests (in `e2e/`): `npm ci && npm test`.

Repository hooks: `uvx pre-commit run --all-files`.
