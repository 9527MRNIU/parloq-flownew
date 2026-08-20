#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BAOTA_ENV_FILE="${PARLOQ_BAOTA_ENV_FILE:-${PROJECT_DIR}/.env.baota.local}"

log() {
  printf '[parloq-release] %s\n' "$*"
}

die() {
  printf '[parloq-release] ERROR: %s\n' "$*" >&2
  exit 1
}

for command_name in git docker python3 shasum mktemp; do
  command -v "${command_name}" >/dev/null 2>&1 || die "${command_name} is required"
done

cd "${PROJECT_DIR}"
[ "$(git branch --show-current)" = "main" ] \
  || die "production updates must run from main"
if ! git diff --quiet || ! git diff --cached --quiet; then
  die "working tree has tracked changes"
fi
if [ -n "$(git ls-files --others --exclude-standard)" ]; then
  die "working tree has untracked files"
fi

git fetch origin main
head_sha="$(git rev-parse HEAD)"
[ "${head_sha}" = "$(git rev-parse origin/main)" ] \
  || die "HEAD is not equal to origin/main"
short_sha="${head_sha:0:12}"

python3 "${SCRIPT_DIR}/baota_api.py" \
  --env-file "${BAOTA_ENV_FILE}" status

export PARLOQ_BUILD_COMMIT="${head_sha}"
export PARLOQ_BUILD_PLATFORM="linux/amd64"
bash "${SCRIPT_DIR}/build-production-images.sh"

built_api_image="parloq-flow-api-local:${short_sha}"
built_web_image="parloq-flow-web-local:${short_sha}"
built_gateway_image="parloq-flow-wa-gateway-local:${short_sha}"
api_image="parloq-flow-api-server:${short_sha}"
web_image="parloq-flow-web-server:${short_sha}"
gateway_image="parloq-flow-wa-gateway-server:${short_sha}"
docker image tag "${built_api_image}" "${api_image}"
docker image tag "${built_web_image}" "${web_image}"
docker image tag "${built_gateway_image}" "${gateway_image}"

release_temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/parloq-release.XXXXXX")"
archive="${release_temp_dir}/parloq-flow-${short_sha}.tar"
cleanup() {
  rm -f -- "${archive}"
  rmdir "${release_temp_dir}" 2>/dev/null || true
}
trap cleanup EXIT

log "正在导出 linux/amd64 镜像 ${short_sha}。"
docker image save --output "${archive}" \
  "${api_image}" "${web_image}" "${gateway_image}"
checksum="$(shasum -a 256 "${archive}")"
checksum="${checksum%% *}"

python3 "${SCRIPT_DIR}/baota_api.py" \
  --env-file "${BAOTA_ENV_FILE}" release \
  --archive "${archive}" \
  --checksum "${checksum}" \
  --commit "${head_sha}" \
  --short-sha "${short_sha}" \
  --api-image "${api_image}" \
  --web-image "${web_image}" \
  --gateway-image "${gateway_image}" \
  --compose-file "${SCRIPT_DIR}/docker-compose.production.yml"

log "${head_sha} 已通过宝塔 API 发布完成。"
