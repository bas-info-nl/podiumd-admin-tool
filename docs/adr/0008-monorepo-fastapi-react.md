# Monorepo with a FastAPI backend and a React frontend in one image

One repository holds `backend/`, `frontend/`, `charts/podiumd-admin/` and `docs/`. The backend is Python 3.12+ with FastAPI, the official `kubernetes` client, SQLAlchemy 2 + Alembic, Authlib (OIDC) and structlog (JSON logs), fully typed with mypy strict. The frontend is React + TypeScript with Vite and TanStack Query. Its API client is generated from the backend's OpenAPI spec. One container image is shipped: the backend serves the built frontend and holds the OIDC session, so the browser never holds tokens.

We chose a Python backend over a TypeScript full-stack setup to match the Python/Django skills of the PodiumD Component ecosystem, and because the Kubernetes Python client is mature. Shipping one image keeps the Helm chart and RBAC minimal.
