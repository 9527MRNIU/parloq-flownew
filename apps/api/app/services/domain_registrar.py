from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4


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


class DomainRegistrar:
    """Registrar boundary. Production adapters can implement this contract later."""

    def quote(self, hostname: str, years: int = 1) -> DomainQuote:
        raise NotImplementedError

    def register(self, hostname: str, years: int = 1) -> RegistrationResult:
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

    def register(self, hostname: str, years: int = 1) -> RegistrationResult:
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
