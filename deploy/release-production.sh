#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_DIR="${PARLOQ_COMPOSE_DIR:-/www/server/panel/data/compose/parloq-flow}"
COMPOSE_FILE="${COMPOSE_DIR}/docker-compose.yaml"
ENV_FILE="${COMPOSE_DIR}/.env"
GITHUB_TOKEN_FILE="${COMPOSE_DIR}/github-token"
MANAGED_COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.production.yml"

log() {
  printf '[parloq-release] %s\n' "$*"
}

die() {
  printf '[parloq-release] ERROR: %s\n' "$*" >&2
  exit 1
}

for command_name in git docker flock curl mktemp; do
  command -v "${command_name}" >/dev/null 2>&1 || die "${command_name} is required"
done

[ -d "${COMPOSE_DIR}" ] || die "BaoTa Compose directory does not exist: ${COMPOSE_DIR}"
[ -f "${COMPOSE_FILE}" ] || die "BaoTa Compose file does not exist: ${COMPOSE_FILE}"
[ -f "${ENV_FILE}" ] || die "production env file does not exist: ${ENV_FILE}"
[ -f "${MANAGED_COMPOSE_FILE}" ] || die "managed Compose template is missing"

token_candidate=""
askpass_file=""
cleanup_local_files() {
  if [ -n "${token_candidate}" ]; then
    rm -f -- "${token_candidate}"
  fi
  if [ -n "${askpass_file}" ]; then
    rm -f -- "${askpass_file}"
  fi
}
trap cleanup_local_files EXIT

configure_github_token() {
  if ! IFS= read -r -s -p 'GitHub fine-grained token（输入不会显示）: ' github_token; then
    printf '\n'
    die "GitHub token input was cancelled"
  fi
  printf '\n'
  if [ "${#github_token}" -lt 20 ] || [ "${#github_token}" -gt 512 ]; then
    unset github_token
    die "GitHub token has an invalid length"
  fi
  case "${github_token}" in
    *[[:space:]]*)
      unset github_token
      die "GitHub token must not contain whitespace"
      ;;
  esac
  token_candidate="$(mktemp "${GITHUB_TOKEN_FILE}.candidate.XXXXXX")"
  umask 077
  printf '%s' "${github_token}" >"${token_candidate}"
  unset github_token
  chmod 600 "${token_candidate}"
  mv "${token_candidate}" "${GITHUB_TOKEN_FILE}"
  token_candidate=""
  log "GitHub Token 已保存到 ${GITHUB_TOKEN_FILE}"
}

if [ ! -s "${GITHUB_TOKEN_FILE}" ]; then
  log "服务器尚未配置 GitHub Token，首次更新需要输入一次。"
  configure_github_token
fi
chmod 600 "${GITHUB_TOKEN_FILE}"

cd "${PROJECT_DIR}"
[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] || die "production updates must run from main"
if ! git diff --quiet || ! git diff --cached --quiet; then
  die "working tree has tracked changes"
fi
if [ -n "$(git ls-files --others --exclude-standard)" ]; then
  die "working tree has untracked files"
fi

if [ "${PARLOQ_RELEASE_AFTER_GIT_UPDATE:-0}" != 1 ]; then
  askpass_file="$(mktemp /tmp/parloq-git-askpass.XXXXXX)"
  cleanup_askpass() {
    rm -f -- "${askpass_file}"
    askpass_file=""
  }
  chmod 700 "${askpass_file}"
  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'case "$1" in' \
    '  *Username*) printf "%s\n" "x-access-token" ;;' \
    '  *Password*) tr -d "\r\n" <"${PARLOQ_GITHUB_TOKEN_FILE:?}" ;;' \
    '  *) exit 1 ;;' \
    'esac' >"${askpass_file}"
  fetch_main() {
    GIT_ASKPASS="${askpass_file}" \
      GIT_TERMINAL_PROMPT=0 \
      PARLOQ_GITHUB_TOKEN_FILE="${GITHUB_TOKEN_FILE}" \
      git fetch origin main
  }
  if ! fetch_main; then
    log "Git 更新失败，Token 可能已失效，请重新输入后重试。"
    configure_github_token
    fetch_main || die "could not fetch origin/main with the configured GitHub token"
  fi
  git merge --ff-only origin/main
  cleanup_askpass
  export PARLOQ_RELEASE_AFTER_GIT_UPDATE=1
  exec bash "${SCRIPT_DIR}/release-production.sh"
fi

head_sha="$(git rev-parse HEAD)"
[ "${head_sha}" = "$(git rev-parse origin/main)" ] || die "HEAD is not equal to origin/main"
short_sha="$(git rev-parse --short=12 HEAD)"
api_image="parloq-flow-api-server:${short_sha}"
web_image="parloq-flow-web-server:${short_sha}"
gateway_image="parloq-flow-wa-gateway-server:${short_sha}"

lock_file="${COMPOSE_DIR}/.release.lock"
exec 9>"${lock_file}"
flock -n 9 || die "another Parloq Flow update is already running"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
env_backup="${ENV_FILE}.backup-server-${short_sha}-${timestamp}"
compose_backup="${COMPOSE_FILE}.backup-server-${short_sha}-${timestamp}"
env_candidate="${ENV_FILE}.candidate-server-${short_sha}-$$"
compose_candidate="${COMPOSE_FILE}.candidate-server-${short_sha}-$$"
switched=0

rollback() {
  code=$?
  trap - ERR
  rm -f -- "${env_candidate}" "${compose_candidate}"
  if [ "${switched}" = 1 ] && [ -f "${env_backup}" ] && [ -f "${compose_backup}" ]; then
    log "更新失败，正在恢复上一版 Compose 配置和镜像。"
    cp -p "${env_backup}" "${ENV_FILE}"
    cp -p "${compose_backup}" "${COMPOSE_FILE}"
    cd "${COMPOSE_DIR}"
    PARLOQ_APP_PULL_POLICY=never docker compose \
      --env-file "${ENV_FILE}" \
      -f "${COMPOSE_FILE}" \
      up -d --no-deps --wait --wait-timeout 600 \
      wa-gateway api api-worker web || true
  fi
  die "update failed with exit code ${code}"
}
trap rollback ERR

cp -p "${ENV_FILE}" "${env_backup}"
cp -p "${COMPOSE_FILE}" "${compose_backup}"
cp -p "${ENV_FILE}" "${env_candidate}"
cp "${MANAGED_COMPOSE_FILE}" "${compose_candidate}"
chmod --reference="${COMPOSE_FILE}" "${compose_candidate}"

update_env() {
  key="$1"
  value="$2"
  if grep -q "^${key}=" "${env_candidate}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${env_candidate}"
  else
    printf '%s=%s\n' "${key}" "${value}" >>"${env_candidate}"
  fi
}

update_env PARLOQ_SOURCE_ROOT "${PROJECT_DIR}"
update_env PARLOQ_GIT_REF "${head_sha}"
update_env PARLOQ_APP_PULL_POLICY build
update_env PARLOQ_API_IMAGE "${api_image}"
update_env PARLOQ_WEB_IMAGE "${web_image}"
update_env PARLOQ_WA_GATEWAY_IMAGE "${gateway_image}"
chmod 600 "${env_candidate}"

docker compose \
  --env-file "${env_candidate}" \
  -f "${compose_candidate}" \
  config --quiet

switched=1
mv "${env_candidate}" "${ENV_FILE}"
mv "${compose_candidate}" "${COMPOSE_FILE}"

cd "${COMPOSE_DIR}"
log "服务器开始构建 ${short_sha} 并更新宝塔 Compose 项目。"
docker compose \
  --env-file "${ENV_FILE}" \
  -f "${COMPOSE_FILE}" \
  up -d --build --remove-orphans --wait --wait-timeout 600

verify_service() {
  service="$1"
  expected_image="$2"
  container_id="$(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" ps -q "${service}")"
  [ -n "${container_id}" ]
  actual_image="$(docker inspect --format '{{.Config.Image}}' "${container_id}")"
  revision="$(docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "${container_id}")"
  [ "${actual_image}" = "${expected_image}" ]
  [ "${revision}" = "${head_sha}" ]
}

verify_service api "${api_image}"
verify_service api-worker "${api_image}"
verify_service web "${web_image}"
verify_service wa-gateway "${gateway_image}"
curl -fsS --max-time 20 http://127.0.0.1:18100/healthz >/dev/null
curl -fsS --max-time 20 http://127.0.0.1:18100/readyz >/dev/null

trap - ERR
log "${head_sha} 构建和更新完成。"
log "配置备份：${env_backup}"
log "Compose 备份：${compose_backup}"
