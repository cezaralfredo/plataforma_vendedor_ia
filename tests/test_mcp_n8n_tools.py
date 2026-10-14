from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.tools import TOOL_DEFINITIONS, handle_tool_call


def test_n8n_mcp_tool_definitions_present():
    names = {tool["name"]: tool for tool in TOOL_DEFINITIONS}
    
    assert "solicitar_agendamento_orquestrador_n8n" in names
    sched_tool = names["solicitar_agendamento_orquestrador_n8n"]
    assert "client_name" in sched_tool["inputSchema"]["properties"]
    assert "phone" in sched_tool["inputSchema"]["properties"]
    assert "professional_id" in sched_tool["inputSchema"]["properties"]
    assert "service_id" in sched_tool["inputSchema"]["properties"]

    assert "solicitar_cancelamento_n8n" in names
    cancel_tool = names["solicitar_cancelamento_n8n"]
    assert "appointment_id" in cancel_tool["inputSchema"]["properties"]


@pytest.mark.asyncio
async def test_solicitar_agendamento_orquestrador_n8n_success():
    mock_db = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "appointment_id": 99,
        "amount": "R$ 150,00",
        "payment_url": "https://sandbox.asaas.com/i/test",
        "pix_code": "00020126580014br.gov.bcb.pix...",
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await handle_tool_call(
            "solicitar_agendamento_orquestrador_n8n",
            {
                "client_name": "João Silva",
                "phone": "5511999998888",
                "professional_id": 1,
                "service_id": 2,
                "start_time": "2026-09-25T14:00:00",
                "end_time": "2026-09-25T15:00:00",
                "notes": "Teste agendamento n8n",
            },
            mock_db,
        )

        assert "isError" not in result or not result["isError"]
        text = result["content"][0]["text"]
        assert "Agendamento #99 orquestrado com sucesso pelo n8n!" in text
        assert "Link de Pagamento: https://sandbox.asaas.com/i/test" in text


@pytest.mark.asyncio
async def test_solicitar_cancelamento_n8n_success():
    mock_db = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await handle_tool_call(
            "solicitar_cancelamento_n8n",
            {
                "appointment_id": 99,
                "phone": "5511999998888",
            },
            mock_db,
        )

        assert "isError" not in result or not result["isError"]
        text = result["content"][0]["text"]
        assert "Reserva #99 cancelada com sucesso via Subagente de Cancelamento do n8n." in text
