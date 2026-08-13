#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REMOTE_HOST="${PARLOQ_PRODUCTION_HOST:-root@216.106.185.81}"
REMOTE_DIR="${PARLOQ_PRODUCTION_DIR:-/www/server/panel/data/compose/parloq-flow}"
COMPOSE_FILE="${REMOTE_DIR}/docker-compose.yaml"
ENV_FILE="${REMOTE_DIR}/.env"

die() {
  printf '[parloq-release] ERROR: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[parloq-release] %s\n' "$*"
}

for command_name in git docker ssh scp shasum gzip; do
  command -v "${command_name}" >/dev/null 2>&1 || die "${command_name} is required"
done

cd "${PROJECT_DIR}"
if ! git diff --quiet || ! git diff --cached --quiet; then
  die "working tree has tracked changes"
fi
if [ -n "$(git ls-files --others --exclude-standard)" ]; then
  die "working tree has untracked files"
fi
branch="$(git rev-parse --abbrev-ref HEAD)"
[ "${branch}" = "main" ] || die "production releases must run from main"
git fetch origin main
head_sha="$(git rev-parse HEAD)"
origin_sha="$(git rev-parse origin/main)"
[ "${head_sha}" = "${origin_sha}" ] || die "HEAD is not equal to origin/main"
short_sha="$(git rev-parse --short=12 HEAD)"

api_image="parloq-flow-api-local:${short_sha}"
web_image="parloq-flow-web-local:${short_sha}"
gateway_image="parloq-flow-wa-gateway-local:${short_sha}"

log "build immutable images for ${head_sha}"
bash "${SCRIPT_DIR}/build-production-images.sh"

transfer_dir="$(mktemp -d)"
archive="${transfer_dir}/parloq-flow-images-${short_sha}.tar.gz"
checksum="${archive}.sha256"
remote_archive="/tmp/$(basename "${archive}")"
remote_checksum="${remote_archive}.sha256"
cleanup() {
  rm -rf "${transfer_dir}"
}
trap cleanup EXIT

log "export images"
docker image save "${api_image}" "${web_image}" "${gateway_image}" | gzip -1 >"${archive}"
(cd "${transfer_dir}" && shasum -a 256 "$(basename "${archive}")" >"$(basename "${checksum}")")

log "upload image archive"
scp "${archive}" "${checksum}" "${REMOTE_HOST}:/tmp/"

log "verify, load, migrate, and switch application services"
ssh -o BatchMode=yes "${REMOTE_HOST}" bash -s -- \
  "${head_sha}" "${short_sha}" "${remote_archive}" "${remote_checksum}" \
  "${REMOTE_DIR}" "${COMPOSE_FILE}" "${ENV_FILE}" \
  "${api_image}" "${web_image}" "${gateway_image}" <<'REMOTE_SCRIPT'
set -Eeuo pipefail
commit_sha="$1"
short_sha="$2"
archive="$3"
checksum="$4"
remote_dir="$5"
compose_file="$6"
env_file="$7"
api_image="$8"
web_image="$9"
gateway_image="${10}"

cd /tmp
sha256sum -c "$(basename "${checksum}")"
docker image load <"${archive}"

[ -f "${compose_file}" ] || { echo "missing ${compose_file}" >&2; exit 1; }
[ -f "${env_file}" ] || { echo "missing ${env_file}" >&2; exit 1; }
backup="${env_file}.backup-${short_sha}-$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "${env_file}" "${backup}"

update_env() {
  key="$1"
  value="$2"
  if grep -q "^${key}=" "${env_file}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${env_file}"
  else
    printf '%s=%s\n' "${key}" "${value}" >>"${env_file}"
  fi
}
update_env PARLOQ_API_IMAGE "${api_image}"
update_env PARLOQ_WEB_IMAGE "${web_image}"
update_env PARLOQ_WA_GATEWAY_IMAGE "${gateway_image}"
chmod 600 "${env_file}"

cd "${remote_dir}"
docker compose --env-file "${env_file}" -f "${compose_file}" config --quiet
docker compose --env-file "${env_file}" -f "${compose_file}" up -d postgres redis
docker compose --env-file "${env_file}" -f "${compose_file}" run --rm migrate
docker compose --env-file "${env_file}" -f "${compose_file}" up -d --no-deps wa-gateway api api-worker web
docker compose --env-file "${env_file}" -f "${compose_file}" ps

for attempt in $(seq 1 45); do
  if curl -fsS http://127.0.0.1:18100/healthz >/dev/null; then
    break
  fi
  [ "${attempt}" -lt 45 ] || { echo "health check failed" >&2; exit 1; }
  sleep 2
done

for service in api web wa-gateway; do
  container_id="$(docker compose --env-file "${env_file}" -f "${compose_file}" ps -q "${service}")"
  revision="$(docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "${container_id}")"
  [ "${revision}" = "${commit_sha}" ] || { echo "revision mismatch for ${service}" >&2; exit 1; }
done

rm -f "${archive}" "${checksum}"
echo "release ${commit_sha} healthy; env backup: ${backup}"
REMOTE_SCRIPT

log "release ${head_sha} completed"
