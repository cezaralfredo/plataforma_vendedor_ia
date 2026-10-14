"""
Teste das ferramentas MCP de gestão de clientes:
buscar_cliente_por_telefone, cadastrar_cliente, atualizar_cliente, vincular_whatsapp
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.models.professional import Professional
from app.models.professional_service import ProfessionalService
from app.models.service import Service
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

    def test_listar_servicos_sem_filtro_identifica_ofertas_iguais_por_profissional(
        self, client: TestClient, db_session: Session
    ):
        entities = seed_data(db_session)
        outro_profissional = Professional(name="Ana Costa", active=True)
        db_session.add(outro_profissional)
        db_session.flush()
        db_session.add(
            ProfessionalService(
                professional_id=outro_profissional.id,
                service_id=entities["service"].id,
            )
        )
        db_session.commit()

        response = _mcp_call(client, "listar_servicos", {})

        text = response.json()["result"]["content"][0]["text"]
        assert text.count("Corte de cabelo") == 2
        assert "Maria Souza" in text
        assert "Ana Costa" in text

    def test_listar_servicos_sem_filtro_nao_repete_duplicata_do_mesmo_profissional(
        self, client: TestClient, db_session: Session
    ):
        entities = seed_data(db_session)
        db_session.add(
            Service(
                name="Corte de cabelo",
                description=entities["service"].description,
                duration_minutes=60,
                price_cents=5000,
                category="corte",
            )
        )
        db_session.commit()

        response = _mcp_call(client, "listar_servicos", {})

        text = response.json()["result"]["content"][0]["text"]
        assert text.count("Corte de cabelo") == 1

    def test_listar_servicos_por_profissional_mantem_ofertas_sem_repetir_nome(
        self, client: TestClient, db_session: Session
    ):
        entities = seed_data(db_session)

        response = _mcp_call(
            client,
            "listar_servicos",
            {"professional_id": entities["professional"].id},
        )

        text = response.json()["result"]["content"][0]["text"]
        assert "Corte de cabelo" in text
        assert "Escova" in text
        assert "Maria Souza" not in text

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
