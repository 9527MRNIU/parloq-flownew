#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RELEASE_SOURCE_DIR="${PARLOQ_RELEASE_SOURCE_DIR:-${PROJECT_DIR}.release-source}"
COMPOSE_DIR="${PARLOQ_COMPOSE_DIR:-/www/server/panel/data/compose/parloq-flow}"
COMPOSE_FILE="${COMPOSE_DIR}/docker-compose.yaml"
ENV_FILE="${COMPOSE_DIR}/.env"
GITHUB_TOKEN_FILE="${COMPOSE_DIR}/github-token"
IMAGE_RETENTION="${PARLOQ_IMAGE_RETENTION:-3}"
BUILD_CACHE_MAX_AGE="${PARLOQ_BUILD_CACHE_MAX_AGE:-168h}"
ORIGINAL_ARGUMENTS=("$@")

log() {
  printf '[parloq-release] %s\n' "$*"
}

die() {
  printf '[parloq-release] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: bash deploy/release-production.sh [--branch <remote-branch>]

Without --branch, an interactive terminal shows the remote branches and uses main by default.
Non-interactive runs without --branch also use main.
EOF
}

release_branch_argument=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --branch)
      [ "$#" -ge 2 ] || die "--branch requires a remote branch name"
      [ -z "${release_branch_argument}" ] || die "--branch may only be provided once"
      release_branch_argument="$2"
      shift 2
      ;;
    --branch=*)
      [ -z "${release_branch_argument}" ] || die "--branch may only be provided once"
      release_branch_argument="${1#--branch=}"
      [ -n "${release_branch_argument}" ] || die "--branch requires a remote branch name"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

for command_name in git docker flock curl mktemp sort; do
  command -v "${command_name}" >/dev/null 2>&1 || die "${command_name} is required"
done

case "${IMAGE_RETENTION}" in
  ''|*[!0-9]*) die "PARLOQ_IMAGE_RETENTION must be a positive integer" ;;
esac
[ "${IMAGE_RETENTION}" -gt 0 ] || die "PARLOQ_IMAGE_RETENTION must be greater than zero"

[ -d "${COMPOSE_DIR}" ] || die "BaoTa Compose directory does not exist: ${COMPOSE_DIR}"
[ -f "${COMPOSE_FILE}" ] || die "BaoTa Compose file does not exist: ${COMPOSE_FILE}"
[ -f "${ENV_FILE}" ] || die "production env file does not exist: ${ENV_FILE}"
case "${RELEASE_SOURCE_DIR}" in
  /*) ;;
  *) die "PARLOQ_RELEASE_SOURCE_DIR must be an absolute path" ;;
esac
[ "${RELEASE_SOURCE_DIR}" != "${PROJECT_DIR}" ] \
  || die "release source directory must differ from the main checkout"
case "${RELEASE_SOURCE_DIR}/" in
  "${PROJECT_DIR}/"*) die "release source directory must not be inside the main checkout" ;;
esac

token_candidate=""
askpass_file=""
management_origin_candidate=""
cleanup_local_files() {
  if [ -n "${token_candidate}" ]; then
    rm -f -- "${token_candidate}"
  fi
  if [ -n "${askpass_file}" ]; then
    rm -f -- "${askpass_file}"
  fi
  if [ -n "${management_origin_candidate}" ]; then
    rm -f -- "${management_origin_candidate}"
  fi
}
trap cleanup_local_files EXIT

create_git_askpass() {
  [ -z "${askpass_file}" ] || return 0
  askpass_file="$(mktemp /tmp/parloq-git-askpass.XXXXXX)"
  chmod 700 "${askpass_file}"
  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'case "$1" in' \
    '  *Username*) printf "%s\n" "x-access-token" ;;' \
    '  *Password*) tr -d "\r\n" <"${PARLOQ_GITHUB_TOKEN_FILE:?}" ;;' \
    '  *) exit 1 ;;' \
    'esac' >"${askpass_file}"
}

git_with_auth() {
  GIT_ASKPASS="${askpass_file}" \
    GIT_TERMINAL_PROMPT=0 \
    PARLOQ_GITHUB_TOKEN_FILE="${GITHUB_TOKEN_FILE}" \
    git "$@"
}

normalize_management_origin() {
  raw_origin="$1"
  case "${raw_origin}" in
    ''|*[[:space:]]*|*'?'*|*'#'*|*'@'*) return 1 ;;
  esac
  raw_origin="$(printf '%s' "${raw_origin}" | tr '[:upper:]' '[:lower:]')"
  case "${raw_origin}" in
    https://*) management_host="${raw_origin#https://}" ;;
    *://*) return 1 ;;
    *) management_host="${raw_origin}" ;;
  esac
  case "${management_host}" in
    ''|*'/'*|*':'*) return 1 ;;
  esac
  hostname_pattern='^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'
  if [ "${#management_host}" -gt 253 ] \
    || ! printf '%s' "${management_host}" | grep -Eq "${hostname_pattern}"; then
    return 1
  fi
  printf 'https://%s' "${management_host}"
}

read_env_value() {
  key="$1"
  awk -v key="${key}" 'index($0, key "=") == 1 { sub("^[^=]*=", ""); print; exit }' "${ENV_FILE}"
}

persist_management_origin() {
  value="$1"
  management_origin_candidate="$(mktemp "${ENV_FILE}.candidate-management-origin.XXXXXX")"
  cp -p "${ENV_FILE}" "${management_origin_candidate}"
  if grep -q '^MANAGEMENT_ORIGIN=' "${management_origin_candidate}"; then
    sed -i "s|^MANAGEMENT_ORIGIN=.*|MANAGEMENT_ORIGIN=${value}|" "${management_origin_candidate}"
  else
    printf '%s=%s\n' MANAGEMENT_ORIGIN "${value}" >>"${management_origin_candidate}"
  fi
  chmod 600 "${management_origin_candidate}"
  mv "${management_origin_candidate}" "${ENV_FILE}"
  management_origin_candidate=""
}

configure_management_origin() {
  if ! IFS= read -r -p '管理后台域名（例如 center.parloq.com）: ' origin_input; then
    printf '\n'
    die "management origin input was cancelled"
  fi
  if ! normalized_origin="$(normalize_management_origin "${origin_input}")"; then
    unset origin_input
    die "management origin must be a valid hostname or HTTPS origin without a port or path"
  fi
  unset origin_input
  persist_management_origin "${normalized_origin}"
  management_origin="${normalized_origin}"
  log "管理后台域名已保存到 ${ENV_FILE}"
}

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

management_origin="$(read_env_value MANAGEMENT_ORIGIN)"
if [ -z "${management_origin}" ]; then
  log "服务器尚未配置管理后台域名，首次更新需要输入一次。"
  configure_management_origin
elif ! normalized_origin="$(normalize_management_origin "${management_origin}")" \
  || [ "${normalized_origin}" != "${management_origin}" ]; then
  die "MANAGEMENT_ORIGIN in ${ENV_FILE} is invalid; expected https://example.com"
fi
management_host="${management_origin#https://}"

cd "${PROJECT_DIR}"
[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] || die "production updates must run from main"
if ! git diff --quiet || ! git diff --cached --quiet; then
  die "working tree has tracked changes"
fi
if [ -n "$(git ls-files --others --exclude-standard)" ]; then
  die "working tree has untracked files"
fi

create_git_askpass

if [ "${PARLOQ_RELEASE_AFTER_GIT_UPDATE:-0}" != 1 ]; then
  fetch_main() {
    git_with_auth fetch --no-tags origin main
  }
  if ! fetch_main; then
    log "Git 更新失败，Token 可能已失效，请重新输入后重试。"
    configure_github_token
    fetch_main || die "could not fetch origin/main with the configured GitHub token"
  fi
  git merge --ff-only origin/main
  rm -f -- "${askpass_file}"
  askpass_file=""
  export PARLOQ_RELEASE_AFTER_GIT_UPDATE=1
  exec bash "${SCRIPT_DIR}/release-production.sh" "${ORIGINAL_ARGUMENTS[@]}"
fi

[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] \
  || die "HEAD is not equal to origin/main"

load_remote_branches() {
  local remote_output=""
  local branch_name=""
  local ref_name=""
  local _object_id=""
  local found_main=0
  local discovered_branches=()
  local sorted_branches=()

  if ! remote_output="$(git_with_auth ls-remote --heads origin)"; then
    die "could not list remote branches with the configured GitHub token"
  fi
  while IFS=$'\t' read -r _object_id ref_name; do
    case "${ref_name}" in
      refs/heads/*) branch_name="${ref_name#refs/heads/}" ;;
      *) continue ;;
    esac
    git check-ref-format --branch "${branch_name}" >/dev/null 2>&1 || continue
    discovered_branches+=("${branch_name}")
    [ "${branch_name}" != "main" ] || found_main=1
  done <<<"${remote_output}"

  [ "${found_main}" = 1 ] || die "origin/main was not found in the remote branch list"
  mapfile -t sorted_branches < <(printf '%s\n' "${discovered_branches[@]}" | LC_ALL=C sort -u)
  REMOTE_BRANCHES=("main")
  for branch_name in "${sorted_branches[@]}"; do
    [ "${branch_name}" = "main" ] || REMOTE_BRANCHES+=("${branch_name}")
  done
}

remote_branch_exists() {
  local expected="$1"
  local branch_name=""
  for branch_name in "${REMOTE_BRANCHES[@]}"; do
    [ "${branch_name}" != "${expected}" ] || return 0
  done
  return 1
}

select_release_branch() {
  local selection=""
  local branch_name=""
  local choice_number=1

  if [ -n "${release_branch_argument}" ]; then
    remote_branch_exists "${release_branch_argument}" \
      || die "remote branch does not exist: ${release_branch_argument}"
    release_branch="${release_branch_argument}"
    return
  fi
  if [ ! -t 0 ]; then
    release_branch="main"
    log "非交互运行未指定 --branch，默认发布 main。"
    return
  fi

  printf '可发布的远程分支：\n'
  for branch_name in "${REMOTE_BRANCHES[@]}"; do
    if [ "${branch_name}" = "main" ]; then
      printf '  %d) %s（默认）\n' "${choice_number}" "${branch_name}"
    else
      printf '  %d) %s\n' "${choice_number}" "${branch_name}"
    fi
    choice_number=$((choice_number + 1))
  done
  if ! IFS= read -r -p '请选择分支编号或输入分支名，直接回车发布 main: ' selection; then
    printf '\n'
    die "branch selection was cancelled"
  fi
  if [ -z "${selection}" ]; then
    release_branch="main"
    return
  fi
  if remote_branch_exists "${selection}"; then
    release_branch="${selection}"
    return
  fi
  choice_number=1
  for branch_name in "${REMOTE_BRANCHES[@]}"; do
    if [ "${selection}" = "${choice_number}" ]; then
      release_branch="${branch_name}"
      return
    fi
    choice_number=$((choice_number + 1))
  done
  die "invalid remote branch selection: ${selection}"
}

resolve_common_git_dir() {
  local checkout_dir="$1"
  local common_dir=""
  common_dir="$(git -C "${checkout_dir}" rev-parse --git-common-dir)" || return 1
  case "${common_dir}" in
    /*) (cd "${common_dir}" && pwd -P) ;;
    *) (cd "${checkout_dir}/${common_dir}" && pwd -P) ;;
  esac
}

prepare_release_source() {
  local project_common_dir=""
  local release_common_dir=""

  if [ -e "${RELEASE_SOURCE_DIR}" ]; then
    [ -d "${RELEASE_SOURCE_DIR}" ] || die "release source path is not a directory: ${RELEASE_SOURCE_DIR}"
    [ ! -L "${RELEASE_SOURCE_DIR}" ] || die "release source directory must not be a symlink"
    project_common_dir="$(resolve_common_git_dir "${PROJECT_DIR}")" \
      || die "could not resolve the main checkout Git directory"
    release_common_dir="$(resolve_common_git_dir "${RELEASE_SOURCE_DIR}")" \
      || die "existing release source is not a Git worktree: ${RELEASE_SOURCE_DIR}"
    [ "${project_common_dir}" = "${release_common_dir}" ] \
      || die "existing release source belongs to a different Git repository"
    [ -z "$(git -C "${RELEASE_SOURCE_DIR}" status --porcelain --untracked-files=all)" ] \
      || die "release source worktree has local changes: ${RELEASE_SOURCE_DIR}"
    git -C "${RELEASE_SOURCE_DIR}" switch --detach "${target_sha}"
  else
    git worktree add --detach "${RELEASE_SOURCE_DIR}" "${target_sha}"
  fi
  [ "$(git -C "${RELEASE_SOURCE_DIR}" rev-parse HEAD)" = "${target_sha}" ] \
    || die "release source HEAD does not match the selected remote branch"
  MANAGED_COMPOSE_FILE="${RELEASE_SOURCE_DIR}/deploy/docker-compose.production.yml"
  [ -f "${MANAGED_COMPOSE_FILE}" ] || die "selected branch is missing the managed Compose template"
}

load_remote_branches
select_release_branch

lock_file="${COMPOSE_DIR}/.release.lock"
exec 9>"${lock_file}"
flock -n 9 || die "another Parloq Flow update is already running"

target_ref="refs/remotes/origin/${release_branch}"
target_refspec="+refs/heads/${release_branch}:${target_ref}"
git_with_auth fetch --no-tags origin "${target_refspec}" \
  || die "could not fetch origin/${release_branch} with the configured GitHub token"
target_sha="$(git rev-parse --verify "${target_ref}^{commit}")" \
  || die "could not resolve origin/${release_branch} to a commit"
log "已选择远程分支 ${release_branch}，目标提交 ${target_sha}。"
if [ "${release_branch}" != "main" ] \
  && ! git merge-base --is-ancestor origin/main "${target_sha}"; then
  log "WARNING: ${release_branch} 没有包含当前 main 的全部提交，将按所选分支原样发布。"
fi
prepare_release_source

head_sha="${target_sha}"
short_sha="${head_sha:0:12}"
api_image="parloq-flow-api-server:${short_sha}"
web_image="parloq-flow-web-server:${short_sha}"
gateway_image="parloq-flow-wa-gateway-server:${short_sha}"

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

update_env PARLOQ_SOURCE_ROOT "${RELEASE_SOURCE_DIR}"
update_env PARLOQ_GIT_BRANCH "${release_branch}"
update_env PARLOQ_GIT_REF "${head_sha}"
update_env PARLOQ_APP_PULL_POLICY build
update_env PARLOQ_API_IMAGE "${api_image}"
update_env PARLOQ_WEB_IMAGE "${web_image}"
update_env PARLOQ_WA_GATEWAY_IMAGE "${gateway_image}"
update_env MANAGEMENT_ORIGIN "${management_origin}"
chmod 600 "${env_candidate}"

docker compose \
  --env-file "${env_candidate}" \
  -f "${compose_candidate}" \
  config --quiet

switched=1
mv "${env_candidate}" "${ENV_FILE}"
mv "${compose_candidate}" "${COMPOSE_FILE}"

cd "${COMPOSE_DIR}"
log "服务器开始构建 ${release_branch} @ ${short_sha} 并更新宝塔 Compose 项目。"
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
management_page="$(curl -fsS --max-time 20 -H "Host: ${management_host}" http://127.0.0.1:18100/)"
case "${management_page}" in
  *'<div id="root"></div>'*) ;;
  *) log "ERROR: management SPA did not load for ${management_host}"; false ;;
esac
forwarded_management_page="$(curl -fsS --max-time 20 \
  -H 'Host: 127.0.0.1' \
  -H "X-Forwarded-Host: ${management_host}" \
  http://127.0.0.1:18100/)"
case "${forwarded_management_page}" in
  *'<div id="root"></div>'*) ;;
  *) log "ERROR: management SPA did not load through forwarded-host proxy mode"; false ;;
esac
loopback_management_page="$(curl -fsS --max-time 20 \
  -H 'Host: 127.0.0.1' \
  http://127.0.0.1:18100/)"
case "${loopback_management_page}" in
  *'<div id="root"></div>'*) ;;
  *) log "ERROR: management SPA did not load through BaoTa loopback Host mode"; false ;;
esac
curl -fsS --max-time 20 \
  "${management_origin}/api/auth/security?username=release-check" >/dev/null
public_management_page="$(curl -fsS --max-time 20 \
  "${management_origin}/?release-check=${short_sha}")"
case "${public_management_page}" in
  *'<div id="root"></div>'*) ;;
  *) log "ERROR: public management SPA did not load from ${management_origin}"; false ;;
esac
log "管理后台 ${management_origin} 验证通过。"

trap - ERR

cleanup_component_images() {
  component="$1"
  entries=()
  for repository in \
    "parloq-flow-${component}-server" \
    "parloq-flow-${component}-local"; do
    while IFS= read -r image_ref; do
      [ -n "${image_ref}" ] || continue
      image_tag="${image_ref##*:}"
      [[ "${image_tag}" =~ ^[0-9a-f]{12}$ ]] || continue
      if ! created_at="$(docker image inspect --format '{{.Created}}' "${image_ref}" 2>/dev/null)"; then
        log "WARNING: 无法读取镜像 ${image_ref}，跳过清理。"
        continue
      fi
      entries+=("${created_at}|${image_ref}")
    done < <(docker image ls "${repository}" --format '{{.Repository}}:{{.Tag}}')
  done

  [ "${#entries[@]}" -gt 0 ] || return 0
  mapfile -t sorted_entries < <(printf '%s\n' "${entries[@]}" | sort -r)
  kept=0
  for entry in "${sorted_entries[@]}"; do
    image_ref="${entry#*|}"
    if [ "${kept}" -lt "${IMAGE_RETENTION}" ]; then
      kept=$((kept + 1))
      continue
    fi
    if ! image_id="$(docker image inspect --format '{{.Id}}' "${image_ref}" 2>/dev/null)"; then
      continue
    fi
    if [ -n "$(docker ps -q --filter "ancestor=${image_id}")" ]; then
      log "保留运行中的镜像 ${image_ref}。"
      continue
    fi
    if docker image rm "${image_ref}" >/dev/null; then
      log "已清理旧镜像 ${image_ref}。"
    else
      log "WARNING: 无法清理旧镜像 ${image_ref}，可能仍被停止的容器引用。"
    fi
  done
}

log "开始清理 Parloq Flow 历史镜像，每个组件保留最近 ${IMAGE_RETENTION} 个版本。"
for component in api web wa-gateway; do
  if ! cleanup_component_images "${component}"; then
    log "WARNING: ${component} 历史镜像清理失败，不影响本次发布结果。"
  fi
done

if docker builder prune --force --filter "until=${BUILD_CACHE_MAX_AGE}"; then
  log "已清理超过 ${BUILD_CACHE_MAX_AGE} 的 BuildKit 构建缓存。"
else
  log "WARNING: BuildKit 缓存清理失败，不影响本次发布结果。"
fi

log "${release_branch} @ ${head_sha} 构建和更新完成。"
log "配置备份：${env_backup}"
log "Compose 备份：${compose_backup}"
