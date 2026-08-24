#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="${PARLOQ_COMPOSE_PROJECT:-parloq-flow}"
PUBLIC_HOST="${PARLOQ_PUBLIC_HOST:-216.106.185.81}"
COMPOSE_DIR="${PARLOQ_COMPOSE_DIR:-/www/server/panel/data/compose/parloq-flow}"
PARLOQ_ENV_FILE="${PARLOQ_ENV_FILE:-${COMPOSE_DIR}/.env}"
STATE_DIR="${PARLOQ_PUBLIC_STATE_DIR:-${COMPOSE_DIR}/.public-data-access}"
STATE_FILE="${STATE_DIR}/state"
BT_PYTHON="${PARLOQ_BT_PYTHON:-/usr/bin/btpython}"
BT_PANEL_ROOT="${PARLOQ_BT_PANEL_ROOT:-/www/server/panel}"
PORT_MIN="${PARLOQ_PUBLIC_PORT_MIN:-20000}"
PORT_MAX="${PARLOQ_PUBLIC_PORT_MAX:-29999}"
POSTGRES_RULE_REMARK="Parloq Flow temporary PostgreSQL public access"
REDIS_RULE_REMARK="Parloq Flow temporary Redis public access"
PROXY_MARKER="parloq-flow-public-data-proxy-v2"

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    printf '请使用 root 运行此脚本。\n' >&2
    return 1
  fi
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf '缺少命令：%s\n' "$1" >&2
    return 1
  }
}

read_env_value() {
  local key="$1"
  [[ -f "${PARLOQ_ENV_FILE}" ]] || return 0
  awk -v wanted="${key}" 'index($0, wanted "=") == 1 { sub("^[^=]*=", ""); print; exit }' "${PARLOQ_ENV_FILE}"
}

container_id_for_service() {
  local service="$1"
  docker ps \
    --filter "label=com.docker.compose.project=${PROJECT_NAME}" \
    --filter "label=com.docker.compose.service=${service}" \
    --format '{{.ID}}' \
    | head -n 1
}

healthy_container_ip() {
  local service="$1"
  local container_id health container_ip
  container_id="$(container_id_for_service "${service}")"
  if [[ -z "${container_id}" ]]; then
    printf '找不到 Parloq Flow 的 %s 容器。\n' "${service}" >&2
    return 1
  fi
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}")"
  if [[ "${health}" != "healthy" && "${health}" != "running" ]]; then
    printf '%s 容器当前状态为 %s，拒绝打开公网访问。\n' "${service}" "${health}" >&2
    return 1
  fi
  container_ip="$(docker inspect --format '{{range .NetworkSettings.Networks}}{{if .IPAddress}}{{.IPAddress}}{{end}}{{end}}' "${container_id}")"
  if [[ -z "${container_ip}" || "${container_ip}" != *.*.*.* ]]; then
    printf '无法读取 %s 容器的 IPv4 地址。\n' "${service}" >&2
    return 1
  fi
  printf '%s' "${container_ip}"
}

choose_random_port() {
  local excluded="${1:-0}" candidate _attempt
  for _attempt in $(seq 1 200); do
    candidate="$(python3 - "${PORT_MIN}" "${PORT_MAX}" <<'PY'
import secrets
import sys

minimum, maximum = map(int, sys.argv[1:])
print(minimum + secrets.randbelow(maximum - minimum + 1))
PY
)"
    [[ "${candidate}" != "${excluded}" ]] || continue
    if ! python3 - "${candidate}" <<'PY'
import socket
import sys

with socket.socket() as listener:
    listener.bind(("0.0.0.0", int(sys.argv[1])))
PY
    then
      continue
    fi
    baota_firewall free "${candidate}" "" >/dev/null 2>&1 || continue
    printf '%s' "${candidate}"
    return 0
  done
  printf '在 %s-%s 中没有找到可用随机端口。\n' "${PORT_MIN}" "${PORT_MAX}" >&2
  return 1
}

# 只调用宝塔自己的防火墙管理类，让规则显示在“宝塔 → 安全”中。
baota_firewall() {
  local action="$1" port="${2:-0}" remark="${3:-}"
  "${BT_PYTHON}" - "${action}" "${port}" "${remark}" "${BT_PANEL_ROOT}" <<'PY'
import contextlib
import io
import os
import sys

action, port, remark, panel_root = sys.argv[1:]
if not port.isdigit() or not 0 <= int(port) <= 65535:
    raise SystemExit(2)
os.chdir(panel_root)
sys.path.insert(0, os.path.join(panel_root, "class"))
import firewalls  # type: ignore  # noqa: E402
import public  # type: ignore  # noqa: E402


def find():
    row = public.M("firewall").where("port=?", (port,)).find()
    return row if isinstance(row, dict) and row else None


def invoke(method, request):
    with contextlib.redirect_stdout(io.StringIO()):
        result = method(request)
    if isinstance(result, dict) and result.get("status") is False:
        raise RuntimeError(str(result.get("msg", "BaoTa firewall operation failed")))


row = find()
if action == "free":
    raise SystemExit(1 if row else 0)
if action == "owned":
    raise SystemExit(0 if row and row.get("ps") == remark else 1)
if action == "add":
    if row and row.get("ps") != remark:
        raise RuntimeError("port belongs to another BaoTa Security rule")
    if not row:
        request = public.dict_obj()
        request.port = port
        request.ps = remark
        invoke(firewalls.firewalls().AddAcceptPort, request)
    row = find()
    if not row or row.get("ps") != remark:
        raise RuntimeError("BaoTa did not persist the expected Security rule")
    raise SystemExit(0)
if action == "delete":
    if not row:
        raise SystemExit(0)
    if row.get("ps") != remark:
        raise RuntimeError("refusing to delete a foreign BaoTa Security rule")
    request = public.dict_obj()
    request.id = str(row["id"])
    request.port = port
    invoke(firewalls.firewalls().DelAcceptPort, request)
    if find():
        raise RuntimeError("BaoTa did not remove the Security rule")
    raise SystemExit(0)
raise RuntimeError("unsupported BaoTa firewall action")
PY
}

start_forwarder() {
  local listen_port="$1" target_host="$2" target_port="$3"
  nohup python3 -c '
import selectors
import socket
import sys
import threading

listen_port, target_host, target_port = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])

def relay(client):
    upstream = None
    try:
        upstream = socket.create_connection((target_host, target_port), timeout=10)
        client.setblocking(False)
        upstream.setblocking(False)
        selector = selectors.DefaultSelector()
        selector.register(client, selectors.EVENT_READ, upstream)
        selector.register(upstream, selectors.EVENT_READ, client)
        while True:
            for key, _ in selector.select(timeout=60):
                data = key.fileobj.recv(65536)
                if not data:
                    return
                key.data.sendall(data)
    finally:
        client.close()
        if upstream is not None:
            upstream.close()

with socket.socket() as listener:
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("0.0.0.0", listen_port))
    listener.listen(128)
    while True:
        client, _ = listener.accept()
        threading.Thread(target=relay, args=(client,), daemon=True).start()
' "${listen_port}" "${target_host}" "${target_port}" "${PROXY_MARKER}" >/dev/null 2>&1 &
  local forwarder_pid=$!
  sleep 0.2
  kill -0 "${forwarder_pid}" >/dev/null 2>&1 || {
    printf '端口转发进程启动失败。\n' >&2
    return 1
  }
  printf '%s' "${forwarder_pid}"
}

forwarder_is_owned() {
  local pid="$1" listen_port="$2"
  [[ -r "/proc/${pid}/cmdline" ]] || return 1
  tr '\0' '\n' <"/proc/${pid}/cmdline" | grep -Fxq "${PROXY_MARKER}" \
    && tr '\0' '\n' <"/proc/${pid}/cmdline" | grep -Fxq "${listen_port}"
}

stop_owned_forwarder() {
  local pid="$1" listen_port="$2"
  [[ -n "${pid}" ]] || return 0
  forwarder_is_owned "${pid}" "${listen_port}" || return 0
  kill "${pid}"
}

write_state() {
  install -d -m 700 "${STATE_DIR}"
  umask 077
  {
    printf 'POSTGRES_PORT=%q\n' "$1"
    printf 'REDIS_PORT=%q\n' "$2"
    printf 'POSTGRES_PID=%q\n' "$3"
    printf 'REDIS_PID=%q\n' "$4"
    printf 'POSTGRES_RULE_ID=%q\n' "$5"
    printf 'REDIS_RULE_ID=%q\n' "$6"
    printf 'POSTGRES_CONTAINER_ID=%q\n' "$7"
    printf 'REDIS_CONTAINER_ID=%q\n' "$8"
  } >"${STATE_FILE}"
}

load_state() {
  POSTGRES_PORT=""
  REDIS_PORT=""
  POSTGRES_PID=""
  REDIS_PID=""
  POSTGRES_RULE_ID=""
  REDIS_RULE_ID=""
  POSTGRES_CONTAINER_ID=""
  REDIS_CONTAINER_ID=""
  if [[ -f "${STATE_FILE}" ]]; then
    # The file is root-owned, mode 600, and contains only shell-escaped scalar values.
    source "${STATE_FILE}"
  fi
}

show_connection_info() {
  local POSTGRES_PORT="${1:-}" REDIS_PORT="${2:-}"
  if [[ -z "${POSTGRES_PORT}" || -z "${REDIS_PORT}" ]]; then
    load_state
  fi
  local postgres_db postgres_user
  postgres_db="$(read_env_value POSTGRES_DB)"
  postgres_user="$(read_env_value POSTGRES_USER)"
  postgres_db="${postgres_db:-parloq_flow}"
  postgres_user="${postgres_user:-parloq_flow}"
  printf '\n连接信息（密码不会显示）：\n'
  printf 'PostgreSQL: %s:%s / 数据库 %s / 用户 %s\n' "${PUBLIC_HOST}" "${POSTGRES_PORT}" "${postgres_db}" "${postgres_user}"
  printf 'PostgreSQL URL: postgresql://%s:<POSTGRES_PASSWORD>@%s:%s/%s\n' "${postgres_user}" "${PUBLIC_HOST}" "${POSTGRES_PORT}" "${postgres_db}"
  printf 'Redis: %s:%s\n' "${PUBLIC_HOST}" "${REDIS_PORT}"
  printf 'Redis URL: redis://:<REDIS_PASSWORD>@%s:%s/0\n' "${PUBLIC_HOST}" "${REDIS_PORT}"
  printf '来源范围：0.0.0.0/0（不限制来源 IP）\n'
}

status_access() {
  load_state
  if [[ ! -f "${STATE_FILE}" ]]; then
    printf '状态：已关闭\n'
    return 0
  fi
  if forwarder_is_owned "${POSTGRES_PID}" "${POSTGRES_PORT}" \
    && forwarder_is_owned "${REDIS_PID}" "${REDIS_PORT}" \
    && baota_firewall owned "${POSTGRES_PORT}" "${POSTGRES_RULE_REMARK}" >/dev/null 2>&1 \
    && baota_firewall owned "${REDIS_PORT}" "${REDIS_RULE_REMARK}" >/dev/null 2>&1 \
    && [[ "$(container_id_for_service postgres)" == "${POSTGRES_CONTAINER_ID}" ]] \
    && [[ "$(container_id_for_service redis)" == "${REDIS_CONTAINER_ID}" ]]; then
    printf '状态：已打开\n'
    printf '宝塔安全规则：正常\n'
    printf '来源范围：0.0.0.0/0\n'
    show_connection_info
  else
    printf '状态：异常，请先关闭清理后再重新打开。\n'
    return 1
  fi
}

close_access() {
  require_root
  if [[ ! -f "${STATE_FILE}" ]]; then
    printf '状态：已经关闭。\n'
    return 0
  fi
  load_state
  baota_firewall delete "${POSTGRES_PORT}" "${POSTGRES_RULE_REMARK}" \
    || { printf '删除 PostgreSQL 宝塔安全规则失败。\n' >&2; return 1; }
  baota_firewall delete "${REDIS_PORT}" "${REDIS_RULE_REMARK}" \
    || { printf '删除 Redis 宝塔安全规则失败。\n' >&2; return 1; }
  stop_owned_forwarder "${POSTGRES_PID}" "${POSTGRES_PORT}"
  stop_owned_forwarder "${REDIS_PID}" "${REDIS_PORT}"
  rm -f "${STATE_FILE}"
  rmdir "${STATE_DIR}" >/dev/null 2>&1 || true
  printf '已关闭 Parloq Flow 数据服务公网访问。\n'
}

open_access() {
  require_root
  for command_name in docker python3 seq; do
    require_command "${command_name}"
  done
  [[ -x "${BT_PYTHON}" ]] || { printf '找不到宝塔 Python：%s\n' "${BT_PYTHON}" >&2; return 1; }
  [[ -d "${BT_PANEL_ROOT}/class" ]] || { printf '找不到宝塔面板目录。\n' >&2; return 1; }
  [[ -f "${PARLOQ_ENV_FILE}" ]] || { printf '找不到生产环境文件。\n' >&2; return 1; }
  [[ -n "$(read_env_value POSTGRES_PASSWORD)" ]] \
    || { printf '生产环境尚未配置 POSTGRES_PASSWORD。\n' >&2; return 1; }
  [[ -n "$(read_env_value REDIS_PASSWORD)" ]] \
    || { printf '生产环境尚未配置 REDIS_PASSWORD。\n' >&2; return 1; }
  if [[ -f "${STATE_FILE}" ]]; then
    status_access && printf '公网访问已经打开，无需重复操作。\n' && return 0
    printf '检测到异常状态，请先选择“关闭”清理。\n' >&2
    return 1
  fi

  local postgres_ip redis_ip postgres_port redis_port postgres_pid redis_pid
  local postgres_container_id redis_container_id
  local postgres_rule_id redis_rule_id
  postgres_ip="$(healthy_container_ip postgres)"
  redis_ip="$(healthy_container_ip redis)"
  postgres_container_id="$(container_id_for_service postgres)"
  redis_container_id="$(container_id_for_service redis)"
  postgres_port="$(choose_random_port)"
  redis_port="$(choose_random_port "${postgres_port}")"

  postgres_pid="$(start_forwarder "${postgres_port}" "${postgres_ip}" 5432)"
  if ! redis_pid="$(start_forwarder "${redis_port}" "${redis_ip}" 6379)"; then
    stop_owned_forwarder "${postgres_pid}" "${postgres_port}"
    return 1
  fi
  postgres_rule_id="${postgres_port}"
  redis_rule_id="${redis_port}"
  write_state \
    "${postgres_port}" "${redis_port}" "${postgres_pid}" "${redis_pid}" \
    "${postgres_rule_id}" "${redis_rule_id}" \
    "${postgres_container_id}" "${redis_container_id}"
  if ! baota_firewall add "${postgres_port}" "${POSTGRES_RULE_REMARK}"; then
    stop_owned_forwarder "${postgres_pid}" "${postgres_port}"
    stop_owned_forwarder "${redis_pid}" "${redis_port}"
    rm -f "${STATE_FILE}"
    return 1
  fi
  if ! baota_firewall add "${redis_port}" "${REDIS_RULE_REMARK}"; then
    baota_firewall delete "${postgres_port}" "${POSTGRES_RULE_REMARK}" || true
    stop_owned_forwarder "${postgres_pid}" "${postgres_port}"
    stop_owned_forwarder "${redis_pid}" "${redis_port}"
    rm -f "${STATE_FILE}"
    return 1
  fi
  printf '已打开 Parloq Flow 数据服务公网访问。\n'
  printf '随机端口已写入宝塔安全规则。\n'
  printf '来源范围：0.0.0.0/0\n'
  show_connection_info
}

show_menu() {
  printf 'Parloq Flow PostgreSQL / Redis 公网访问\n'
  printf '1) 状态\n'
  printf '2) 打开\n'
  printf '3) 关闭\n'
}

main() {
  local choice="${1:-}"
  require_root || return 1
  for command_name in docker python3 seq; do
    require_command "${command_name}" || return 1
  done
  [[ -x "${BT_PYTHON}" ]] || { printf '找不到宝塔 Python：%s\n' "${BT_PYTHON}" >&2; return 1; }
  [[ -d "${BT_PANEL_ROOT}/class" ]] || { printf '找不到宝塔面板目录。\n' >&2; return 1; }
  case "${PORT_MIN}:${PORT_MAX}" in
    *[!0-9:]*) printf '随机端口范围必须是数字。\n' >&2; return 1 ;;
  esac
  if [[ "${PORT_MIN}" -lt 1024 || "${PORT_MAX}" -gt 65535 || "${PORT_MIN}" -ge "${PORT_MAX}" ]]; then
    printf '随机端口范围无效。\n' >&2
    return 1
  fi
  if [[ -z "${choice}" ]]; then
    show_menu
    read -r -p '请选择 [1-3]：' choice
  fi
  case "${choice}" in
    1 | status) status_access ;;
    2 | open) open_access ;;
    3 | close) close_access ;;
    *) printf '无效选项。\n' >&2; return 2 ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
