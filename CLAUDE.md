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

Work is done by five agent roles, defined in [.claude/agents/](.claude/agents/):

| Role                                                       | Does                                                                                                                                                                                                                                                        | Never                          |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| [task-manager](.claude/agents/task-manager.md)             | Creates a worktree and branch from `origin/main`, gathers related follow-ups, routes each task to a developer role, pushes, opens the PR, waits for CI and the Copilot review, replies to and resolves threads, files `follow-up` issues, reports decisions | writes production code, merges |
| [backend-developer](.claude/agents/backend-developer.md)   | `backend/`: Python, FastAPI, the hexagonal domain, persistence, auth, logging                                                                                                                                                                               | pushes, touches GitHub         |
| [frontend-developer](.claude/agents/frontend-developer.md) | `frontend/` and `e2e/`: React, NL Design System CSS, i18n, accessibility, Playwright BDD                                                                                                                                                                    | pushes, touches GitHub         |
| [platform-engineer](.claude/agents/platform-engineer.md)   | Image, Helm chart, kind/Tilt, GitHub Actions, pre-commit and tool versions                                                                                                                                                                                  | pushes, touches GitHub         |
| [code-reviewer](.claude/agents/code-reviewer.md)           | Re-runs every check itself, reviews against tasks, design, specs and ADRs across all stacks, triages Copilot comments (fix, follow-up or decline)                                                                                                           | edits code                     |

**Routing.** The task-manager assigns each task to one developer role, based on the paths and content involved. When a task spans stacks, the backend goes first and exports `openapi.json`; the frontend then regenerates the client from it. Platform work comes last if it depends on either. Each branch gets its own git worktree (`../podiumd-admin-tool-<branch with / replaced by ->`), so parallel runs never share a checkout. The orchestrator removes the worktree after the merge.

The saved workflow [.claude/workflows/implement-task-group.js](.claude/workflows/implement-task-group.js) runs the roles end to end. It has three modes:

- `{ mode: "implement", change, group, tasks, branch }` implements an OpenSpec task group and opens a PR;
- `{ mode: "issue", issue, branch }` implements a GitHub issue (e.g. a `follow-up`) and opens a PR that fixes it;
- `{ mode: "review", pr, branch }` handles the CI and Copilot feedback on an existing PR.

Add `resume: true` to an `implement` or `issue` run to continue it after an interruption, e.g. a usage limit. It reuses the branch and worktree, and briefs the developers from the commits already made.

**Ownership of findings.** Blocking review findings and Copilot fixes go to the role that owns the code. If one turns up in another role's area during a run, it becomes an extra work package for that role (at most 3 per run). `CLAUDE.md` and `.claude/**` belong to the **orchestrator**, the main session: roles report exact diffs, and the orchestrator applies them. Docs follow the stack they describe. Repository-wide docs belong to the platform-engineer. `CONTEXT.md`, ADRs and OpenSpec artifacts change only through a decision for the user.

**Copilot reviews are handled proactively.** The organisation's Copilot reviewer comments within minutes of a PR being opened or pushed. The code-reviewer triages every finding, and fixes go to the developer role that owns the code. The task-manager pushes, replies, resolves and asks Copilot to review again, until a review has no new actionable findings (at most 3 rounds). Unresolved threads block merging.

**Decisions for the user.** Design questions that a role can't settle within its scope are reported as a separate "Decisions for the user" list (question, options, recommendation), never buried among suggestions. Only the user merges, after reviewing.

## Developer rules

These apply to the backend-developer, frontend-developer and platform-engineer alike.

- **Scope.** Implement exactly the tasks, issue or review findings you were given, in the worktree the task-manager prepared. Nothing from other task groups. Mention out-of-scope problems; don't fix them.
- **Sources of truth.** `CONTEXT.md` (terms), `docs/adr/*` (never contradict an ADR), `openspec/changes/<change>/` (`design.md`, `specs/`, `tasks.md`) and `docs/development-requirements.md`.
- **Test-first.** Write a failing test, then make it pass, then refactor. For a review finding, first reproduce it with a failing test on the current code. Report the failing test name and how it failed.
- **Quality gates.** Every check CI runs must pass locally before you report. Never disable a rule without a comment explaining why.
- **Verification is honest.** Never hide output or exit codes, e.g. with `--silent`, `|| true` or `2>/dev/null`, when proving that something works. Check the exit code.
- **Tool versions.** Use each tool's single source (see below and the README "Tool versions" table). Never install global tools, and never write a tool version into a workflow, Dockerfile or doc command.
- **Supply chain.** Use real, current package versions. Pin GitHub Actions and hooks to full commit SHAs, and images to digests, that you looked up. Never invent them.
- **Commits.**
  - Make small, logical commits. **Commit after every task or fix that is green**, so an interrupted run loses at most the step in progress.
  - Every message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - Claims in commit messages must be accurate. Say what you verified, not what you assume.
- **Boundaries.**
  - Never push, never call `gh` or the GitHub API, and never tick boxes in `tasks.md`.
  - Changes to `CLAUDE.md` or `.claude/**` are not yours to make. Put them in your report as an exact diff, and the orchestrator applies them.
  - If you disagree with a review finding, explain why instead of ignoring it.
- **Report.**
  - For each task or finding: what you did, the commits and the checks that passed.
  - What you didn't do, and why.
  - A one-to-two-sentence PR-thread reply per review finding.
  - **Decisions for the user:** design questions you couldn't settle within scope, each with options and your recommendation.
  - **Hand-off notes:** e.g. changed API endpoints and models for the frontend-developer.

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

Repository hooks: `uv run --project backend --locked pre-commit run --all-files`. This uses the pre-commit version locked in `backend/uv.lock`; install the hooks with `uv run --project backend --locked pre-commit install`.

**Tool versions have one source each,** read by CI and local development alike (see the README, "Tool versions"):

- uv: `required-version` in `backend/pyproject.toml`;
- Python: `backend/.python-version`;
- Node: `.nvmrc`;
- pre-commit: `backend/uv.lock`;
- hook tools (gitleaks, actionlint, hadolint, shellcheck): `.pre-commit-config.yaml`.

Never hard-code a tool version in a workflow or a doc command.
