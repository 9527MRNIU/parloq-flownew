from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from app.services.platform_clients import (
    BaoTaClient,
    CloudflareClient,
    NameSiloClient,
    PlatformClientError,
)
from app.services.domain_registrar import DomainRegistrarError, NameSiloDomainRegistrar


def test_namesilo_quote_and_purchase_parameters_match_the_old_integration() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        operation = request.url.path.rsplit("/", 1)[-1]
        if operation == "checkRegisterAvailability":
            return httpx.Response(
                200,
                json={
                    "reply": {
                        "code": 300,
                        "available": {"domain": {"domain": "example.com", "price": "12.00"}},
                    }
                },
            )
        if operation == "registerDomain":
            return httpx.Response(
                200,
                json={"reply": {"code": 300, "order_amount": "12.00"}},
            )
        raise AssertionError(f"unexpected operation {operation}")

    client = NameSiloClient(
        "secret-key",
        payment_id="2531590",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    try:
        available, price = client.check_availability("example.com")
        amount = client.register_domain(
            "example.com",
            1,
            private=True,
            auto_renew=False,
        )
    finally:
        client.close()

    assert available is True
    assert price == Decimal("12.00")
    assert amount == Decimal("12.00")
    purchase_query = requests[1].url.params
    assert purchase_query["domain"] == "example.com"
    assert purchase_query["years"] == "1"
    assert purchase_query["private"] == "1"
    assert purchase_query["auto_renew"] == "0"
    assert purchase_query["payment_id"] == "2531590"
    assert purchase_query["key"] == "secret-key"


def test_namesilo_searches_the_price_catalogue_then_checks_availability() -> None:
    requests: list[httpx.Request] = []
    progress = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        operation = request.url.path.rsplit("/", 1)[-1]
        if operation == "getPrices":
            return httpx.Response(
                200,
                json={
                    "reply": {
                        "code": 300,
                        "detail": "success",
                        "com": {"registration": "12.00", "renew": "15.00"},
                        "xyz": {"registration": "3.00", "renew": "4.00"},
                        "invalid": {"registration": "not-a-price"},
                    }
                },
            )
        if operation == "checkRegisterAvailability":
            assert request.url.params["domains"] == "brand.xyz,brand.com"
            return httpx.Response(
                200,
                json={
                    "reply": {
                        "code": 300,
                        "available": {
                            "domain": [
                                {
                                    "domain": "brand.xyz",
                                    "price": "2.50",
                                    "renew": "3.50",
                                },
                                {"domain": "brand.com"},
                            ]
                        },
                    }
                },
            )
        raise AssertionError(f"unexpected operation {operation}")

    client = NameSiloClient(
        "secret-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.batch_request_interval_seconds = 0
    report = client.search_available_domains("brand", on_progress=progress.append)

    assert [request.url.path for request in requests] == [
        "/apibatch/getPrices",
        "/apibatch/checkRegisterAvailability",
    ]
    assert report.searched_count == 2
    assert report.candidate_count == 2
    assert report.skipped_count == 0
    assert [option.domain for option in report.options] == ["brand.xyz", "brand.com"]
    assert report.options[0].registration_price == Decimal("2.50")
    assert report.options[0].renewal_price == Decimal("3.50")
    assert report.options[1].registration_price == Decimal("12.00")
    assert report.options[1].renewal_price == Decimal("15.00")
    assert progress[0].candidate_count == 2
    assert progress[0].searched_count == 0
    assert progress[-1] == report


def test_namesilo_search_splits_timed_out_batches_without_losing_progress() -> None:
    availability_calls: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        operation = request.url.path.rsplit("/", 1)[-1]
        if operation == "getPrices":
            return httpx.Response(
                200,
                json={
                    "reply": {
                        "code": 300,
                        **{
                            f"tld{index}": {
                                "registration": str(index + 1),
                                "renew": str(index + 2),
                            }
                            for index in range(11)
                        },
                    }
                },
            )
        if operation == "checkRegisterAvailability":
            domains = request.url.params["domains"].split(",")
            availability_calls.append(domains)
            if len(availability_calls) == 1:
                raise httpx.ReadTimeout("timeout", request=request)
            return httpx.Response(
                200,
                json={
                    "reply": {
                        "code": 300,
                        "available": {
                            "domain": [{"domain": domain} for domain in domains]
                        },
                    }
                },
            )
        raise AssertionError(f"unexpected operation {operation}")

    client = NameSiloClient(
        "secret-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.batch_request_interval_seconds = 0
    report = client.search_available_domains("brand")

    assert [len(domains) for domains in availability_calls] == [11, 5, 6]
    assert report.searched_count == 11
    assert report.candidate_count == 11
    assert report.skipped_count == 0
    assert len(report.options) == 11


def test_namesilo_purchase_timeout_is_marked_unknown_for_reconciliation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    client = NameSiloClient(
        "secret-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(PlatformClientError) as caught:
        client.register_domain(
            "example.com",
            1,
            private=True,
            auto_renew=False,
        )
    assert caught.value.outcome_unknown is True


def test_namesilo_without_payment_id_uses_account_balance() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"reply": {"code": 300, "order_amount": "12.00"}},
        )

    client = NameSiloClient(
        "secret-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    amount = client.register_domain(
        "example.com",
        1,
        private=True,
        auto_renew=False,
    )

    assert amount == Decimal("12.00")
    assert "payment_id" not in captured[0].url.params


def test_namesilo_connection_test_is_read_only() -> None:
    operations: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        operations.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(
            200,
            json={"reply": {"code": 300, "domains": [], "pager": {"total": 0}}},
        )

    client = NameSiloClient(
        "secret-key",
        payment_id="2531590",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.verify_connection()

    assert operations == ["listDomains"]


def test_namesilo_reads_account_balance_for_payment_readiness() -> None:
    operations: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        operation = request.url.path.rsplit("/", 1)[-1]
        operations.append(operation)
        assert operation == "getAccountBalance"
        return httpx.Response(
            200,
            json={"reply": {"code": 300, "balance": "42.37"}},
        )

    client = NameSiloClient(
        "secret-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.get_account_balance() == Decimal("42.37")
    assert operations == ["getAccountBalance"]


def test_namesilo_mit_payment_rejection_has_actionable_message() -> None:
    class RejectingClient:
        def register_domain(self, *args, **kwargs):
            raise PlatformClientError(
                "MIT charge requires mitIdentifier for CheckoutProfile",
                code="280",
            )

    registrar = NameSiloDomainRegistrar.__new__(NameSiloDomainRegistrar)
    registrar._client = RejectingClient()

    with pytest.raises(DomainRegistrarError) as raised:
        registrar.register("example.com", 1)

    assert "缺少自动扣款授权" in str(raised.value)
    assert "改用账户余额" in str(raised.value)
    assert raised.value.code == "280"


def test_namesilo_reads_nested_nameservers_and_updates_all_slots() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        operation = request.url.path.rsplit("/", 1)[-1]
        if operation == "getDomainInfo":
            return httpx.Response(
                200,
                json={
                    "reply": {
                        "code": 300,
                        "nameservers": {
                            "nameserver": [
                                "OLD-ONE.EXAMPLE.NET.",
                                "old-two.example.net",
                            ]
                        },
                    }
                },
            )
        if operation == "changeNameServers":
            return httpx.Response(200, json={"reply": {"code": 300}})
        raise AssertionError(f"unexpected operation {operation}")

    client = NameSiloClient(
        "secret-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    info = client.get_domain_info("example.com")
    client.change_name_servers(
        "example.com",
        ["elsa.ns.cloudflare.com", "ray.ns.cloudflare.com"],
    )

    assert info["nameservers"] == [
        "old-one.example.net",
        "old-two.example.net",
    ]
    params = requests[1].url.params
    assert params["domain"] == "example.com"
    assert params["ns1"] == "elsa.ns.cloudflare.com"
    assert params["ns2"] == "ray.ns.cloudflare.com"


def test_cloudflare_ensures_zone_dns_and_settings_idempotently() -> None:
    zone: dict[str, object] | None = None
    records: list[dict[str, object]] = []
    settings = {"ssl": "off"}
    mutations: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal zone
        path = request.url.path.removeprefix("/client/v4")
        if request.method == "GET" and path == "/zones":
            result = [zone] if zone is not None else []
            return httpx.Response(200, json={"success": True, "result": result})
        if request.method == "POST" and path == "/zones":
            mutations.append((request.method, path))
            zone = {
                "id": "zone-1",
                "name": "example.com",
                "status": "pending",
                "name_servers": ["elsa.ns.cloudflare.com", "ray.ns.cloudflare.com"],
            }
            return httpx.Response(200, json={"success": True, "result": zone})
        if request.method == "GET" and path == "/zones/zone-1/dns_records":
            selected = [
                row
                for row in records
                if row["type"] == request.url.params["type"]
                and row["name"] == request.url.params["name"]
            ]
            return httpx.Response(200, json={"success": True, "result": selected})
        if request.method == "POST" and path == "/zones/zone-1/dns_records":
            mutations.append((request.method, path))
            body = json.loads(request.content)
            row = {"id": f"record-{len(records) + 1}", **body}
            records.append(row)
            return httpx.Response(200, json={"success": True, "result": row})
        if request.method == "GET" and path == "/zones/zone-1/settings/ssl":
            return httpx.Response(
                200,
                json={"success": True, "result": {"id": "ssl", "value": settings["ssl"]}},
            )
        if request.method == "PATCH" and path == "/zones/zone-1/settings/ssl":
            mutations.append((request.method, path))
            settings["ssl"] = json.loads(request.content)["value"]
            return httpx.Response(200, json={"success": True, "result": {"value": settings["ssl"]}})
        raise AssertionError(f"unexpected request {request.method} {path}")

    http_client = httpx.Client(
        base_url=CloudflareClient.base_url,
        transport=httpx.MockTransport(handler),
    )
    client = CloudflareClient("token", account_id="account-1", client=http_client)

    assert client.find_zone("example.com") is None
    created = client.create_zone("example.com")
    assert created["id"] == "zone-1"
    first = client.ensure_dns_record(
        "zone-1",
        record_type="CNAME",
        name="example.com",
        content="center.parloq.com",
        proxied=True,
    )
    second = client.ensure_dns_record(
        "zone-1",
        record_type="CNAME",
        name="example.com",
        content="center.parloq.com",
        proxied=True,
    )
    client.ensure_zone_setting("zone-1", "ssl", "flexible")
    client.ensure_zone_setting("zone-1", "ssl", "flexible")

    assert first == second
    assert mutations == [
        ("POST", "/zones"),
        ("POST", "/zones/zone-1/dns_records"),
        ("PATCH", "/zones/zone-1/settings/ssl"),
    ]


def test_baota_creates_site_and_proxy_once_and_refuses_conflicts() -> None:
    site: dict[str, object] | None = None
    proxies: list[dict[str, object]] = []
    mutations: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal site
        action = request.url.params.get("action")
        if request.url.path == "/data" and action == "getData":
            return httpx.Response(200, json={"data": [site] if site else []})
        if request.url.path == "/site" and action == "AddSite":
            mutations.append("AddSite")
            site = {
                "id": 38,
                "name": "landing.example",
                "path": "/www/wwwroot/landing.example",
            }
            return httpx.Response(200, json={"status": True})
        if request.url.path == "/site" and action == "GetProxyList":
            return httpx.Response(200, json=proxies)
        if request.url.path == "/site" and action == "CreateProxy":
            mutations.append("CreateProxy")
            proxies.append(
                {
                    "proxydir": "/",
                    "proxysite": "http://127.0.0.1:18100",
                }
            )
            return httpx.Response(200, json={"status": True})
        raise AssertionError(f"unexpected request {request.url}")

    client = BaoTaClient(
        "https://panel.example",
        "baota-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    created = client.create_site("landing.example", "/www/wwwroot/landing.example")
    client.ensure_reverse_proxy("landing.example", "http://127.0.0.1:18100")
    client.ensure_reverse_proxy("landing.example", "http://127.0.0.1:18100")

    assert created["id"] == 38
    assert mutations == ["AddSite", "CreateProxy"]

    proxies[:] = [{"proxydir": "/", "proxysite": "http://127.0.0.1:9999"}]
    with pytest.raises(PlatformClientError, match="未进行覆盖"):
        client.ensure_reverse_proxy("landing.example", "http://127.0.0.1:18100")
    assert mutations == ["AddSite", "CreateProxy"]
