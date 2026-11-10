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

## Team workflow (agents)

Work is done by three agent roles, defined in [.claude/agents/](.claude/agents/):

| Role                                                   | Does                                                                                                                                                                              | Never                          |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| [task-manager](.claude/agents/task-manager.md)         | Creates the branch from `origin/main`, briefs the developer, pushes, opens the PR, waits for CI and the Copilot review, replies to and resolves threads, files `follow-up` issues | writes production code, merges |
| [senior-developer](.claude/agents/senior-developer.md) | Implements tasks and review fixes test-first, runs every check, commits locally                                                                                                   | pushes, touches GitHub         |
| [code-reviewer](.claude/agents/code-reviewer.md)       | Re-runs every check itself, reviews against tasks, design, specs and ADRs, triages Copilot comments (fix, follow-up or decline)                                                   | edits code                     |

The saved workflow [.claude/workflows/implement-task-group.js](.claude/workflows/implement-task-group.js) runs them end to end. It works in two modes:

- `{ mode: "implement", change, group, tasks, branch }` implements a task group and opens a PR;
- `{ mode: "review", pr, branch }` handles the CI and Copilot feedback on an existing PR.

**Copilot reviews are handled proactively.** The organisation's Copilot reviewer comments within minutes of a PR being opened or pushed. The code-reviewer triages every finding, and fixes go back to the senior-developer. The task-manager pushes, replies, resolves and asks Copilot to review again, until a review has no new actionable findings (at most 3 rounds). Unresolved threads block merging. Only the user merges, after reviewing.

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

Repository hooks: `uv run --project backend pre-commit run --all-files`. This uses the pre-commit version locked in `backend/uv.lock`; install the hooks with `uv run --project backend pre-commit install`.

**Tool versions have one source each,** read by CI and local development alike (see the README, "Tool versions"):

- uv: `required-version` in `backend/pyproject.toml`;
- Python: `backend/.python-version`;
- Node: `.nvmrc`;
- pre-commit: `backend/uv.lock`;
- hook tools (gitleaks, actionlint, hadolint, shellcheck): `.pre-commit-config.yaml`.

Never hard-code a tool version in a workflow or a doc command.
