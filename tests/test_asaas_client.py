import asyncio
import json

import httpx
import pytest

from app.config import settings
from app.services.asaas_client import (
    AsaasClient,
    AsaasIntegrationError,
    AsaasUncertainResultError,
)


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler,
) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    transport = httpx.MockTransport(capture)
    monkeypatch.setattr(
        AsaasClient,
        "_get_client",
        lambda self: httpx.AsyncClient(
            transport=transport,
            headers=self.headers,
            timeout=self.timeout,
        ),
    )
    return requests


def test_client_uses_current_sandbox_url_and_user_agent(monkeypatch):
    requests = _install_transport(
        monkeypatch,
        lambda request: httpx.Response(200, json={"data": []}),
    )

    asyncio.run(AsaasClient().list_payments(external_reference="appointment:7"))

    request = requests[0]
    expected_base = settings.asaas_base_url.rstrip("/")
    assert str(request.url) == (
        f"{expected_base}/payments"
        "?limit=10&externalReference=appointment%3A7"
    )
    assert request.headers["access_token"] == settings.asaas_api_key
    assert request.headers["user-agent"].startswith(settings.app_name)


def test_create_customer_sends_external_reference(monkeypatch):
    requests = _install_transport(
        monkeypatch,
        lambda request: httpx.Response(200, json={"id": "cus_1"}),
    )

    asyncio.run(
        AsaasClient().create_customer(
            name="Cliente",
            phone="11999999999",
            external_reference="user:4",
        )
    )

    assert json.loads(requests[0].content)["externalReference"] == "user:4"


def test_create_payment_sends_external_reference(monkeypatch):
    requests = _install_transport(
        monkeypatch,
        lambda request: httpx.Response(200, json={"id": "pay_1"}),
    )

    asyncio.run(
        AsaasClient().create_payment(
            customer_id="cus_1",
            value=50,
            due_date="2026-08-25",
            billing_type="PIX",
            external_reference="appointment:12",
        )
    )

    assert json.loads(requests[0].content)["externalReference"] == "appointment:12"


def test_mutating_timeout_is_not_retried(monkeypatch):
    calls = 0

    def timeout(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("unknown result")

    _install_transport(monkeypatch, timeout)

    with pytest.raises(AsaasUncertainResultError):
        asyncio.run(
            AsaasClient().create_payment(
                customer_id="cus_1",
                value=50,
                due_date="2026-08-25",
                billing_type="PIX",
                external_reference="appointment:12",
            )
        )

    assert calls == 1


@pytest.mark.parametrize(
    "error_type",
    [httpx.ReadError, httpx.RemoteProtocolError],
    ids=["read-error", "remote-protocol-error"],
)
def test_mutating_transport_failures_are_uncertain_and_not_retried(
    monkeypatch, error_type
):
    calls = 0

    def transport_failure(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise error_type("unknown result", request=request)

    _install_transport(monkeypatch, transport_failure)

    with pytest.raises(AsaasUncertainResultError):
        asyncio.run(
            AsaasClient().create_payment(
                customer_id="cus_1",
                value=50,
                due_date="2026-08-25",
                billing_type="PIX",
                external_reference="appointment:12",
            )
        )

    assert calls == 1


def test_mutating_server_error_is_uncertain_and_not_retried(monkeypatch):
    requests = _install_transport(
        monkeypatch,
        lambda _request: httpx.Response(503, json={"message": "unavailable"}),
    )

    with pytest.raises(AsaasUncertainResultError):
        asyncio.run(
            AsaasClient().create_payment(
                customer_id="cus_1",
                value=50,
                due_date="2026-08-25",
                billing_type="PIX",
                external_reference="appointment:12",
            )
        )

    assert len(requests) == 1


def test_non_success_response_becomes_integration_error(monkeypatch):
    _install_transport(
        monkeypatch,
        lambda request: httpx.Response(
            422,
            json={"errors": [{"description": "invalid customer"}]},
        ),
    )

    with pytest.raises(AsaasIntegrationError, match="invalid customer"):
        asyncio.run(AsaasClient().get_payment("pay_bad"))


def test_refund_posts_to_provider(monkeypatch):
    requests = _install_transport(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={"id": "pay_1", "status": "REFUNDED"},
        ),
    )

    result = asyncio.run(AsaasClient().refund_payment("pay_1"))

    assert requests[0].method == "POST"
    assert requests[0].url.path == "/v3/payments/pay_1/refund"
    assert result["status"] == "REFUNDED"
