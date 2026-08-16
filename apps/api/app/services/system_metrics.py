from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from app.config import get_settings


settings = get_settings()
CGROUP_ROOT = Path("/sys/fs/cgroup")
CGROUP_UNLIMITED_LIMIT = 1 << 60
SYSTEM_HOST_PROC_PATH = (
    Path(settings.system_host_proc_path) if settings.system_host_proc_path else None
)
SYSTEM_HOST_DISK_PATH = (
    Path(settings.system_host_disk_path) if settings.system_host_disk_path else None
)
SYSTEM_CPU_SAMPLE_LOCK = Lock()
SYSTEM_CPU_SAMPLE: dict[str, dict[str, float]] = {}


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None


def _read_int(path: Path) -> int | None:
    raw = _read_text(path)
    if not raw or raw == "max":
        return None
    try:
        return int(raw.split()[0])
    except (TypeError, ValueError):
        return None


def _host_proc_root() -> Path | None:
    if not SYSTEM_HOST_PROC_PATH:
        return None
    if (SYSTEM_HOST_PROC_PATH / "stat").is_file() and (
        SYSTEM_HOST_PROC_PATH / "meminfo"
    ).is_file():
        return SYSTEM_HOST_PROC_PATH
    return None


def _host_disk_path() -> Path | None:
    if SYSTEM_HOST_DISK_PATH and SYSTEM_HOST_DISK_PATH.exists():
        return SYSTEM_HOST_DISK_PATH
    return None


def _clamp_percent(value: float | None) -> float | None:
    if value is None:
        return None
    return round(max(0.0, min(float(value), 100.0)), 1)


def _percent(used: int | None, total: int | None) -> float | None:
    if used is None or not total or total <= 0:
        return None
    return _clamp_percent((used / total) * 100)


def _parse_cpuset_count(value: str | None) -> int | None:
    if not value:
        return None
    count = 0
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if "-" not in item:
            count += 1
            continue
        start, end = item.split("-", 1)
        try:
            count += max(int(end) - int(start) + 1, 0)
        except ValueError:
            continue
    return count or None


def _cpu_quota_cores() -> float | None:
    cpu_max = _read_text(CGROUP_ROOT / "cpu.max")
    if cpu_max:
        parts = cpu_max.split()
        if len(parts) >= 2 and parts[0] != "max":
            try:
                quota = int(parts[0])
                period = int(parts[1])
                if quota > 0 and period > 0:
                    return max(quota / period, 0.01)
            except ValueError:
                pass
    for base in (CGROUP_ROOT / "cpu", CGROUP_ROOT / "cpu,cpuacct"):
        quota = _read_int(base / "cpu.cfs_quota_us")
        period = _read_int(base / "cpu.cfs_period_us")
        if quota and quota > 0 and period and period > 0:
            return max(quota / period, 0.01)
    return None


def _cpuset_cores() -> int | None:
    for path in (
        CGROUP_ROOT / "cpuset.cpus.effective",
        CGROUP_ROOT / "cpuset.cpus",
        CGROUP_ROOT / "cpuset" / "cpuset.cpus",
    ):
        count = _parse_cpuset_count(_read_text(path))
        if count:
            return count
    return None


def _cpu_capacity() -> float:
    quota = _cpu_quota_cores()
    cpuset = _cpuset_cores()
    available = float(cpuset or os.cpu_count() or 1)
    if quota:
        return max(min(quota, available), 0.01) if cpuset else max(quota, 0.01)
    return max(available, 1.0)


def _proc_cpu_count(proc_root: Path) -> int | None:
    raw = _read_text(proc_root / "cpuinfo")
    if not raw:
        return None
    count = sum(1 for line in raw.splitlines() if line.startswith("processor"))
    return count or None


def _cgroup_cpu_usage() -> tuple[float, str] | None:
    cpu_stat = _read_text(CGROUP_ROOT / "cpu.stat")
    if cpu_stat:
        for line in cpu_stat.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "usage_usec":
                try:
                    return int(parts[1]) / 1_000_000, "cgroup"
                except ValueError:
                    break
    for path in (
        CGROUP_ROOT / "cpuacct" / "cpuacct.usage",
        CGROUP_ROOT / "cpu,cpuacct" / "cpuacct.usage",
    ):
        usage_ns = _read_int(path)
        if usage_ns is not None:
            return usage_ns / 1_000_000_000, "cgroup"
    return None


def _proc_cpu_times(proc_root: Path = Path("/proc")) -> tuple[float, float] | None:
    raw = _read_text(proc_root / "stat")
    first_line = raw.splitlines()[0] if raw else ""
    parts = first_line.split()
    if not parts or parts[0] != "cpu":
        return None
    try:
        values = [float(value) for value in parts[1:]]
    except ValueError:
        return None
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def _cpu_metrics() -> dict[str, Any]:
    now = time.monotonic()
    host_proc = _host_proc_root()
    if host_proc:
        proc_times = _proc_cpu_times(host_proc)
        if proc_times:
            total, idle = proc_times
            with SYSTEM_CPU_SAMPLE_LOCK:
                previous = SYSTEM_CPU_SAMPLE.get("host-proc")
                percent = None
                if previous:
                    total_delta = total - previous.get("total", total)
                    idle_delta = idle - previous.get("idle", idle)
                    if total_delta > 0 and idle_delta >= 0:
                        percent = (1 - idle_delta / total_delta) * 100
                SYSTEM_CPU_SAMPLE["host-proc"] = {
                    "time": now,
                    "total": total,
                    "idle": idle,
                }
            return {
                "percent": _clamp_percent(percent),
                "cores": _proc_cpu_count(host_proc) or os.cpu_count() or 1,
                "source": "host-procfs",
            }

    capacity = _cpu_capacity()
    cgroup_usage = _cgroup_cpu_usage()
    with SYSTEM_CPU_SAMPLE_LOCK:
        if cgroup_usage:
            usage_seconds, source = cgroup_usage
            previous = SYSTEM_CPU_SAMPLE.get("cgroup")
            percent = None
            if previous:
                elapsed = now - previous.get("time", now)
                usage_delta = usage_seconds - previous.get("usage", usage_seconds)
                if elapsed > 0 and usage_delta >= 0:
                    percent = (usage_delta / elapsed / capacity) * 100
            SYSTEM_CPU_SAMPLE["cgroup"] = {"time": now, "usage": usage_seconds}
            return {
                "percent": _clamp_percent(percent),
                "cores": round(capacity, 2),
                "source": source,
            }

        proc_times = _proc_cpu_times()
        if proc_times:
            total, idle = proc_times
            previous = SYSTEM_CPU_SAMPLE.get("proc")
            percent = None
            if previous:
                total_delta = total - previous.get("total", total)
                idle_delta = idle - previous.get("idle", idle)
                if total_delta > 0 and idle_delta >= 0:
                    percent = (1 - idle_delta / total_delta) * 100
            SYSTEM_CPU_SAMPLE["proc"] = {"time": now, "total": total, "idle": idle}
            return {
                "percent": _clamp_percent(percent),
                "cores": round(capacity, 2),
                "source": "procfs",
            }
    return {"percent": None, "cores": round(capacity, 2), "source": "unavailable"}


def _proc_memory(proc_root: Path = Path("/proc")) -> tuple[int, int] | None:
    raw = _read_text(proc_root / "meminfo")
    if not raw:
        return None
    values: dict[str, int] = {}
    for line in raw.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.strip().split()
        if not key or not parts:
            continue
        try:
            values[key] = int(parts[0]) * 1024
        except ValueError:
            continue
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if total and available is not None:
        return total, available
    return None


def _cgroup_memory_limit() -> int | None:
    for path in (
        CGROUP_ROOT / "memory.max",
        CGROUP_ROOT / "memory" / "memory.limit_in_bytes",
    ):
        value = _read_int(path)
        if value and 0 < value < CGROUP_UNLIMITED_LIMIT:
            return value
    return None


def _cgroup_memory_current() -> int | None:
    for path in (
        CGROUP_ROOT / "memory.current",
        CGROUP_ROOT / "memory" / "memory.usage_in_bytes",
    ):
        value = _read_int(path)
        if value is not None:
            return max(value, 0)
    return None


def _memory_metrics() -> dict[str, Any]:
    host_proc = _host_proc_root()
    if host_proc:
        host_memory = _proc_memory(host_proc)
        if host_memory:
            total, available = host_memory
            used = max(total - available, 0)
            return {
                "usedBytes": used,
                "totalBytes": total,
                "freeBytes": available,
                "percent": _percent(used, total),
                "source": "host-procfs",
            }

    current = _cgroup_memory_current()
    limit = _cgroup_memory_limit()
    proc_memory = _proc_memory()
    if current is not None:
        total = limit or (proc_memory[0] if proc_memory else None)
        free = max(total - current, 0) if total else None
        return {
            "usedBytes": current,
            "totalBytes": total,
            "freeBytes": free,
            "percent": _percent(current, total),
            "source": "cgroup",
        }
    if proc_memory:
        total, available = proc_memory
        used = max(total - available, 0)
        return {
            "usedBytes": used,
            "totalBytes": total,
            "freeBytes": available,
            "percent": _percent(used, total),
            "source": "procfs",
        }
    return {
        "usedBytes": None,
        "totalBytes": None,
        "freeBytes": None,
        "percent": None,
        "source": "unavailable",
    }


def _disk_metrics() -> dict[str, Any]:
    host_disk = _host_disk_path()
    target = host_disk or Path("/")
    source = "host-statvfs" if host_disk else "statvfs"
    try:
        stat = os.statvfs(target)
    except OSError:
        return {
            "usedBytes": None,
            "totalBytes": None,
            "freeBytes": None,
            "percent": None,
            "path": "/" if host_disk else str(target),
            "source": "unavailable",
        }
    block_size = stat.f_frsize or stat.f_bsize
    total = stat.f_blocks * block_size
    free = stat.f_bavail * block_size
    used = max(total - stat.f_bfree * block_size, 0)
    return {
        "usedBytes": used,
        "totalBytes": total,
        "freeBytes": free,
        "percent": _percent(used, total),
        "path": "/",
        "source": source,
    }


def system_resource_metrics() -> dict[str, Any]:
    return {
        "cpu": _cpu_metrics(),
        "memory": _memory_metrics(),
        "disk": _disk_metrics(),
        "updatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "refreshIntervalSeconds": 3,
    }
