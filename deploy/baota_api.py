#!/usr/bin/env python3
"""Small BaoTa API client used by the production release wrapper.

Remote mutations are sent through BaoTa's authenticated HTTP API. SSH is used
only as an encrypted tunnel to the panel's loopback listener because the panel
API allow-list intentionally contains loopback rather than arbitrary client IPs.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import socket
import ssl
import subprocess
import sys
import time
from typing import Any, Iterator, Mapping
import urllib.error
import urllib.parse
import urllib.request


PROJECT_NAME = "parloq-flow"
REMOTE_DIR = "/www/server/panel/data/compose/parloq-flow"
COMPOSE_FILE = f"{REMOTE_DIR}/docker-compose.yaml"
ENV_FILE = f"{REMOTE_DIR}/.env"
RELEASE_DIR = f"{REMOTE_DIR}/releases"
SITE_NAME = "center.parloq.com"


class BaoTaError(RuntimeError):
    pass


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        raise BaoTaError(f"missing BaoTa credential file: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_token_hash(settings: Mapping[str, str]) -> str:
    configured_hash = settings.get("BAOTA_API_TOKEN_HASH", "").lower()
    if re.fullmatch(r"[0-9a-f]{32}", configured_hash):
        return configured_hash
    api_key = settings.get("BAOTA_API_KEY")
    if api_key:
        return hashlib.md5(api_key.encode()).hexdigest()
    if settings.get("BAOTA_TOKEN_SOURCE") != "remote-api-json":
        raise BaoTaError(
            "configure BAOTA_API_KEY, BAOTA_API_TOKEN_HASH, or BAOTA_TOKEN_SOURCE=remote-api-json"
        )
    ssh_host = settings.get("BAOTA_SSH_HOST", "root@216.106.185.81")
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        ssh_host,
        "python3 -c 'import json; print(json.load(open(\"/www/server/panel/config/api.json\"))[\"token\"])'",
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=15)
    token_hash = result.stdout.strip().lower()
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{32}", token_hash):
        raise BaoTaError("could not read the BaoTa API token hash through the read-only SSH channel")
    return token_hash


@contextmanager
def panel_endpoint(settings: Mapping[str, str]) -> Iterator[str]:
    ssh_host = settings.get("BAOTA_SSH_HOST", "root@216.106.185.81")
    panel_port = int(settings.get("BAOTA_PANEL_REMOTE_PORT", "10049"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        local_port = listener.getsockname()[1]
    command = [
        "ssh",
        "-N",
        "-o",
        "BatchMode=yes",
        "-o",
        "ExitOnForwardFailure=yes",
        "-L",
        f"127.0.0.1:{local_port}:127.0.0.1:{panel_port}",
        ssh_host,
    ]
    tunnel = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if tunnel.poll() is not None:
                detail = (tunnel.stderr.read() if tunnel.stderr else "").strip()
                raise BaoTaError(f"BaoTa SSH tunnel failed: {detail or 'unknown error'}")
            try:
                with socket.create_connection(("127.0.0.1", local_port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise BaoTaError("BaoTa SSH tunnel did not become ready")
        yield f"https://127.0.0.1:{local_port}"
    finally:
        tunnel.terminate()
        try:
            tunnel.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tunnel.kill()
            tunnel.wait(timeout=5)


class BaoTaClient:
    def __init__(self, base_url: str, token_hash: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key_hash = token_hash
        self.context = ssl._create_unverified_context()

    def signed(self, values: Mapping[str, object] | None = None) -> dict[str, object]:
        request_time = str(int(time.time()))
        request_token = hashlib.md5(
            (request_time + self.api_key_hash).encode()
        ).hexdigest()
        return {
            **(dict(values or {})),
            "request_time": request_time,
            "request_token": request_token,
        }

    def post(self, path: str, values: Mapping[str, object] | None = None, *, timeout: int = 60) -> Any:
        payload = urllib.parse.urlencode(self.signed(values)).encode()
        request = urllib.request.Request(
            self.base_url + path,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(request, context=self.context, timeout=timeout) as response:
                body = response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise BaoTaError(f"BaoTa request failed for {path}: {type(exc).__name__}") from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise BaoTaError(f"BaoTa returned non-JSON data for {path}") from exc

    @staticmethod
    def require_success(payload: Any, operation: str, *, false_is_success: bool = False) -> Any:
        if false_is_success and payload is False:
            return payload
        if not isinstance(payload, dict) or payload.get("status") is not True:
            message = payload.get("msg") if isinstance(payload, dict) else type(payload).__name__
            raise BaoTaError(f"{operation} failed: {message or 'unknown BaoTa response'}")
        return payload

    def read_file(self, path: str) -> tuple[str, str, object]:
        payload = self.post("/files?action=GetFileBody", {"path": path})
        self.require_success(payload, f"read {path}")
        value = payload.get("data")
        encoding = payload.get("encoding") or "utf-8"
        modified = payload.get("st_mtime")
        if isinstance(value, dict):
            encoding = value.get("encoding") or encoding
            modified = value.get("st_mtime", modified)
            value = value.get("data") or value.get("content") or value.get("body") or ""
        if not isinstance(value, str) or modified is None:
            raise BaoTaError(f"BaoTa returned an invalid file snapshot for {path}")
        return value, str(encoding), modified

    def upload(self, local_path: Path, remote_dir: str, *, chunk_size: int = 4 * 1024 * 1024) -> str:
        total = local_path.stat().st_size
        offset = 0
        with local_path.open("rb") as source:
            while offset < total:
                source.seek(offset)
                chunk = source.read(min(chunk_size, total - offset))
                payload = self.post(
                    "/files?action=upload",
                    {
                        "f_name": local_path.name,
                        "f_path": remote_dir,
                        "f_size": total,
                        "f_start": offset,
                        "b64_data": base64.b64encode(chunk).decode(),
                    },
                    timeout=180,
                )
                next_offset = offset + len(chunk)
                if isinstance(payload, int):
                    if payload != next_offset:
                        raise BaoTaError(
                            f"BaoTa upload offset mismatch: expected {next_offset}, got {payload}"
                        )
                else:
                    self.require_success(payload, "upload release archive")
                    if next_offset != total:
                        raise BaoTaError("BaoTa finalized the upload before the last chunk")
                offset = next_offset
                percent = int(offset * 100 / total)
                print(f"[parloq-release] BaoTa upload {percent}%", flush=True)
        remote_path = f"{remote_dir}/{local_path.name}"
        check = self.post("/files?action=upload_file_exists", {"filename": remote_path})
        self.require_success(check, "verify uploaded archive")
        info = check.get("msg") or check.get("data") or {}
        if not isinstance(info, dict) or int(info.get("size", -1)) != total:
            raise BaoTaError("BaoTa uploaded archive size does not match")
        return remote_path

    def delete_file(self, path: str) -> None:
        payload = self.post("/files?action=DeleteFile", {"path": path})
        self.require_success(payload, f"delete {path}")

    def add_shell_task(self, name: str, script: str) -> int:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", name):
            raise BaoTaError("invalid temporary task name")
        if not script.strip() or len(script.encode()) > 64_000:
            raise BaoTaError("invalid temporary task script")
        created = self.post(
            "/crontab",
            {
                "action": "AddCrontab",
                "name": name,
                "type": "day-n",
                "where1": "36500",
                "sType": "toShell",
                "sBody": script,
                "sName": "Parloq Flow 一次性生产发布任务",
                "save": 0,
                "backupTo": "localhost",
            },
        )
        self.require_success(created, "create BaoTa release task")
        try:
            task_id = int(created.get("id"))
        except (TypeError, ValueError) as exc:
            raise BaoTaError("BaoTa did not return a release task id") from exc
        accepted = self.post("/crontab", {"action": "StartTask", "id": task_id})
        self.require_success(accepted, "start BaoTa release task")
        return task_id

    def delete_task(self, task_id: int) -> None:
        payload = self.post("/crontab", {"action": "DelCrontab", "id": task_id})
        self.require_success(payload, "delete BaoTa release task")

    def wait_status(self, path: str, *, timeout_seconds: int = 1_800) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            payload = self.post("/files?action=GetFileBody", {"path": path})
            if isinstance(payload, dict) and payload.get("status") is True:
                value = payload.get("data")
                if isinstance(value, dict):
                    value = value.get("data") or value.get("content") or value.get("body")
                if isinstance(value, str) and value.strip():
                    try:
                        result = json.loads(value)
                    except json.JSONDecodeError:
                        result = None
                    if isinstance(result, dict) and result.get("status") in {"success", "failed"}:
                        return result
            time.sleep(2)
        raise BaoTaError("timed out waiting for the BaoTa release task")


def release_script(
    *, commit: str, short_sha: str, archive: str, checksum: str,
    api_image: str, web_image: str, gateway_image: str, status_file: str,
) -> str:
    for value in (commit, short_sha):
        if not re.fullmatch(r"[0-9a-f]{7,40}", value):
            raise BaoTaError("invalid Git revision")
    for image in (api_image, web_image, gateway_image):
        if not re.fullmatch(r"[A-Za-z0-9._/:@-]+", image):
            raise BaoTaError("invalid image reference")
    q = shlex.quote
    return f"""#!/usr/bin/env bash
set -Eeuo pipefail
commit={q(commit)}
short_sha={q(short_sha)}
archive={q(archive)}
checksum={q(checksum)}
remote_dir={q(REMOTE_DIR)}
compose_file={q(COMPOSE_FILE)}
env_file={q(ENV_FILE)}
status_file={q(status_file)}
api_image={q(api_image)}
web_image={q(web_image)}
gateway_image={q(gateway_image)}
backup="${{env_file}}.backup-${{short_sha}}-$(date -u +%Y%m%dT%H%M%SZ)"
switched=0
write_status() {{
  mkdir -p "$(dirname "${{status_file}}")"
  printf '%s\n' "$1" >"${{status_file}}"
}}
rollback() {{
  code=$?
  rollback_succeeded=0
  if [ "${{switched}}" = 1 ] && [ -f "${{backup}}" ]; then
    if cp -p "${{backup}}" "${{env_file}}"; then
      cd "${{remote_dir}}"
      if docker compose --env-file "${{env_file}}" -f "${{compose_file}}" up -d --no-deps wa-gateway api api-worker web; then
        rollback_succeeded=1
      fi
    fi
  fi
  write_status "{{\"status\":\"failed\",\"commit\":\"${{commit}}\",\"exitCode\":${{code}},\"rollbackAttempted\":${{switched}},\"rollbackSucceeded\":${{rollback_succeeded}}}}"
  exit "${{code}}"
}}
trap rollback ERR
printf '%s  %s\n' "${{checksum}}" "${{archive}}" | sha256sum -c -
docker image load <"${{archive}}"
[ -f "${{compose_file}}" ]
[ -f "${{env_file}}" ]
cp -p "${{env_file}}" "${{backup}}"
update_env() {{
  key="$1"; value="$2"
  if grep -q "^${{key}}=" "${{env_file}}"; then
    sed -i "s|^${{key}}=.*|${{key}}=${{value}}|" "${{env_file}}"
  else
    printf '%s=%s\n' "${{key}}" "${{value}}" >>"${{env_file}}"
  fi
}}
update_env PARLOQ_API_IMAGE "${{api_image}}"
update_env PARLOQ_WEB_IMAGE "${{web_image}}"
update_env PARLOQ_WA_GATEWAY_IMAGE "${{gateway_image}}"
chmod 600 "${{env_file}}"
switched=1
cd "${{remote_dir}}"
docker compose --env-file "${{env_file}}" -f "${{compose_file}}" config --quiet
docker compose --env-file "${{env_file}}" -f "${{compose_file}}" up -d postgres redis
docker compose --profile migration --env-file "${{env_file}}" -f "${{compose_file}}" run --interactive=false -T --rm migrate
docker compose --env-file "${{env_file}}" -f "${{compose_file}}" up -d --no-deps wa-gateway api api-worker web
for attempt in $(seq 1 60); do
  curl -fsS http://127.0.0.1:18100/healthz >/dev/null && break
  [ "${{attempt}}" -lt 60 ] || false
  sleep 2
done
for service in api api-worker web wa-gateway; do
  container_id="$(docker compose --env-file "${{env_file}}" -f "${{compose_file}}" ps -q "${{service}}")"
  revision="$(docker inspect --format '{{{{ index .Config.Labels \"org.opencontainers.image.revision\" }}}}' "${{container_id}}")"
  [ "${{revision}}" = "${{commit}}" ]
done
trap - ERR
write_status "{{\"status\":\"success\",\"commit\":\"${{commit}}\",\"backup\":\"${{backup}}\"}}"
"""


def command_status(client: BaoTaClient) -> None:
    sites = client.post(
        "/data?action=getData&table=sites",
        {"limit": 20, "p": 1, "type": -1, "order": "id desc", "search": SITE_NAME},
    )
    proxies = client.post("/site?action=GetProxyList", {"sitename": SITE_NAME})
    stacks = client.post("/mod/docker/com/ls", {})
    site_ok = isinstance(sites, dict) and any(
        row.get("name") == SITE_NAME for row in (sites.get("data") or []) if isinstance(row, dict)
    )
    proxy_ok = isinstance(proxies, list) and any(
        row.get("proxyname") == PROJECT_NAME and row.get("proxysite") == "http://127.0.0.1:18100"
        for row in proxies if isinstance(row, dict)
    )
    stack_ok = isinstance(stacks, list) and any(
        row.get("Name") == PROJECT_NAME or row.get("name") == PROJECT_NAME
        for row in stacks if isinstance(row, dict)
    )
    print(json.dumps({"site": site_ok, "proxy": proxy_ok, "stack": stack_ok}))
    if not all((site_ok, proxy_ok, stack_ok)):
        raise BaoTaError("BaoTa production registration is incomplete")


def command_release(client: BaoTaClient, args: argparse.Namespace) -> None:
    archive = Path(args.archive).resolve()
    if not archive.is_file() or archive.suffix != ".tar":
        raise BaoTaError("release archive must be an existing .tar file")
    remote_archive = client.upload(archive, RELEASE_DIR)
    status_file = f"{RELEASE_DIR}/status-{args.short_sha}.json"
    script = release_script(
        commit=args.commit,
        short_sha=args.short_sha,
        archive=remote_archive,
        checksum=args.checksum,
        api_image=args.api_image,
        web_image=args.web_image,
        gateway_image=args.gateway_image,
        status_file=status_file,
    )
    task_id = client.add_shell_task(f"parloq-release-{args.short_sha}", script)
    result = client.wait_status(status_file)
    if result.get("status") != "success":
        raise BaoTaError(
            f"production release failed (exit={result.get('exitCode')}, rollback={result.get('rollbackAttempted')})"
        )
    client.delete_task(task_id)
    client.delete_file(remote_archive)
    client.delete_file(status_file)
    print(json.dumps({"status": "success", "commit": args.commit, "backup": result.get("backup")}))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument(
        "--env-file",
        type=Path,
        default=Path(os.environ.get("PARLOQ_BAOTA_ENV_FILE", ".env.baota.local")),
    )
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    release = commands.add_parser("release")
    release.add_argument("--archive", required=True)
    release.add_argument("--checksum", required=True)
    release.add_argument("--commit", required=True)
    release.add_argument("--short-sha", required=True)
    release.add_argument("--api-image", required=True)
    release.add_argument("--web-image", required=True)
    release.add_argument("--gateway-image", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        settings = load_env(args.env_file)
        token_hash = resolve_token_hash(settings)
        with panel_endpoint(settings) as base_url:
            client = BaoTaClient(base_url, token_hash)
            if args.command == "status":
                command_status(client)
            else:
                command_release(client, args)
        return 0
    except BaoTaError as exc:
        print(f"[parloq-release] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
