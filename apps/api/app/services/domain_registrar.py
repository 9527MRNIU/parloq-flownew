from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from app.services.platform_clients import NameSiloClient, PlatformClientError


class DomainRegistrarError(RuntimeError):
    pass


class DomainRegistrarUnknownError(DomainRegistrarError):
    def __init__(self, message: str, provider_order_ref: str):
        super().__init__(message)
        self.provider_order_ref = provider_order_ref


@dataclass(frozen=True, slots=True)
class DomainQuote:
    available: bool
    amount: Decimal
    currency: str = "USD"
    provider: str = "mock"


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    provider_order_ref: str
    amount: Decimal | None = None


class DomainRegistrar:
    """Registrar boundary. Production adapters can implement this contract later."""

    def quote(self, hostname: str, years: int = 1) -> DomainQuote:
        raise NotImplementedError

    def register(
        self,
        hostname: str,
        years: int = 1,
        *,
        private: bool = True,
        auto_renew: bool = False,
    ) -> RegistrationResult:
        raise NotImplementedError

    def reconcile(self, provider_order_ref: str | None, hostname: str) -> RegistrationResult:
        raise NotImplementedError


class MockDomainRegistrar(DomainRegistrar):
    _annual_prices = {
        "com": Decimal("12.00"),
        "net": Decimal("13.00"),
        "org": Decimal("11.00"),
        "xyz": Decimal("3.00"),
        "io": Decimal("36.00"),
    }

    def quote(self, hostname: str, years: int = 1) -> DomainQuote:
        tld = hostname.rsplit(".", 1)[-1]
        annual = self._annual_prices.get(tld, Decimal("15.00"))
        # Deterministic local-only unavailable fixtures are useful for UI/tests.
        available = not hostname.startswith(("taken.", "unavailable."))
        return DomainQuote(available=available, amount=annual * years)

    def register(
        self,
        hostname: str,
        years: int = 1,
        *,
        private: bool = True,
        auto_renew: bool = False,
    ) -> RegistrationResult:
        del private, auto_renew
        quote = self.quote(hostname, years)
        if not quote.available:
            raise DomainRegistrarError("域名已被注册")
        reference = f"mock_reg_{uuid4().hex}"
        if hostname.startswith("timeout."):
            raise DomainRegistrarUnknownError("注册商响应超时，结果未知", reference)
        return RegistrationResult(provider_order_ref=reference)

    def reconcile(self, provider_order_ref: str | None, hostname: str) -> RegistrationResult:
        if provider_order_ref is None:
            return RegistrationResult(provider_order_ref=f"mock_reg_reconciled_{uuid4().hex}")
        if not provider_order_ref.startswith("mock_reg_"):
            raise DomainRegistrarError("注册商订单号无效")
        return RegistrationResult(provider_order_ref=provider_order_ref)


class NameSiloDomainRegistrar(DomainRegistrar):
    def __init__(self, api_key: str, *, payment_id: str | None = None) -> None:
        self._client = NameSiloClient(api_key, payment_id=payment_id)

    def close(self) -> None:
        self._client.close()

    def quote(self, hostname: str, years: int = 1) -> DomainQuote:
        try:
            available, annual_amount = self._client.check_availability(hostname)
        except PlatformClientError as exc:
            raise DomainRegistrarError(str(exc)) from exc
        if available and annual_amount is None:
            raise DomainRegistrarError("NameSilo 未返回有效域名价格")
        return DomainQuote(
            available=available,
            amount=(annual_amount or Decimal("0")) * years,
            provider="namesilo",
        )

    def register(
        self,
        hostname: str,
        years: int = 1,
        *,
        private: bool = True,
        auto_renew: bool = False,
    ) -> RegistrationResult:
        reference = f"namesilo:{hostname}"
        try:
            amount = self._client.register_domain(
                hostname,
                years,
                private=private,
                auto_renew=auto_renew,
            )
        except PlatformClientError as exc:
            if exc.outcome_unknown:
                raise DomainRegistrarUnknownError(str(exc), reference) from exc
            raise DomainRegistrarError(str(exc)) from exc
        return RegistrationResult(provider_order_ref=reference, amount=amount)

    def reconcile(
        self,
        provider_order_ref: str | None,
        hostname: str,
    ) -> RegistrationResult:
        expected = f"namesilo:{hostname}"
        if provider_order_ref and provider_order_ref != expected:
            raise DomainRegistrarError("NameSilo 订单域名不匹配")
        try:
            owned = self._client.owns_domain(hostname)
        except PlatformClientError as exc:
            raise DomainRegistrarError(str(exc)) from exc
        if not owned:
            raise DomainRegistrarError("NameSilo 账户中尚未找到该域名")
        return RegistrationResult(provider_order_ref=expected)
