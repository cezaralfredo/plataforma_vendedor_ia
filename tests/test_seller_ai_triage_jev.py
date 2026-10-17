"""
Testes unitários da integração da Triagem TypeSafe Jev no SellerAIService.
Garante o roteamento rápido (fast-paths) com economia de 100% de tokens de LLM
para saudações, confirmações de pagamento e transbordo humano.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.company_settings import CompanySettings
from app.models.payment import Payment
from app.models.user import User
from app.schemas.triage import TriageResult
from app.services.seller_ai_service import SellerAIService
from app.services.whatsapp.base import InboundMessage


@pytest.mark.asyncio
async def test_seller_ai_fast_handoff_human_via_jev(db_session: Session):
    """Testa transbordo humano imediato via Jev sem acionar o LLM."""
    user = User(name="Rodrigo", phone="5585988881111")
    db_session.add(user)
    db_session.commit()

    service = SellerAIService(db_session)
    inbound = InboundMessage(
        provider="evolution",
        sender_phone=user.phone,
        sender_name="Rodrigo",
        text="Quero falar com uma pessoa agora por favor",
        message_id="msg-jev-1",
    )

    mock_triage = TriageResult(
        intent="falar_humano",
        intent_confidence=0.95,
        is_human_handoff=0.98,
        is_payment_claim=0.0,
        frustration_score=0.8,
        frustration_level="impaciente",
        recommended_action="fast_handoff_human",
        fast_response_text=None,
        model_used="typesafe/jev-1.13",
        cost_usd=0.0001,
        is_fallback=False,
    )

    with patch.object(service.triage_service, "evaluate", new_callable=AsyncMock) as mock_eval, \
         patch.object(service.gateway, "send_text", new_callable=AsyncMock) as mock_send, \
         patch("app.services.seller_ai_service.SalesOrchestrator") as mock_orchestrator:

        mock_eval.return_value = mock_triage

        response = await service.handle_inbound_message(inbound)

        # Deve responder imediatamente com atendimento humano e link de suporte
        assert "notifiquei nossa equipe" in response.lower() or "atendimento humano" in response.lower()
        mock_send.assert_called_once()
        # O SalesOrchestrator (LLM caro) NÃO deve ser instanciado nem chamado (0 tokens)!
        mock_orchestrator.assert_not_called()

    # Verifica se a IA foi pausada no cadastro do usuário
    db_session.refresh(user)
    assert user.custom_fields.get("ai_paused_until") is not None


@pytest.mark.asyncio
async def test_seller_ai_fast_check_pix_confirmed_via_jev(db_session: Session):
    """Testa confirmação direta de PIX já recebido via Jev com 0 tokens de LLM."""
    user = User(name="Camila Silva", phone="5585988882222")
    db_session.add(user)
    db_session.commit()

    payment = Payment(
        user_id=user.id,
        amount_cents=15000,
        billing_type="pix",
        status="received",
        description="Pedido de cosméticos",
    )
    db_session.add(payment)
    db_session.commit()

    service = SellerAIService(db_session)
    inbound = InboundMessage(
        provider="waha",
        sender_phone=user.phone,
        sender_name="Camila",
        text="Acabei de fazer o PIX aqui",
        message_id="msg-jev-2",
    )

    mock_triage = TriageResult(
        intent="confirmar_pix",
        intent_confidence=0.92,
        is_human_handoff=0.0,
        is_payment_claim=0.96,
        frustration_score=0.1,
        frustration_level="calmo",
        recommended_action="fast_check_pix",
        fast_response_text=None,
        model_used="typesafe/jev-1.13",
        cost_usd=0.0001,
        is_fallback=False,
    )

    with patch.object(service.triage_service, "evaluate", new_callable=AsyncMock) as mock_eval, \
         patch.object(service.gateway, "send_text", new_callable=AsyncMock) as mock_send, \
         patch("app.services.seller_ai_service.SalesOrchestrator") as mock_orchestrator:

        mock_eval.return_value = mock_triage

        response = await service.handle_inbound_message(inbound)

        assert "confirmado com sucesso" in response
        assert "R$ 150.00" in response
        assert f"Pedido #{payment.id}" in response
        mock_send.assert_called_once()
        mock_orchestrator.assert_not_called()


@pytest.mark.asyncio
async def test_seller_ai_fast_check_pix_pending_via_jev(db_session: Session):
    """Testa aviso de PIX ainda pendente de liquidação via Jev com 0 tokens de LLM."""
    user = User(name="Lucas Ferreira", phone="5585988883333")
    db_session.add(user)
    db_session.commit()

    payment = Payment(
        user_id=user.id,
        amount_cents=8990,
        billing_type="pix",
        status="pending",
        description="Pedido tênis",
        invoice_url="https://asaas.com/i/pix-lucas",
    )
    db_session.add(payment)
    db_session.commit()

    service = SellerAIService(db_session)
    inbound = InboundMessage(
        provider="meta",
        sender_phone=user.phone,
        sender_name="Lucas",
        text="Mandei o pagamento do pix",
        message_id="msg-jev-3",
    )

    mock_triage = TriageResult(
        intent="confirmar_pix",
        intent_confidence=0.90,
        is_human_handoff=0.0,
        is_payment_claim=0.94,
        frustration_score=0.2,
        frustration_level="calmo",
        recommended_action="fast_check_pix",
        fast_response_text=None,
        model_used="typesafe/jev-1.13",
        cost_usd=0.0001,
        is_fallback=False,
    )

    with patch.object(service.triage_service, "evaluate", new_callable=AsyncMock) as mock_eval, \
         patch.object(service.gateway, "send_text", new_callable=AsyncMock) as mock_send, \
         patch("app.services.seller_ai_service.SalesOrchestrator") as mock_orchestrator:

        mock_eval.return_value = mock_triage

        response = await service.handle_inbound_message(inbound)

        assert "acompanhando seu pagamento" in response
        assert "R$ 89.90" in response
        assert "https://asaas.com/i/pix-lucas" in response
        mock_send.assert_called_once()
        mock_orchestrator.assert_not_called()


@pytest.mark.asyncio
async def test_seller_ai_fast_greeting_initial_message_via_jev(db_session: Session):
    """Testa saudação rápida inicial via Jev com mensagem da loja e 0 tokens de LLM."""
    settings = db_session.query(CompanySettings).first()
    if not settings:
        settings = CompanySettings(company_name="Barbearia Imperial", welcome_message="Bem-vindo à Barbearia Imperial! ✂️")
        db_session.add(settings)
    else:
        settings.company_name = "Barbearia Imperial"
        settings.welcome_message = "Bem-vindo à Barbearia Imperial! ✂️"
    db_session.commit()

    user = User(name="Gabriel", phone="5585988884444")
    db_session.add(user)
    db_session.commit()

    service = SellerAIService(db_session)
    inbound = InboundMessage(
        provider="waha",
        sender_phone=user.phone,
        sender_name="Gabriel",
        text="Olá bom dia",
        message_id="msg-jev-4",
    )

    mock_triage = TriageResult(
        intent="saudacao",
        intent_confidence=0.98,
        is_human_handoff=0.0,
        is_payment_claim=0.0,
        frustration_score=0.0,
        frustration_level="calmo",
        recommended_action="fast_greeting",
        fast_response_text="Olá! Seja muito bem-vindo.",
        model_used="typesafe/jev-1.13",
        cost_usd=0.0001,
        is_fallback=False,
    )

    with patch.object(service.triage_service, "evaluate", new_callable=AsyncMock) as mock_eval, \
         patch.object(service.gateway, "send_text", new_callable=AsyncMock) as mock_send, \
         patch("app.services.seller_ai_service.SalesOrchestrator") as mock_orchestrator:

        mock_eval.return_value = mock_triage

        response = await service.handle_inbound_message(inbound)

        assert "Bem-vindo à Barbearia Imperial! ✂️" in response
        mock_send.assert_called_once()
        mock_orchestrator.assert_not_called()
