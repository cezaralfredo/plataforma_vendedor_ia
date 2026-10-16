import json
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.company_settings import CompanySettings
from app.models.payment import Payment
from app.models.product import Product
from app.models.user import User
from app.services.ai.orchestrator import SalesOrchestrator
from app.services.ai.providers.anthropic_client import AnthropicClient
from app.services.ai.providers.base import (
    BaseLLMClient,
    LLMMessage,
    LLMResponse,
    ToolCall,
)
from app.services.ai.providers.factory import get_llm_client
from app.services.ai.providers.openai_client import OpenAICompatibleClient
from app.services.ai.subagents.catalog_subagent import CatalogSubagent
from app.services.ai.subagents.checkout_subagent import CheckoutSubagent
from app.services.ai.subagents.order_status_subagent import OrderStatusSubagent
from app.services.ai.subagents.support_subagent import SupportSubagent


def test_llm_factory_selection():
    """Testa a factory retornando a classe e modelo corretos para cada provedor configurado."""
    # OpenAI
    settings_openai = CompanySettings(
        ai_provider="openai",
        ai_model="gpt-4o",
        ai_api_key="sk-test-openai",
    )
    client_openai = get_llm_client(settings_openai)
    assert isinstance(client_openai, OpenAICompatibleClient)
    assert client_openai.model == "gpt-4o"
    assert "api.openai.com" in client_openai.endpoint_url

    # Anthropic
    settings_anthropic = CompanySettings(
        ai_provider="anthropic",
        ai_model="claude-3-5-sonnet-20241022",
        ai_api_key="sk-ant-test",
    )
    client_anthropic = get_llm_client(settings_anthropic)
    assert isinstance(client_anthropic, AnthropicClient)
    assert client_anthropic.model == "claude-3-5-sonnet-20241022"
    assert "api.anthropic.com" in client_anthropic.endpoint_url

    # Gemini
    settings_gemini = CompanySettings(
        ai_provider="gemini",
        ai_model="gemini-1.5-flash",
        ai_api_key="AIzaSyTest",
    )
    client_gemini = get_llm_client(settings_gemini)
    assert isinstance(client_gemini, OpenAICompatibleClient)
    assert "generativelanguage.googleapis.com" in client_gemini.endpoint_url

    # Groq
    settings_groq = CompanySettings(
        ai_provider="groq",
        ai_model="llama-3.3-70b-versatile",
        ai_api_key="gsk-test",
    )
    client_groq = get_llm_client(settings_groq)
    assert isinstance(client_groq, OpenAICompatibleClient)
    assert "api.groq.com" in client_groq.endpoint_url

    # Custom / Ollama
    settings_custom = CompanySettings(
        ai_provider="custom",
        ai_base_url="http://localhost:11434/v1",
        ai_model="llama3.2",
    )
    client_custom = get_llm_client(settings_custom)
    assert isinstance(client_custom, OpenAICompatibleClient)
    assert "localhost:11434" in client_custom.endpoint_url

    # Sem API Key para OpenAI -> Deve retornar None para acionar fallback
    settings_empty = CompanySettings(ai_provider="openai", ai_api_key="")
    assert get_llm_client(settings_empty) is None


def test_anthropic_message_conversion():
    """Testa se a conversão para a API Anthropic Claude extrai o system prompt e formata tools."""
    client = AnthropicClient(api_key="test-key", model="claude-3-5-haiku-20241022")
    messages = [
        LLMMessage(role="system", content="Você é um vendedor."),
        LLMMessage(role="user", content="Quero comprar."),
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[ToolCall(id="call_123", name="consultar_catalogo", arguments={})],
        ),
        LLMMessage(role="tool", content='{"produtos": []}', tool_call_id="call_123"),
    ]

    system_prompt, formatted = client._convert_messages(messages)
    assert system_prompt == "Você é um vendedor."
    assert len(formatted) == 3
    assert formatted[0]["role"] == "user"
    assert formatted[1]["role"] == "assistant"
    assert formatted[1]["content"][0]["type"] == "tool_use"
    assert formatted[2]["role"] == "user"
    assert formatted[2]["content"][0]["type"] == "tool_result"


@pytest.mark.asyncio
async def test_catalog_subagent(db_session: Session):
    """Testa a execução de ferramentas no CatalogSubagent."""
    prod = Product(
        name="Camiseta DryFit Pro",
        price_cents=7990,
        weight_kg=Decimal("0.250"),
        stock_quantity=15,
        active=True,
    )
    db_session.add(prod)
    db_session.commit()

    agent = CatalogSubagent(db_session)
    tools = agent.get_tools()
    assert len(tools) == 2
    tool_names = [t.name for t in tools]
    assert "consultar_catalogo" in tool_names
    assert "obter_detalhes_produto" in tool_names

    # Consulta catálogo
    res = await agent.execute_tool("consultar_catalogo", {"termo_busca": "DryFit"})
    data = json.loads(res)
    assert data["status"] == "sucesso"
    assert data["total"] == 1
    assert data["produtos"][0]["id"] == prod.id
    assert data["produtos"][0]["peso_kg"] == 0.250
    assert data["produtos"][0]["preco_reais"] == "R$ 79.90"

    # Detalhes do produto
    res_det = await agent.execute_tool("obter_detalhes_produto", {"produto_id": prod.id})
    data_det = json.loads(res_det)
    assert data_det["status"] == "sucesso"
    assert data_det["produto"]["nome"] == "Camiseta DryFit Pro"


@pytest.mark.asyncio
async def test_checkout_subagent(db_session: Session):
    """Testa a execução da ferramenta de checkout e cobrança direta no Asaas."""
    user = User(name="Carlos Lima", phone="5585988887777")
    db_session.add(user)
    prod = Product(
        name="Tênis Corrida Leve",
        price_cents=29990,
        weight_kg=Decimal("0.850"),
        stock_quantity=5,
        active=True,
    )
    db_session.add(prod)
    db_session.commit()

    agent = CheckoutSubagent(db_session, user)

    with patch.object(agent.payment_service.asaas, "create_payment", new_callable=AsyncMock) as mock_asaas, \
         patch.object(agent.payment_service.asaas, "list_customers", new_callable=AsyncMock) as mock_cust, \
         patch.object(agent.payment_service.asaas, "create_customer", new_callable=AsyncMock) as _mock_create_cust:

        mock_cust.return_value = [{"id": "cus_999", "mobilePhone": user.phone}]
        mock_asaas.return_value = {
            "id": "pay_555",
            "status": "PENDING",
            "invoiceUrl": "https://sandbox.asaas.com/i/tenis555",
            "value": 299.90,
        }

        res = await agent.execute_tool("criar_pedido_cobranca", {"produto_id": prod.id, "quantidade": 2})
        data = json.loads(res)

        assert data["status"] == "sucesso"
        assert data["produto_id"] == prod.id
        assert data["quantidade"] == 2
        assert data["valor_total_formatado"] == "R$ 599.80"
        assert data["peso_total_kg"] == 1.700
        assert data["link_pagamento"] == "https://sandbox.asaas.com/i/tenis555"


@pytest.mark.asyncio
async def test_order_status_and_support_subagents(db_session: Session):
    """Testa subagentes de status de pedido e transbordo humano."""
    user = User(name="Marina", phone="5585977776666")
    db_session.add(user)
    db_session.commit()

    payment = Payment(
        user_id=user.id,
        amount_cents=15000,
        billing_type="pix",
        status="received",
        description="Pedido: Perfume Floral",
        invoice_url="https://asaas.com/i/p123",
    )
    db_session.add(payment)
    db_session.commit()

    order_agent = OrderStatusSubagent(db_session, user)
    res_orders = await order_agent.execute_tool("consultar_status_pedido", {})
    data_orders = json.loads(res_orders)
    assert data_orders["status"] == "sucesso"
    assert len(data_orders["pedidos"]) == 1
    assert "Confirmado" in data_orders["pedidos"][0]["status_legivel"]

    settings = CompanySettings(company_name="Perfumaria Elegance")
    support_agent = SupportSubagent(settings)
    res_sup = await support_agent.execute_tool("acionar_atendente_humano", {"motivo": "Dúvida sobre entrega"})
    data_sup = json.loads(res_sup)
    assert data_sup["status"] == "sucesso"
    assert "wa.me" in data_sup["link_suporte"]


@pytest.mark.asyncio
async def test_sales_orchestrator_full_tool_loop(db_session: Session):
    """Testa o ciclo de tool calling do orquestrador com mock de LLM emitindo chamada de ferramenta."""
    user = User(name="Roberto Vendas", phone="5585966665555")
    prod = Product(name="Mochila Executiva", price_cents=19900, weight_kg=Decimal("0.900"), stock_quantity=10, active=True)
    db_session.add(user)
    db_session.add(prod)
    db_session.commit()

    settings = CompanySettings(
        company_name="Loja Executiva",
        ai_provider="openai",
        ai_model="gpt-4o-mini",
        ai_api_key="sk-test",
    )

    # Cria cliente mock que primeiro pede para chamar 'criar_pedido_cobranca' e depois responde com o texto final
    mock_llm = AsyncMock(spec=BaseLLMClient)
    step1_response = LLMResponse(
        content=None,
        tool_calls=[
            ToolCall(
                id="call_mock_1",
                name="criar_pedido_cobranca",
                arguments={"produto_id": prod.id, "quantidade": 1},
            )
        ],
    )
    step2_response = LLMResponse(
        content="Perfeito Roberto! Seu pedido da Mochila Executiva foi gerado. Segue o link do PIX: https://sandbox.asaas.com/i/mochila123",
        tool_calls=[],
    )
    mock_llm.generate_response.side_effect = [step1_response, step2_response]

    orchestrator = SalesOrchestrator(
        db=db_session,
        user=user,
        company_settings=settings,
        llm_client=mock_llm,
    )

    with patch.object(orchestrator.checkout_subagent.payment_service.asaas, "create_payment", new_callable=AsyncMock) as mock_asaas, \
         patch.object(orchestrator.checkout_subagent.payment_service.asaas, "list_customers", new_callable=AsyncMock) as mock_cust, \
         patch.object(orchestrator.checkout_subagent.payment_service.asaas, "create_customer", new_callable=AsyncMock) as _mock_create_cust:

        mock_cust.return_value = [{"id": "cus_roberto"}]
        mock_asaas.return_value = {
            "id": "pay_mochila",
            "status": "PENDING",
            "invoiceUrl": "https://sandbox.asaas.com/i/mochila123",
            "value": 199.00,
        }

        result = await orchestrator.process_message("Quero comprar a mochila agora", history=[])

        assert "Mochila Executiva" in result
        assert "https://sandbox.asaas.com/i/mochila123" in result
        assert mock_llm.generate_response.call_count == 2


@pytest.mark.asyncio
async def test_sales_orchestrator_deterministic_fallback(db_session: Session):
    """Testa que se o LLM falhar ou não tiver API key, o fallback determinístico responde de forma confiável."""
    user = User(name="Ana Clara", phone="5585955554444")
    prod = Product(name="Batom Matte Vermelho", price_cents=3500, weight_kg=Decimal("0.050"), stock_quantity=30, active=True)
    db_session.add(user)
    db_session.add(prod)
    db_session.commit()

    settings = CompanySettings(
        company_name="Cosméticos VIP",
        ai_provider="openai",
        ai_api_key="",  # Sem chave -> Força fallback
    )

    orchestrator = SalesOrchestrator(
        db=db_session,
        user=user,
        company_settings=settings,
        llm_client=None,
    )

    # 1. Catálogo
    res_cat = await orchestrator.process_message("quais produtos vocês têm?", history=[])
    assert "Catálogo de Produtos" in res_cat
    assert "Batom Matte Vermelho" in res_cat
    assert "0.050 kg" in res_cat

    # 2. Transbordo Humano
    res_humano = await orchestrator.process_message("quero falar com um atendente humano", history=[])
    assert "notifiquei nossa equipe" in res_humano
    assert "wa.me" in res_humano
