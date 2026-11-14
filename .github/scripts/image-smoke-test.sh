#!/usr/bin/env bash
# Smoke test of the container image (task 10.2, ADR 0007, issue #32).
#
# Usage: image-smoke-test.sh IMAGE
#
# Starts IMAGE the way the Helm chart runs it: as uid 1000, with a read-only
# root filesystem, /tmp as the only writable path, all capabilities dropped and
# no privilege escalation. The settings are the required PODIUMD_ADMIN_* values
# with Onsdorp test data; the database is never contacted, because /healthz
# does not need it. Then it checks:
#
# - the image's user and command, including `--no-proxy-headers` (issue #32);
# - GET /healthz answers 200 {"status":"ok"} from the host;
# - the process runs as uid 1000 and can write to /tmp only;
# - a request from 127.0.0.1 with X-Forwarded-For is logged with its peer
#   address: uvicorn's default --proxy-headers trusts 127.0.0.1 (a mesh
#   sidecar) and would log, and hand the app, the forged address instead.
#
# Needs Docker and curl. Exits non-zero on the first failed check and prints
# the container log.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 IMAGE" >&2
  exit 2
fi
image=$1

expected_user=1000:1000
expected_cmd='["uvicorn","--factory","--no-proxy-headers","--host","0.0.0.0","--port","8000","podiumd_admin.main:create_app_from_environment"]'
forged_ip=203.0.113.7

fail() {
  echo "FAIL $*" >&2
  exit 1
}

echo "Checking the image configuration of ${image}"
user=$(docker image inspect --format '{{.Config.User}}' "${image}")
[[ ${user} == "${expected_user}" ]] || fail "image user is '${user}', expected '${expected_user}'"
cmd=$(docker image inspect --format '{{json .Config.Cmd}}' "${image}")
[[ ${cmd} == "${expected_cmd}" ]] || fail "image command is ${cmd}, expected ${expected_cmd}"
entrypoint=$(docker image inspect --format '{{json .Config.Entrypoint}}' "${image}")
[[ ${entrypoint} == null || ${entrypoint} == '[]' ]] || fail "image has an entrypoint ${entrypoint}; the command must run directly"

# A fresh Fernet key (32 random bytes, url-safe base64) for this run only.
session_key=$(head -c 32 /dev/urandom | base64 | tr '+/' '-_')

container=$(docker run --detach \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --publish 127.0.0.1::8000 \
  --env PODIUMD_ADMIN_ENVIRONMENT_MUNICIPALITY=Onsdorp \
  --env PODIUMD_ADMIN_ENVIRONMENT_STAGE=test \
  --env PODIUMD_ADMIN_PUBLIC_HOSTNAME=admin.podiumd.onsdorp.example \
  --env PODIUMD_ADMIN_OIDC_ISSUER=https://keycloak.onsdorp.example/realms/podiumd \
  --env PODIUMD_ADMIN_OIDC_CLIENT_ID=podiumd-admin \
  --env PODIUMD_ADMIN_OIDC_CLIENT_SECRET=smoke-test-client-secret \
  --env PODIUMD_ADMIN_DATABASE_APP_URL=postgresql+psycopg://podiumd_admin_app:smoke-test@db.onsdorp.example:5432/podiumd_admin \
  --env "PODIUMD_ADMIN_SESSION_ENCRYPTION_KEYS=${session_key}" \
  "${image}")

cleanup() {
  local status=$?
  if [[ ${status} -ne 0 ]]; then
    echo "--- container log ---" >&2
    docker logs "${container}" >&2 || echo "(could not read the container log)" >&2
  fi
  docker rm --force "${container}" >/dev/null || echo "could not remove container ${container}" >&2
  exit "${status}"
}
trap cleanup EXIT

port=$(docker port "${container}" 8000/tcp | head -n 1)
port=${port##*:}
echo "Waiting for /healthz on 127.0.0.1:${port}"
body=""
for _ in $(seq 1 30); do
  if [[ $(docker inspect --format '{{.State.Running}}' "${container}") != true ]]; then
    fail "the container stopped"
  fi
  if body=$(curl --fail --silent --show-error --max-time 2 "http://127.0.0.1:${port}/healthz" 2>&1); then
    break
  fi
  body=""
  sleep 1
done
[[ -n ${body} ]] || fail "/healthz did not answer within 30 seconds"
[[ ${body} == '{"status":"ok"}' ]] || fail "/healthz answered ${body}"
echo "ok   /healthz answers ${body} with a read-only root filesystem"

# docker exec runs as the image user; python is the only tool the checks need.
probe() {
  docker exec "${container}" python -I -c "$1"
}

uid=$(probe 'print(open("/proc/1/status").read().split("Uid:")[1].split()[0])')
[[ ${uid} == 1000 ]] || fail "the server process runs as uid ${uid}, expected 1000"
echo "ok   the server process runs as uid 1000"

probe '
import tempfile
with tempfile.NamedTemporaryFile(dir="/tmp") as f:
    f.write(b"x")
for path in ("/app/smoke-test", "/smoke-test", "/app/.venv/smoke-test"):
    try:
        open(path, "w")
    except OSError:
        continue
    raise SystemExit(f"{path} is writable")
' || fail "/tmp must be the only writable path"
echo "ok   /tmp is writable and the root filesystem is not"

probe "
import urllib.request
request = urllib.request.Request(
    'http://127.0.0.1:8000/healthz', headers={'X-Forwarded-For': '${forged_ip}'}
)
urllib.request.urlopen(request, timeout=5).read()
" || fail "the request with X-Forwarded-For failed"
# Give the access log line a moment to reach stdout.
logs=""
for _ in $(seq 1 10); do
  logs=$(docker logs "${container}" 2>&1)
  if grep -q '127\.0\.0\.1:[0-9]* - \\"GET /healthz' <<<"${logs}" || grep -q "${forged_ip}" <<<"${logs}"; then
    break
  fi
  sleep 0.5
done
if grep -q "${forged_ip}" <<<"${logs}"; then
  fail "uvicorn replaced the peer address with X-Forwarded-For (${forged_ip}): proxy headers must be off"
fi
grep -q '127\.0\.0\.1:[0-9]* - \\"GET /healthz' <<<"${logs}" ||
  fail "no access log line for the request from 127.0.0.1"
echo "ok   X-Forwarded-For from 127.0.0.1 is not applied by uvicorn (--no-proxy-headers)"

echo "image smoke test passed"
