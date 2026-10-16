"""Teste E2E — Fluxo Completo de Produtos e Vendas.

Simula: cadastro de cliente → cadastro de produto com peso → cobrança direta → webhook pagamento → MCP.
"""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from tests.seed import seed_data, seed_payment


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": settings.admin_api_key}


class TestFluxoCompleto:
    """Fluxo: Cliente → Produto → Cobrança → Confirmação."""

    def test_cadastrar_usuario(self, client: TestClient, db_session: Session):
        resp = client.post("/api/users", json={
            "name": "João Silva",
            "phone": "+5511999999999",
            "email": "joao@email.com",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "João Silva"
        assert data["phone"] == "+5511999999999"
        assert "id" in data

    def test_cadastrar_produto_com_peso(self, client: TestClient, db_session: Session):
        resp = client.post(
            "/admin/api/products",
            json={
                "name": "Pomada Modeladora",
                "description": "Fixação forte acabamento fosco",
                "category": "Cabelo",
                "price_cents": 4500,
                "stock_quantity": 25,
                "weight_kg": 0.150,
            },
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Pomada Modeladora"
        assert data["price_cents"] == 4500
        assert float(data["weight_kg"]) == 0.150

    def test_criar_cobranca_direta_produto(self, client: TestClient, db_session: Session):
        from unittest.mock import patch

        from app.services.asaas_client import AsaasClient

        entities = seed_data(db_session)
        user = entities["user"]
        product = entities["product"]

        with patch.object(AsaasClient, "list_customers", new_callable=AsyncMock, return_value=[]), \
             patch.object(AsaasClient, "list_payments", new_callable=AsyncMock, return_value=[]), \
             patch.object(AsaasClient, "create_customer", new_callable=AsyncMock, return_value={"id": "cus_123"}), \
             patch.object(AsaasClient, "create_payment", new_callable=AsyncMock, return_value={
                 "id": "pay_prod_123",
                 "invoiceUrl": "https://asaas.test/pay_prod_123",
             }):

            resp = client.post(
                "/api/payments",
                json={
                    "user_id": user.id,
                    "product_id": product.id,
                    "billing_type": "PIX",
                },
                headers={"Authorization": f"Bearer {settings.api_key}"},
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["product_id"] == product.id
            assert data["amount_cents"] == product.price_cents
            assert data["status"] == "pending"

    def test_webhook_pagamento_recebido(self, client: TestClient, db_session: Session):
        entities = seed_data(db_session)
        pay = seed_payment(db_session, product=entities["product"], user=entities["user"])

        resp = client.post("/webhooks/asaas", json={
            "event": "PAYMENT_RECEIVED",
            "payment": {"id": pay.asaas_payment_id},
        }, headers={"asaas-access-token": settings.asaas_webhook_token})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_webhook_pagamento_duplicado(self, client: TestClient, db_session: Session):
        entities = seed_data(db_session)
        pay = seed_payment(db_session, product=entities["product"], user=entities["user"])

        client.post("/webhooks/asaas", json={
            "event": "PAYMENT_RECEIVED",
            "payment": {"id": pay.asaas_payment_id},
        }, headers={"asaas-access-token": settings.asaas_webhook_token})
        resp = client.post("/webhooks/asaas", json={
            "event": "PAYMENT_RECEIVED",
            "payment": {"id": pay.asaas_payment_id},
        }, headers={"asaas-access-token": settings.asaas_webhook_token})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    def test_mcp_tools_list_contem_produtos(self, client: TestClient, db_session: Session):
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 1,
        }, headers={"Authorization": f"Bearer {settings.api_key}"})
        assert resp.status_code == 200
        tools = resp.json()["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "listar_produtos" in names
        assert "consultar_produto" in names
        assert "criar_cobranca_asaas" in names
        assert "listar_servicos" not in names
        assert "listar_profissionais" not in names
        assert "verificar_disponibilidade" not in names

    def test_mcp_consultar_produto_com_peso(self, client: TestClient, db_session: Session):
        entities = seed_data(db_session)
        product = entities["product"]

        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 2,
            "params": {
                "name": "consultar_produto",
                "arguments": {
                    "product_id": product.id,
                },
            },
        }, headers={"Authorization": f"Bearer {settings.api_key}"})
        assert resp.status_code == 200
        text = resp.json()["result"]["content"][0]["text"]
        assert product.name in text
        assert "0.350 kg" in text
