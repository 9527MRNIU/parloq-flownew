from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from threading import Lock
from typing import Callable, Mapping

import httpx


class PlatformClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        outcome_unknown: bool = False,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.outcome_unknown = outcome_unknown
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class NameSiloDomainOption:
    domain: str
    registration_price: Decimal
    renewal_price: Decimal | None


@dataclass(frozen=True, slots=True)
class NameSiloDomainSearchReport:
    options: tuple[NameSiloDomainOption, ...]
    searched_count: int
    candidate_count: int
    skipped_count: int = 0

    @property
    def partial(self) -> bool:
        return self.skipped_count > 0


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return list(value)
    return [value]


def _domain_rows(value: object) -> list[dict[str, object]]:
    container = _mapping(value)
    nested = container.get("domain")
    rows = nested if isinstance(nested, Mapping | list | tuple) else value
    result: list[dict[str, object]] = []
    for item in _list(rows):
        mapped = _mapping(item)
        if mapped:
            result.append(mapped)
        elif str(item).strip():
            result.append({"domain": str(item).strip()})
    return result


def _decimal(value: object) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


class NameSiloClient:
    base_url = "https://www.namesilo.com/api"
    batch_base_url = "https://www.namesilo.com/apibatch"
    availability_batch_size = 40
    minimum_split_size = 10
    batch_request_interval_seconds = 1.0
    _batch_request_lock = Lock()
    _last_batch_request_at = 0.0

    def __init__(
        self,
        api_key: str,
        *,
        payment_id: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._payment_id = str(payment_id or "").strip() or None
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(10.0, connect=5.0)
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _request(
        self,
        operation: str,
        *,
        success_codes: frozenset[str] = frozenset({"300"}),
        mutation: bool = False,
        batch: bool = False,
        **params: object,
    ) -> dict[str, object]:
        if batch:
            client_type = type(self)
            with client_type._batch_request_lock:
                elapsed = time.monotonic() - client_type._last_batch_request_at
                if elapsed < self.batch_request_interval_seconds:
                    time.sleep(self.batch_request_interval_seconds - elapsed)
                client_type._last_batch_request_at = time.monotonic()
        try:
            response = self._client.get(
                f"{self.batch_base_url if batch else self.base_url}/{operation}",
                params={"version": "1", "type": "json", "key": self._api_key, **params},
            )
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.TimeoutException):
            raise PlatformClientError(
                "NameSilo 响应超时",
                code="timeout",
                outcome_unknown=mutation,
                retryable=True,
            ) from None
        except httpx.HTTPError:
            raise PlatformClientError(
                "NameSilo 连接失败",
                code="connection_error",
                outcome_unknown=mutation,
                retryable=True,
            ) from None
        try:
            payload = _mapping(response.json())
        except ValueError:
            raise PlatformClientError(
                "NameSilo 返回了无法识别的响应",
                outcome_unknown=mutation and response.status_code >= 500,
            ) from None
        reply = _mapping(payload.get("reply"))
        code = str(reply.get("code") or "")
        if response.is_error or code not in success_codes:
            detail = str(reply.get("detail") or reply.get("message") or "NameSilo 请求失败")
            detail = detail.replace(self._api_key, "[redacted]").split("?", 1)[0]
            raise PlatformClientError(
                detail,
                code=code or str(response.status_code),
                outcome_unknown=mutation and response.status_code >= 500,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        return reply

    def _tld_prices(self) -> list[tuple[str, Decimal, Decimal | None]]:
        reply = self._request("getPrices", batch=True)
        prices: list[tuple[str, Decimal, Decimal | None]] = []
        for raw_tld, raw_price in reply.items():
            tld = str(raw_tld).strip().lower().lstrip(".")
            price = _mapping(raw_price)
            registration = _decimal(price.get("registration"))
            if not tld or registration is None:
                continue
            prices.append((tld, registration, _decimal(price.get("renew"))))
        return sorted(
            prices,
            key=lambda item: (
                item[1],
                item[2] if item[2] is not None else Decimal("Infinity"),
                item[0],
            ),
        )

    def search_available_domains(
        self,
        label: str,
        *,
        deadline_seconds: float = 180.0,
        on_progress: Callable[[NameSiloDomainSearchReport], None] | None = None,
    ) -> NameSiloDomainSearchReport:
        """Return purchasable label/TLD combinations using NameSilo's batch APIs.

        NameSilo's price feed is the suffix catalogue. Availability is checked
        separately in batches, exactly as in the legacy management system.
        Timed-out requests are split down to small batches so one slow suffix
        group does not discard the whole result set. Other transient failures
        are counted as skipped and surfaced as a partial result.
        """

        started_at = time.monotonic()
        prices = self._tld_prices()
        price_by_domain = {
            f"{label}.{tld}": (registration, renewal)
            for tld, registration, renewal in prices
        }
        candidates = list(price_by_domain)
        candidate_count = len(candidates)
        searched_count = 0
        skipped_count = 0
        options: list[NameSiloDomainOption] = []

        def report() -> NameSiloDomainSearchReport:
            value = NameSiloDomainSearchReport(
                options=tuple(options),
                searched_count=searched_count,
                candidate_count=candidate_count,
                skipped_count=skipped_count,
            )
            if on_progress is not None:
                on_progress(value)
            return value

        def check_batch(domains: list[str]) -> None:
            nonlocal searched_count, skipped_count
            if not domains:
                return
            if time.monotonic() - started_at >= deadline_seconds:
                skipped_count += len(domains)
                searched_count += len(domains)
                report()
                return
            try:
                reply = self._request(
                    "checkRegisterAvailability",
                    batch=True,
                    domains=",".join(domains),
                )
            except PlatformClientError as exc:
                if exc.code == "timeout" and len(domains) > self.minimum_split_size:
                    midpoint = len(domains) // 2
                    check_batch(domains[:midpoint])
                    check_batch(domains[midpoint:])
                    return
                if exc.retryable:
                    skipped_count += len(domains)
                    searched_count += len(domains)
                    report()
                    return
                raise

            available_rows = {
                str(row.get("domain") or "").strip().lower(): row
                for row in _domain_rows(reply.get("available"))
            }
            for domain in domains:
                row = available_rows.get(domain)
                if row is None:
                    continue
                fallback_registration, renewal = price_by_domain[domain]
                registration = _decimal(row.get("price")) or fallback_registration
                renewal = _decimal(row.get("renew")) or renewal
                options.append(
                    NameSiloDomainOption(
                        domain=domain,
                        registration_price=registration,
                        renewal_price=renewal,
                    )
                )
            searched_count += len(domains)
            report()

        report()
        for offset in range(0, candidate_count, self.availability_batch_size):
            check_batch(candidates[offset : offset + self.availability_batch_size])
        options.sort(
            key=lambda item: (
                item.registration_price,
                item.renewal_price
                if item.renewal_price is not None
                else Decimal("Infinity"),
                item.domain,
            )
        )
        return report()

    def verify_connection(self) -> None:
        self._request("listDomains", page=1, pageSize=1)

    def check_availability(self, domain: str) -> tuple[bool, Decimal | None]:
        reply = self._request("checkRegisterAvailability", domains=domain)
        normalized = domain.lower()
        available_row = next(
            (
                row
                for row in _domain_rows(reply.get("available"))
                if str(row.get("domain") or "").lower() == normalized
            ),
            None,
        )
        unavailable = any(
            str(row.get("domain") or "").lower() == normalized
            for row in _domain_rows(reply.get("unavailable"))
        )
        available = available_row is not None and not unavailable
        price = _decimal(available_row.get("price")) if available_row else None
        if available and price is None:
            prices = self._request("getPrices")
            price = _decimal(_mapping(prices.get(domain.rsplit(".", 1)[-1])).get("registration"))
        return available, price

    def register_domain(
        self,
        domain: str,
        years: int,
        *,
        private: bool,
        auto_renew: bool,
    ) -> Decimal:
        params: dict[str, object] = {
            "domain": domain,
            "years": years,
            "private": "1" if private else "0",
            "auto_renew": "1" if auto_renew else "0",
        }
        if self._payment_id:
            params["payment_id"] = self._payment_id
        reply = self._request(
            "registerDomain",
            success_codes=frozenset({"300", "301", "302"}),
            mutation=True,
            **params,
        )
        amount = _decimal(reply.get("order_amount"))
        if amount is None:
            raise PlatformClientError("NameSilo 未返回有效订单金额", outcome_unknown=True)
        return amount

    def owns_domain(self, domain: str) -> bool:
        try:
            self._request("getDomainInfo", domain=domain)
            return True
        except PlatformClientError as exc:
            message = str(exc).lower()
            if exc.code == "280" or "does not belong" in message or "not active" in message:
                return False
            raise

    def get_domain_info(self, domain: str) -> dict[str, object]:
        reply = self._request("getDomainInfo", domain=domain)
        nameservers: list[str] = []
        raw = reply.get("nameservers") or reply.get("name_servers")

        def collect(value: object) -> None:
            if isinstance(value, Mapping):
                mapped = _mapping(value)
                hostname = mapped.get("nameserver") or mapped.get("host") or mapped.get("name")
                if hostname is not None:
                    collect(hostname)
                    return
                for nested in mapped.values():
                    collect(nested)
                return
            if isinstance(value, list | tuple):
                for nested in value:
                    collect(nested)
                return
            hostname = str(value or "").strip().lower().rstrip(".")
            if hostname and hostname not in nameservers:
                nameservers.append(hostname)

        collect(raw)
        return {"domain": domain.lower(), "nameservers": nameservers, "raw": reply}

    def change_name_servers(self, domain: str, nameservers: list[str]) -> None:
        normalized = [value.strip().lower().rstrip(".") for value in nameservers if value.strip()]
        if not 2 <= len(normalized) <= 13:
            raise PlatformClientError("NameSilo 至少需要 2 个有效域名服务器")
        if any(
            not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value)
            for value in normalized
        ):
            raise PlatformClientError("Cloudflare 返回了无效的域名服务器")
        self._request(
            "changeNameServers",
            mutation=True,
            domain=domain,
            **{f"ns{index}": value for index, value in enumerate(normalized, start=1)},
        )


class CloudflareClient:
    base_url = "https://api.cloudflare.com/client/v4"

    def __init__(
        self,
        api_token: str,
        *,
        account_id: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_token = api_token
        self._account_id = str(account_id or "").strip() or None
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(10.0, connect=5.0),
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json_body: dict[str, object] | None = None,
        mutation: bool = False,
    ) -> dict[str, object]:
        try:
            response = self._client.request(
                method,
                path,
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {self._api_token}"},
            )
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.TimeoutException):
            raise PlatformClientError(
                "Cloudflare 响应超时",
                outcome_unknown=mutation,
            ) from None
        except httpx.HTTPError:
            raise PlatformClientError(
                "Cloudflare 连接失败",
                outcome_unknown=mutation,
            ) from None
        try:
            payload = _mapping(response.json())
        except ValueError:
            raise PlatformClientError(
                "Cloudflare 返回了无法识别的响应",
                outcome_unknown=mutation and response.status_code >= 500,
            ) from None
        if response.is_error or payload.get("success") is not True:
            errors = _list(payload.get("errors"))
            first = _mapping(errors[0]) if errors else {}
            message = str(first.get("message") or "Cloudflare 请求失败")
            raise PlatformClientError(
                message.replace(self._api_token, "[redacted]"),
                code=str(first.get("code") or response.status_code),
                outcome_unknown=mutation and response.status_code >= 500,
            )
        return payload

    def _get(self, path: str, **params: object) -> dict[str, object]:
        return self._request("GET", path, params=dict(params) or None)

    def verify_connection(self) -> list[dict[str, str]]:
        token = _mapping(self._get("/user/tokens/verify").get("result"))
        if str(token.get("status") or "").lower() != "active":
            raise PlatformClientError("Cloudflare API Token 未激活")
        rows = self._get("/accounts", page=1, per_page=50).get("result")
        if not isinstance(rows, list):
            raise PlatformClientError("Cloudflare 账户响应无效")
        return [
            {"id": str(row.get("id") or ""), "name": str(row.get("name") or "")}
            for value in rows
            if (row := _mapping(value)) and str(row.get("id") or "")
        ]

    def find_zone(self, domain: str) -> dict[str, object] | None:
        params: dict[str, object] = {"name": domain, "page": 1, "per_page": 50}
        if self._account_id:
            params["account.id"] = self._account_id
        rows = self._get("/zones", **params).get("result")
        if not isinstance(rows, list):
            raise PlatformClientError("Cloudflare Zone 响应无效")
        normalized = domain.lower().rstrip(".")
        for value in rows:
            row = _mapping(value)
            if str(row.get("name") or "").lower().rstrip(".") == normalized:
                return row
        return None

    def create_zone(self, domain: str) -> dict[str, object]:
        if not self._account_id:
            raise PlatformClientError("请先在系统配置中选择 Cloudflare 账户")
        payload = self._request(
            "POST",
            "/zones",
            json_body={
                "account": {"id": self._account_id},
                "name": domain,
                "type": "full",
            },
            mutation=True,
        )
        result = _mapping(payload.get("result"))
        if not result.get("id"):
            raise PlatformClientError("Cloudflare 未返回 Zone ID", outcome_unknown=True)
        return result

    def list_dns_records(
        self,
        zone_id: str,
        *,
        record_type: str,
        name: str,
    ) -> list[dict[str, object]]:
        rows = self._get(
            f"/zones/{zone_id}/dns_records",
            type=record_type,
            name=name,
            page=1,
            per_page=100,
        ).get("result")
        if not isinstance(rows, list):
            raise PlatformClientError("Cloudflare DNS 响应无效")
        return [_mapping(value) for value in rows if _mapping(value)]

    def ensure_dns_record(
        self,
        zone_id: str,
        *,
        record_type: str,
        name: str,
        content: str,
        proxied: bool = False,
    ) -> dict[str, object]:
        desired = {
            "type": record_type,
            "name": name,
            "content": content,
            "ttl": 1,
            "proxied": bool(proxied and record_type in {"A", "AAAA", "CNAME"}),
        }
        rows = self.list_dns_records(zone_id, record_type=record_type, name=name)
        if len(rows) > 1:
            raise PlatformClientError(f"Cloudflare 中存在多个同名 {record_type} 记录，请先人工整理")
        if rows:
            current = rows[0]
            if (
                str(current.get("content") or "").rstrip(".").lower()
                == content.rstrip(".").lower()
                and bool(current.get("proxied")) == desired["proxied"]
            ):
                return current
            record_id = str(current.get("id") or "")
            if not record_id:
                raise PlatformClientError("Cloudflare DNS 记录缺少 ID")
            result = self._request(
                "PUT",
                f"/zones/{zone_id}/dns_records/{record_id}",
                json_body=desired,
                mutation=True,
            ).get("result")
        else:
            result = self._request(
                "POST",
                f"/zones/{zone_id}/dns_records",
                json_body=desired,
                mutation=True,
            ).get("result")
        row = _mapping(result)
        if not row.get("id"):
            raise PlatformClientError("Cloudflare 未确认 DNS 记录写入", outcome_unknown=True)
        return row

    def ensure_zone_setting(self, zone_id: str, setting: str, value: object) -> None:
        current = _mapping(self._get(f"/zones/{zone_id}/settings/{setting}").get("result"))
        if current.get("value") == value:
            return
        self._request(
            "PATCH",
            f"/zones/{zone_id}/settings/{setting}",
            json_body={"value": value},
            mutation=True,
        )


class BaoTaClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(10.0, connect=5.0)
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _signed_form(self, data: Mapping[str, object]) -> dict[str, object]:
        request_time = str(int(time.time()))
        inner = hashlib.md5(self._api_key.encode("utf-8")).hexdigest()
        request_token = hashlib.md5(f"{request_time}{inner}".encode("utf-8")).hexdigest()
        return {"request_time": request_time, "request_token": request_token, **dict(data)}

    def _post(
        self,
        path: str,
        *,
        data: Mapping[str, object],
        mutation: bool = False,
    ) -> object:
        form = self._signed_form(data)
        try:
            response = self._client.post(f"{self._base_url}{path}", data=form)
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.TimeoutException):
            raise PlatformClientError("宝塔面板响应超时", outcome_unknown=mutation) from None
        except httpx.HTTPError:
            raise PlatformClientError("宝塔面板连接失败", outcome_unknown=mutation) from None
        try:
            payload = response.json()
        except ValueError:
            raise PlatformClientError(
                "宝塔面板返回了无法识别的响应",
                outcome_unknown=mutation and response.status_code >= 500,
            ) from None
        if response.is_error:
            raise PlatformClientError(
                "宝塔面板请求失败",
                outcome_unknown=mutation and response.status_code >= 500,
            )
        if isinstance(payload, Mapping) and payload.get("status") is False:
            message = str(payload.get("msg") or payload.get("message") or "宝塔请求失败")
            raise PlatformClientError(
                message.replace(str(form["request_token"]), "[redacted]"),
                outcome_unknown=mutation and response.status_code >= 500,
            )
        return payload

    def verify_connection(self) -> None:
        self._post(
            "/data?action=getData&table=sites",
            data={
                "p": 1,
                "limit": 1,
                "type": -1,
                "order": "id desc",
                "tojs": "get_site_list",
                "search": "",
            },
        )

    def find_site(self, name: str) -> dict[str, object] | None:
        payload = self._post(
            "/data?action=getData&table=sites",
            data={
                "p": 1,
                "limit": 100,
                "type": -1,
                "order": "id desc",
                "tojs": "get_site_list",
                "search": name,
            },
        )
        rows: object = _mapping(payload).get("data") if isinstance(payload, Mapping) else payload
        for value in _list(rows):
            row = _mapping(value)
            if str(row.get("name") or "").lower().rstrip(".") == name.lower().rstrip("."):
                return row
        return None

    def create_site(self, name: str, path: str) -> dict[str, object]:
        if not re.fullmatch(r"[a-z0-9.-]{1,253}", name):
            raise PlatformClientError("宝塔站点域名无效")
        self._post(
            "/site?action=AddSite",
            mutation=True,
            data={
                "webname": json.dumps(
                    {"domain": name, "domainlist": [], "count": 0},
                    separators=(",", ":"),
                ),
                "path": path,
                "type_id": 0,
                "type": "PHP",
                "version": "00",
                "port": "80",
                "ps": "Parloq Flow 自动接入",
                "ftp": "false",
                "sql": "false",
                "codeing": "utf8",
            },
        )
        site = self.find_site(name)
        if site is None:
            raise PlatformClientError("宝塔未确认站点创建结果", outcome_unknown=True)
        return site

    def list_proxies(self, site_name: str) -> list[dict[str, object]]:
        payload = self._post(
            "/site?action=GetProxyList",
            data={"sitename": site_name},
        )
        rows: object
        if isinstance(payload, Mapping):
            rows = payload.get("data") or payload.get("message") or []
        else:
            rows = payload
        return [_mapping(value) for value in _list(rows) if _mapping(value)]

    @staticmethod
    def _proxy_target(row: Mapping[str, object]) -> str:
        return str(row.get("proxysite") or row.get("proxy_pass") or "").rstrip("/")

    def reverse_proxy_state(self, site_name: str, upstream: str) -> str:
        rows = self.list_proxies(site_name)
        root_rows = [
            row
            for row in rows
            if str(row.get("proxydir") or row.get("proxy_dir") or "/") in {"", "/"}
        ]
        if not root_rows:
            return "missing"
        if len(root_rows) == 1 and self._proxy_target(root_rows[0]) == upstream.rstrip("/"):
            return "exact"
        return "conflict"

    def ensure_reverse_proxy(
        self,
        site_name: str,
        upstream: str,
        *,
        proxy_name: str = "parloq-flow",
    ) -> None:
        state = self.reverse_proxy_state(site_name, upstream)
        if state == "exact":
            return
        if state == "conflict":
            raise PlatformClientError("宝塔站点已有不同的根路径反向代理，未进行覆盖")
        self._post(
            "/site?action=CreateProxy",
            mutation=True,
            data={
                "sitename": site_name,
                "proxyname": proxy_name,
                "proxydir": "/",
                "proxysite": upstream.rstrip("/"),
                "todomain": site_name,
                "type": "1",
                "cache": "0",
                "cachetime": "0",
                "subfilter": "[]",
                "advanced": "0",
            },
        )
        if self.reverse_proxy_state(site_name, upstream) != "exact":
            raise PlatformClientError("宝塔未确认反向代理创建结果", outcome_unknown=True)
