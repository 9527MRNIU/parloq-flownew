from __future__ import annotations

import ipaddress
import re
import socket
import ssl
from urllib.parse import urljoin

import httpx


class DomainVerifyError(Exception):
    pass


def _dns_answers(name: str, record_type: str, timeout: float) -> list[str]:
    try:
        response = httpx.get(
            "https://cloudflare-dns.com/dns-query",
            params={"name": name, "type": record_type},
            headers={"Accept": "application/dns-json"},
            timeout=timeout,
            follow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise DomainVerifyError("域名所有权 DNS 查询失败") from exc
    if int(payload.get("Status", -1)) != 0:
        return []
    return [
        str(answer.get("data", ""))
        for answer in payload.get("Answer", [])
        if str(answer.get("data", ""))
    ]


def _txt_value(raw: str) -> str:
    quoted = re.findall(r'"([^\"]*)"', raw)
    return "".join(quoted) if quoted else raw.strip().strip('"')


def verify_public_domain(
    hostname: str,
    *,
    verification_name: str,
    verification_value: str,
    cname_target: str,
    routing_probe_path: str | None = None,
    timeout: float = 5.0,
) -> None:
    txt_answers = _dns_answers(verification_name, "TXT", timeout)
    if verification_value not in {_txt_value(answer) for answer in txt_answers}:
        raise DomainVerifyError("未找到系统签发的 TXT 所有权验证记录")
    cname_answers = _dns_answers(hostname, "CNAME", timeout)
    expected_cname = cname_target.lower().rstrip(".")
    cname_matches = expected_cname in {
        answer.lower().rstrip(".") for answer in cname_answers
    }
    # A proxied Cloudflare CNAME intentionally answers with edge A/AAAA records,
    # so public DNS cannot reveal the configured CNAME. In that case, prove the
    # hostname is already reaching this application over trusted HTTPS instead.
    # TXT ownership remains mandatory in both modes.
    if not cname_matches:
        if not routing_probe_path or not routing_probe_path.startswith("/"):
            raise DomainVerifyError("域名尚未指向系统推广入口")
        try:
            response = httpx.get(
                urljoin(f"https://{hostname}", routing_probe_path),
                timeout=timeout,
                follow_redirects=False,
            )
            response.raise_for_status()
            data = response.json().get("data", {})
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            raise DomainVerifyError("域名尚未通过 HTTPS 接入系统推广入口") from exc
        if (
            data.get("hostname") != hostname
            or data.get("proof") != "parloq-domain-routing-v1"
        ):
            raise DomainVerifyError("域名 HTTPS 接入校验响应不匹配")
    try:
        addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise DomainVerifyError("域名 DNS 解析失败") from exc
    public_ips: list[str] = []
    for address in addresses:
        raw = str(address[4][0]).split("%", 1)[0]
        parsed = ipaddress.ip_address(raw)
        if not parsed.is_global:
            raise DomainVerifyError("安全策略禁止验证内网、回环或保留地址")
        if str(parsed) not in public_ips:
            public_ips.append(str(parsed))
    if not public_ips:
        raise DomainVerifyError("域名没有公网 DNS 记录")
    context = ssl.create_default_context()
    last_error: Exception | None = None
    for public_ip in public_ips:
        try:
            with socket.create_connection((public_ip, 443), timeout=timeout) as raw_socket:
                with context.wrap_socket(raw_socket, server_hostname=hostname):
                    return
        except (OSError, ssl.SSLError) as exc:
            last_error = exc
    raise DomainVerifyError("域名 SSL 验证失败") from last_error
