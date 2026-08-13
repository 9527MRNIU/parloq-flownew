#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

die() {
  printf '[parloq-build] ERROR: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[parloq-build] %s\n' "$*"
}

command -v git >/dev/null 2>&1 || die "git is required"
command -v docker >/dev/null 2>&1 || die "docker is required"
docker buildx version >/dev/null 2>&1 || die "docker buildx is required"

cd "${PROJECT_DIR}"
if ! git diff --quiet || ! git diff --cached --quiet; then
  die "working tree has tracked changes; commit them before a production build"
fi
if [ -n "$(git ls-files --others --exclude-standard)" ]; then
  die "working tree has untracked files; commit or remove them before a production build"
fi

commit_sha="${PARLOQ_BUILD_COMMIT:-$(git rev-parse HEAD)}"
short_sha="$(git rev-parse --short=12 "${commit_sha}")"
platform="${PARLOQ_BUILD_PLATFORM:-linux/amd64}"

api_image="parloq-flow-api-local:${short_sha}"
web_image="parloq-flow-web-local:${short_sha}"
gateway_image="parloq-flow-wa-gateway-local:${short_sha}"

log "commit: ${commit_sha}"
log "platform: ${platform}"

docker buildx build --platform "${platform}" --load \
  --build-arg "BUILD_VERSION=${commit_sha}" \
  -t "${api_image}" "${PROJECT_DIR}/apps/api"
docker buildx build --platform "${platform}" --load \
  --target production \
  --build-arg "BUILD_VERSION=${commit_sha}" \
  -t "${web_image}" "${PROJECT_DIR}/apps/web"
docker buildx build --platform "${platform}" --load \
  --build-arg "BUILD_VERSION=${commit_sha}" \
  -t "${gateway_image}" "${PROJECT_DIR}/services/wa-gateway-baileys"

log "built ${api_image}"
log "built ${web_image}"
log "built ${gateway_image}"
