from __future__ import annotations

import ipaddress
import socket


class ProxyHealthError(Exception):
    pass


def check_public_tcp_reachability(host: str, port: int, timeout: float = 5.0) -> None:
    """Check endpoint reachability without allowing probes to private/internal addresses.

    This v1 check verifies only that the public proxy TCP port accepts a connection. It
    deliberately does not request internal URLs or send the stored proxy credentials.
    """

    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ProxyHealthError("代理主机无法解析") from exc
    public_ips: list[str] = []
    for address in addresses:
        raw_ip = str(address[4][0]).split("%", 1)[0]
        try:
            parsed = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        if not parsed.is_global:
            raise ProxyHealthError("安全策略禁止探测内网、回环或保留地址")
        if str(parsed) not in public_ips:
            public_ips.append(str(parsed))
    if not public_ips:
        raise ProxyHealthError("代理主机没有可用的公网地址")
    last_error: OSError | None = None
    for public_ip in public_ips:
        try:
            with socket.create_connection((public_ip, port), timeout=timeout):
                return
        except OSError as exc:
            last_error = exc
    raise ProxyHealthError("代理端口连接失败") from last_error
