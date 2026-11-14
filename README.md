# PodiumD Admin Tool

A web app that lets a municipality's administrators manage, operate and diagnose
their own [PodiumD](https://github.com/Dimpact-Samenwerking/helm-charts)
Environment. One Admin Tool Instance is installed per Environment (`test`,
`accp` or `prod`). It shows Effective Settings, runs Scripts from a Script
Catalogue as one-off Kubernetes Jobs, runs Diagnostic Runs of read-only Checks,
and keeps an append-only Audit Log of every attempted action.

> Status: in development. Nothing is deployable yet.

## Documentation

- [CONTEXT.md](CONTEXT.md): the domain glossary. Code, specs and docs use these
  terms.
- [docs/adr/](docs/adr/): architecture decision records (ADR 0001–0011).
- [docs/development-requirements.md](docs/development-requirements.md): testing,
  quality gates and the local development loop.
- [docs/research/podiumd.md](docs/research/podiumd.md): facts about PodiumD the
  design relies on.
- [openspec/](openspec/): change proposals, designs, specs and task lists.

## Repository layout

| Path         | Contents                                                     |
| ------------ | ------------------------------------------------------------ |
| `backend/`   | Python 3.12 FastAPI backend, hexagonal layout, managed by uv |
| `frontend/`  | React + TypeScript + Vite UI, NL Design System, Dutch UI     |
| `e2e/`       | Playwright BDD end-to-end tests                              |
| `docs/`      | ADRs, development requirements and research                  |
| `Dockerfile` | The one container image: built frontend plus backend         |

## Development

Prerequisites: [uv](https://docs.astral.sh/uv/) and Node.js with npm, in the
versions below. uv installs Python for the backend.

```sh
# Backend
cd backend
uv sync
uv run pytest

# Frontend
cd frontend
npm ci
npm run dev

# End-to-end tests (against a running Admin Tool Instance, E2E_BASE_URL)
cd e2e
npm ci
npx playwright install chromium
npm test
```

### Tool versions

Every tool version is set in exactly one file in this repository, and CI and
local development read that same file. Versions are exact (patch level), so
"works on my machine" and CI run the same tools. Do not repeat a version in a
workflow or a doc; change the file in the table instead.

| Tool                                               | Single source                                                         | Read by CI                                        | Locally                                                                                             |
| -------------------------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| uv                                                 | `[tool.uv] required-version` in `backend/pyproject.toml`              | `setup-uv` `version-file`                         | uv refuses to run the project with another version; `uv self update <version>` or `brew upgrade uv` |
| Python                                             | `backend/.python-version`                                             | uv (`uv sync` in `backend/`)                      | uv installs and uses it automatically (`uv python install` in `backend/`)                           |
| Node.js (and its bundled npm)                      | `.nvmrc`                                                              | `setup-node` `node-version-file`                  | `nvm install` / `nvm use` (or fnm); npm warns (`EBADENGINE`) on another version                     |
| pre-commit                                         | `backend/uv.lock` (backend dev dependency)                            | `uv run --project backend --locked pre-commit`    | `uv run --project backend --locked pre-commit ...`                                                  |
| gitleaks, actionlint, zizmor, hadolint, shellcheck | hook `rev` in `.pre-commit-config.yaml`                               | through pre-commit                                | through pre-commit                                                                                  |
| ruff, mypy, eslint, prettier, ...                  | `backend/uv.lock`, `frontend/package-lock.json`                       | `uv sync --locked`, `npm ci`                      | `uv sync`, `npm ci`                                                                                 |
| Node.js and Python base images                     | `.nvmrc`, `backend/.python-version` (version); digest in `Dockerfile` | `docker build --build-arg` from the version files | the same `docker build` command (see "Container image")                                             |
| uv in the image                                    | `required-version` (version); digest in `Dockerfile`                  | uv refuses another version, failing the build     | the same                                                                                            |
| Trivy                                              | `FROM` in `.github/tools/trivy/Dockerfile`                            | `.github/scripts/image-scan.sh`                   | `.github/scripts/image-scan.sh`                                                                     |

The uv pin is exact and Dependabot does not bump it: when Dependabot reports a
uv version mismatch, bump `required-version` by hand in a PR ([#22](https://github.com/infonl/podiumd-admin-tool/issues/22)).

Known gap: actionlint shellchecks workflow `run:` blocks with the `shellcheck`
on `PATH`, not the pinned shellcheck-py hook version
([#23](https://github.com/infonl/podiumd-admin-tool/issues/23)).

`package.json` `engines` (and the root entry in each `package-lock.json`)
repeats `.nvmrc` as `^<version>` because npm cannot read `.nvmrc`; a pre-commit
hook (`.github/scripts/check-node-engines.sh`) fails when they disagree. npm
only warns on a mismatch: `engine-strict` is not set, because Dependabot's npm
updater runs an older Node.js and would fail every update. CI always installs
exactly `.nvmrc`.

The Python language level comes from `requires-python` in
`backend/pyproject.toml`: ruff infers its target from it, and mypy checks
against the interpreter, which is the one in `backend/.python-version`. uv
rejects a `.python-version` outside `requires-python`.

The `Dockerfile` never names a version (`check-dockerfile-versions.sh`, a
pre-commit hook, fails if it does). It pins the base images and the uv image
by digest, and the digest decides which image is used, so the build checks
that the image's Node.js, Python and uv match the version files. After a Node.js,
Python or uv bump, update the matching digest in the `Dockerfile` too, with
`docker buildx imagetools inspect <image>:<tag>`; the build fails until you
do. Dependabot cannot update these digests (it cannot resolve the build-arg
tags); it does update the Trivy image.

After a version bump, update locally with `uv self update <version>` (or
`brew upgrade uv`), `nvm install` in the repository root, and `uv sync` and
`npm ci` again.

### Database and integration tests

The backend stores the Audit Log and sessions in PostgreSQL (ADR 0005, design
D2/D4). Two database roles are involved: `podiumd_admin_owner` owns the schema
and runs the Alembic migrations, and `podiumd_admin_app` is the role the
application runs with. The app role may only read and insert Audit Entries.

The persistence tests (marker `integration`, in `backend/tests/adapters/db/`)
start a real PostgreSQL with [testcontainers](https://testcontainers.com/), so
they need a running Docker. They are part of the default `uv run pytest` run and
of CI. Without Docker they fail rather than skip; to leave them out locally,
run `uv run pytest -m "not integration"`.

Run the migrations against a database as the owner role:

```sh
cd backend
PODIUMD_ADMIN_DATABASE_OWNER_URL=postgresql+psycopg://podiumd_admin_owner:...@localhost:5432/podiumd_admin \
  uv run alembic upgrade head
# Or print the SQL to review it first:
uv run alembic upgrade head --sql
```

### Container image

One image holds the built frontend and the backend (design D7, ADR 0008). It
runs as uid 1000 with a read-only root filesystem; `/tmp` is the only path
that must be writable. Build it from the repository root; the Node.js and
Python versions come from their version files:

```sh
docker build \
  --build-arg NODE_BASE_VERSION="$(cat .nvmrc)" \
  --build-arg PYTHON_BASE_VERSION="$(cat backend/.python-version)" \
  --tag podiumd-admin:local .
```

The container listens on port 8000 and starts
`uvicorn --factory --no-proxy-headers podiumd_admin.main:create_app_from_environment`.
It needs the `PODIUMD_ADMIN_*` settings (`backend/src/podiumd_admin/config.py`);
`.github/scripts/image-smoke-test.sh` shows a minimal set. Check an image the
way CI does with `.github/scripts/check.sh image`: hadolint, the Dockerfile
version check, the build, the smoke test (read-only root filesystem,
`/healthz`, uid 1000, proxy headers off) and the Trivy scan, which fails on
HIGH or CRITICAL vulnerabilities that have a fix.

### Pre-commit hooks

The hooks in [.pre-commit-config.yaml](.pre-commit-config.yaml) run ruff,
prettier, eslint, gitleaks, hadolint, actionlint, zizmor, shellcheck and whitespace
fixers on every commit. pre-commit itself is a backend dev dependency, and the
ruff, prettier and eslint hooks use the versions locked in the backend and
frontend, so install those first. Then install the hooks once per clone:

```sh
(cd backend && uv sync) && (cd frontend && npm ci)
uv run --project backend --locked pre-commit install
```

Run all hooks against the whole repository with
`uv run --project backend --locked pre-commit run --all-files`. CI runs the
same command with the same pre-commit version, so a green local run means a
green `hygiene` job. The full-history gitleaks scan that CI also runs is
`uv run --project backend --locked pre-commit run gitleaks-history --hook-stage manual`.

### Quality gates

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs these checks on
pull requests and on `main`; run them locally before you push.

| Area     | Commands                                                                                                                                                                                                                |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Backend  | `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run lint-imports`, `uv run pytest`, coverage gate, pip-audit                                                                                  |
| Frontend | `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run test:coverage`, `npm audit`                                                                                                                       |
| Image    | hadolint, `check-dockerfile-versions.sh`, `docker build`, `image-smoke-test.sh`, `image-scan.sh` (Trivy): `.github/scripts/check.sh image`                                                                              |
| Hygiene  | `uv run --project backend --locked pre-commit run --all-files`, gitleaks over the full history, actionlint, hadolint, the path gate tests, the Dockerfile version check tests, the agent setup tests (`.claude/tests/`) |

CodeQL ([.github/workflows/codeql.yml](.github/workflows/codeql.yml)) analyses
Python and TypeScript on every pull request, on `main` and weekly. Dependabot
([.github/dependabot.yml](.github/dependabot.yml)) proposes dependency updates
weekly. All GitHub Actions are pinned to commit SHAs.

On pull requests the checks are gated by path: a job or CodeQL language only
runs when the PR touches its area, as decided by
[.github/scripts/changed-areas.sh](.github/scripts/changed-areas.sh). `hygiene`
always runs. A gated check still reports, as skipped (`backend`, `frontend`, `image`) or
as a quick pass (CodeQL), so the required checks on `main` never wait. Pushes to
`main`, the weekly CodeQL run and manual runs check everything.

| Area                           | Runs when a pull request changes                                                                                                    |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| `backend`                      | `backend/`, `dev/keycloak/` (the shared Keycloak realm the backend integration tests import), `.gitignore`, `ci.yml`                |
| `frontend`                     | `frontend/`, `e2e/`, `.nvmrc`, `.prettierrc.json`, `.prettierignore`, `.editorconfig`, `.gitignore`, `ci.yml`                       |
| `image`                        | `backend/`, `frontend/`, `Dockerfile`, `.dockerignore`, `.nvmrc`, `.github/tools/trivy/`, the image scripts, `ci.yml`               |
| CodeQL (python)                | `backend/`, any `*.py` or `*.pyi` file, `codeql.yml`                                                                                |
| CodeQL (javascript-typescript) | `frontend/`, `e2e/`, any JavaScript, TypeScript or HTML file (CodeQL scans the whole repository, `.claude/` included), `codeql.yml` |
| `hygiene`                      | always                                                                                                                              |

Changing `changed-areas.sh` itself runs every gated check. `.pre-commit-config.yaml`
is only used by `hygiene`, which always runs. `hygiene` also runs
[.github/scripts/test-changed-areas.sh](.github/scripts/test-changed-areas.sh),
the tests for the gate itself; run it locally after changing the mapping.

### Coverage gate

The domain and application layers need at least 85% coverage (lines and branches
combined, design D9). The gate runs after pytest in `backend/`:

```sh
uv run pytest
uv run coverage report --include="src/podiumd_admin/domain/*,src/podiumd_admin/application/*" --fail-under=85
```

It is already enforced in CI. While `domain/` and `application/` hold only empty
packages it passes trivially (empty modules are skipped); the first domain or
application module without enough tests fails it, because coverage also reports
modules no test imports. Adapters are not part of the gate.

## Licence

Licensed under the [EUPL-1.2](LICENSE). See also [publiccode.yml](publiccode.yml).
