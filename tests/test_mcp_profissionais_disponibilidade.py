"""
Testes dedicados às ferramentas MCP de profissionais e disponibilidade:
- listar_profissionais
- verificar_disponibilidade (com ID e com nome do profissional)
- meus_agendamentos com detalhes de IDs
- solicitar_agendamento_orquestrador_n8n com resolução de nomes
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.models.appointment import Appointment
from tests.seed import seed_data


def _mcp_call(client: TestClient, name: str, arguments: dict):
    return client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {"name": name, "arguments": arguments},
        },
        headers={"Authorization": f"Bearer {settings.api_key}"},
    )


class TestMCPProfissionaisDisponibilidade:

    def test_listar_profissionais_retorna_todos_com_servicos(
        self, client: TestClient, db_session: Session
    ):
        entities = seed_data(db_session)
        resp = _mcp_call(client, "listar_profissionais", {})
        assert resp.status_code == 200
        text = resp.json()["result"]["content"][0]["text"]
        assert "Maria Souza" in text
        assert f"ID #{entities['professional'].id}" in text
        assert "Corte de cabelo" in text

    def test_listar_profissionais_filtro_por_nome(
        self, client: TestClient, db_session: Session
    ):
        seed_data(db_session)
        resp = _mcp_call(client, "listar_profissionais", {"name": "Maria"})
        assert resp.status_code == 200
        text = resp.json()["result"]["content"][0]["text"]
        assert "Maria Souza" in text

        resp2 = _mcp_call(client, "listar_profissionais", {"name": "Inexistente"})
        text2 = resp2.json()["result"]["content"][0]["text"]
        assert "Nenhum profissional encontrado" in text2

    def test_verificar_disponibilidade_por_id_e_por_nome(
        self, client: TestClient, db_session: Session
    ):
        entities = seed_data(db_session)
        prof_id = entities["professional"].id

        # Por ID numérico (2026-07-30 está no seed com specific_date)
        resp_id = _mcp_call(
            client,
            "verificar_disponibilidade",
            {"professional_id": prof_id, "date": "2026-07-30"},
        )
        assert resp_id.status_code == 200
        text_id = resp_id.json()["result"]["content"][0]["text"]
        assert "09:00" in text_id
        assert "Maria Souza" in text_id

        # Por nome do profissional
        resp_name = _mcp_call(
            client,
            "verificar_disponibilidade",
            {"professional_name": "Maria Souza", "date": "2026-07-30"},
        )
        assert resp_name.status_code == 200
        text_name = resp_name.json()["result"]["content"][0]["text"]
        assert "09:00" in text_name
        assert "Maria Souza" in text_name

        # Passando nome dentro do campo professional_id (resiliência LLM)
        resp_resilient = _mcp_call(
            client,
            "verificar_disponibilidade",
            {"professional_id": "Maria Souza", "date": "2026-07-30"},
        )
        assert resp_resilient.status_code == 200
        text_resilient = resp_resilient.json()["result"]["content"][0]["text"]
        assert "09:00" in text_resilient

    def test_meus_agendamentos_inclui_ids_de_servico_e_profissional(
        self, client: TestClient, db_session: Session
    ):
        entities = seed_data(db_session)
        user = entities["user"]
        prof = entities["professional"]
        serv = entities["service"]

        from datetime import datetime

        from app.models.payment import Payment

        appt = Appointment(
            user_id=user.id,
            professional_id=prof.id,
            service_id=serv.id,
            start_time=datetime(2026, 9, 23, 13, 0),
            end_time=datetime(2026, 9, 23, 13, 45),
            status="cancelled",
        )
        db_session.add(appt)
        db_session.flush()

        payment = Payment(
            appointment_id=appt.id,
            amount_cents=5000,
            status="confirmed",
        )
        db_session.add(payment)
        db_session.commit()

        resp = _mcp_call(client, "meus_agendamentos", {"phone": user.phone})
        assert resp.status_code == 200
        text = resp.json()["result"]["content"][0]["text"]
        assert f"Serviço #{serv.id}" in text
        assert f"Profissional #{prof.id}" in text
        assert "Cancelado" in text
        assert "Pagamento: Confirmado" in text

    def test_meus_agendamentos_oculta_cancelados_nao_pagos(
        self, client: TestClient, db_session: Session
    ):
        entities = seed_data(db_session)
        user = entities["user"]
        prof = entities["professional"]
        serv = entities["service"]

        from datetime import datetime
        appt = Appointment(
            user_id=user.id,
            professional_id=prof.id,
            service_id=serv.id,
            start_time=datetime(2026, 9, 23, 15, 0),
            end_time=datetime(2026, 9, 23, 15, 45),
            status="cancelled",
        )
        db_session.add(appt)
        db_session.commit()

        # Por padrão, reserva cancelada sem pagamento NÃO deve aparecer no histórico
        resp = _mcp_call(client, "meus_agendamentos", {"phone": user.phone})
        assert resp.status_code == 200
        text = resp.json()["result"]["content"][0]["text"]
        assert "Nenhum agendamento encontrado" in text

        # Se explicitamente solicitado com include_unpaid_cancelled=True, aparece
        resp_incl = _mcp_call(
            client,
            "meus_agendamentos",
            {"phone": user.phone, "include_unpaid_cancelled": True},
        )
        assert resp_incl.status_code == 200
        text_incl = resp_incl.json()["result"]["content"][0]["text"]
        assert f"Serviço #{serv.id}" in text_incl
        assert "Cancelado" in text_incl
