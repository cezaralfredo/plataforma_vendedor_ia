import asyncio
import logging
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.asaas_client import AsaasClient
from app.services.payment_service import PaymentService
from app.services.user_service import UserService
from tests.seed import seed_appointment, seed_data, seed_payment


def test_mcp_does_not_return_internal_exception(
    client: TestClient,
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(
        UserService,
        "update",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("database password leaked")
        ),
    )
    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 1,
                "params": {
                    "name": "atualizar_cliente",
                    "arguments": {"user_id": 1, "name": "Ana"},
                },
            },
        )
    text = response.json()["result"]["content"][0]["text"]
    assert "database password leaked" not in text
    assert "database password leaked" in caplog.text


def test_recent_payment_failure_is_logged(
    db_session: Session,
    monkeypatch,
    caplog,
):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    payment = seed_payment(db_session, appointment)
    monkeypatch.setattr(
        AsaasClient,
        "get_payment",
        AsyncMock(side_effect=RuntimeError("provider offline")),
    )
    with caplog.at_level(logging.ERROR):
        asyncio.run(PaymentService(db_session).verify_recent_payments())
    assert f"payment_id={payment.id}" in caplog.text
