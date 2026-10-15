"""
Teste das ferramentas MCP de gestão de clientes:
buscar_cliente_por_telefone, cadastrar_cliente, atualizar_cliente, vincular_whatsapp
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.repositories import UserRepository
from tests.seed import seed_data


def _mcp_call(client: TestClient, name: str, arguments: dict):
    return client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": 1,
        "params": {"name": name, "arguments": arguments},
    }, headers={"Authorization": f"Bearer {settings.api_key}"})


class TestMCPClientes:

    def test_tools_list_inclui_ferramentas_de_cliente(self, client: TestClient, db_session: Session):
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 1,
        }, headers={"Authorization": f"Bearer {settings.api_key}"})
        assert resp.status_code == 200
        names = [t["name"] for t in resp.json()["result"]["tools"]]
        assert "buscar_cliente_por_telefone" in names
        assert "cadastrar_cliente" in names
        assert "atualizar_cliente" in names
        assert "vincular_whatsapp" in names

    def test_cadastrar_cliente(self, client: TestClient, db_session: Session):
        resp = _mcp_call(client, "cadastrar_cliente", {
            "name": "Ana Pereira",
            "phone": "5511988881111",
            "email": "ana@email.com",
            "whatsapp_number": "5511988881111",
        })
        assert resp.status_code == 200
        text = resp.json()["result"]["content"][0]["text"]
        assert "Cliente cadastrado" in text
        assert "Ana Pereira" in text

        user = UserRepository(db_session).find_by_phone("5511988881111")
        assert user is not None
        assert user.whatsapp_number == "5511988881111"

    def test_cadastrar_cliente_duplicado_retorna_erro(self, client: TestClient, db_session: Session):
        seed_data(db_session)
        resp = _mcp_call(client, "cadastrar_cliente", {
            "name": "Outra Pessoa",
            "phone": "+5511999999999",
        })
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result.get("isError") is True
        assert "cadastrado" in result["content"][0]["text"]

    def test_buscar_cliente_por_telefone(self, client: TestClient, db_session: Session):
        seed_data(db_session)
        resp = _mcp_call(client, "buscar_cliente_por_telefone", {
            "phone": "+5511999999999",
        })
        assert resp.status_code == 200
        text = resp.json()["result"]["content"][0]["text"]
        assert "João Silva" in text
        assert "+5511999999999" in text

    def test_buscar_cliente_inexistente(self, client: TestClient, db_session: Session):
        resp = _mcp_call(client, "buscar_cliente_por_telefone", {
            "phone": "5511999990000",
        })
        assert resp.status_code == 200
        text = resp.json()["result"]["content"][0]["text"]
        assert "não encontrado" in text

    def test_buscar_cliente_arquivado_nao_o_expoe(self, client: TestClient, db_session: Session):
        entities = seed_data(db_session)
        entities["user"].active = False
        db_session.commit()

        resp = _mcp_call(client, "buscar_cliente_por_telefone", {
            "phone": entities["user"].phone,
        })

        assert resp.status_code == 200
        assert "não encontrado" in resp.json()["result"]["content"][0]["text"]

    def test_atualizar_cliente(self, client: TestClient, db_session: Session):
        entities = seed_data(db_session)
        resp = _mcp_call(client, "atualizar_cliente", {
            "user_id": entities["user"].id,
            "name": "João Silva Atualizado",
            "email": "joao.novo@email.com",
        })
        assert resp.status_code == 200
        text = resp.json()["result"]["content"][0]["text"]
        assert "Cliente atualizado" in text
        assert "João Silva Atualizado" in text

        user = UserRepository(db_session).get(entities["user"].id)
        assert user.name == "João Silva Atualizado"
        assert user.email == "joao.novo@email.com"

    def test_atualizar_cliente_inexistente(self, client: TestClient, db_session: Session):
        resp = _mcp_call(client, "atualizar_cliente", {
            "user_id": 99999,
            "name": "Ninguém",
        })
        assert resp.status_code == 200
        text = resp.json()["result"]["content"][0]["text"]
        assert "não encontrado" in text

    def test_vincular_whatsapp(self, client: TestClient, db_session: Session):
        entities = seed_data(db_session)
        resp = _mcp_call(client, "vincular_whatsapp", {
            "user_id": entities["user"].id,
            "whatsapp_number": "5511988887777",
        })
        assert resp.status_code == 200
        text = resp.json()["result"]["content"][0]["text"]
        assert "WhatsApp vinculado" in text
        assert "5511988887777" in text

        user = UserRepository(db_session).get(entities["user"].id)
        assert user.whatsapp_number == "5511988887777"

    def test_vincular_whatsapp_cliente_inexistente(self, client: TestClient, db_session: Session):
        resp = _mcp_call(client, "vincular_whatsapp", {
            "user_id": 99999,
            "whatsapp_number": "5511988887777",
        })
        assert resp.status_code == 200
        text = resp.json()["result"]["content"][0]["text"]
        assert "não encontrado" in text
