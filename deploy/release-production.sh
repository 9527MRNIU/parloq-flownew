#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BAOTA_ENV_FILE="${PARLOQ_BAOTA_ENV_FILE:-${PROJECT_DIR}/.env.baota.local}"

die() {
  printf '[parloq-release] ERROR: %s\n' "$*" >&2
  exit 1
}

for command_name in git docker python3 shasum; do
  command -v "${command_name}" >/dev/null 2>&1 || die "${command_name} is required"
done

cd "${PROJECT_DIR}"
if ! git diff --quiet || ! git diff --cached --quiet; then
  die "working tree has tracked changes"
fi
if [ -n "$(git ls-files --others --exclude-standard)" ]; then
  die "working tree has untracked files"
fi
[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] || die "production releases must run from main"
git fetch origin main
head_sha="$(git rev-parse HEAD)"
[ "${head_sha}" = "$(git rev-parse origin/main)" ] || die "HEAD is not equal to origin/main"
short_sha="$(git rev-parse --short=12 HEAD)"

api_image="parloq-flow-api-local:${short_sha}"
web_image="parloq-flow-web-local:${short_sha}"
gateway_image="parloq-flow-wa-gateway-local:${short_sha}"

python3 "${SCRIPT_DIR}/baota_api.py" --env-file "${BAOTA_ENV_FILE}" status
bash "${SCRIPT_DIR}/build-production-images.sh"

transfer_dir="$(mktemp -d)"
archive="${transfer_dir}/parloq-flow-images-${short_sha}.tar"
cleanup() {
  rm -rf "${transfer_dir}"
}
trap cleanup EXIT

docker image save "${api_image}" "${web_image}" "${gateway_image}" -o "${archive}"
checksum="$(shasum -a 256 "${archive}" | awk '{print $1}')"

python3 "${SCRIPT_DIR}/baota_api.py" --env-file "${BAOTA_ENV_FILE}" release \
  --archive "${archive}" \
  --checksum "${checksum}" \
  --commit "${head_sha}" \
  --short-sha "${short_sha}" \
  --api-image "${api_image}" \
  --web-image "${web_image}" \
  --gateway-image "${gateway_image}"

curl -fsS --max-time 20 https://center.parloq.com/healthz >/dev/null
printf '[parloq-release] release %s completed through BaoTa APIs\n' "${head_sha}"
