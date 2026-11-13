#!/usr/bin/env bash
# Scan a container image with Trivy (task 10.2, ADR 0007).
#
# Usage: image-scan.sh IMAGE
#
# Fails on a HIGH or CRITICAL vulnerability that has a fixed version, and on a
# secret found in the image. Trivy runs as the image pinned in
# .github/tools/trivy/Dockerfile, its single version source, so CI and local
# runs use the same Trivy. The image is handed over as a `docker save` archive,
# so the Trivy container gets no access to the Docker socket. The vulnerability
# database is cached in the Docker volume podiumd-admin-trivy-cache.
#
# Needs Docker.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 IMAGE" >&2
  exit 2
fi
image=$1

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
trivy_image=$(awk 'toupper($1) == "FROM" { print $2; exit }' "${root}/.github/tools/trivy/Dockerfile")
if [[ ! ${trivy_image} =~ @sha256:[0-9a-f]{64}$ ]]; then
  echo "no digest-pinned FROM image in .github/tools/trivy/Dockerfile" >&2
  exit 1
fi

work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT
docker save --output "${work}/image.tar" "${image}"
# The Trivy container runs as root and only needs to read the archive.
chmod a+rx "${work}"
chmod a+r "${work}/image.tar"

echo "Scanning ${image} with ${trivy_image}" >&2
docker run --rm \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --volume "${work}:/scan:ro" \
  --volume podiumd-admin-trivy-cache:/root/.cache/trivy \
  "${trivy_image}" \
  image \
  --input /scan/image.tar \
  --scanners vuln,secret \
  --severity HIGH,CRITICAL \
  --ignore-unfixed \
  --exit-code 1 \
  --no-progress
