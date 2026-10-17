"""
Testes unitários para o SalesPromptEngine e evolução do motor de prompts do Orquestrador.
"""

from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.models.company_settings import CompanySettings
from app.models.user import User
from app.services.ai.orchestrator import SalesOrchestrator
from app.services.ai.prompt_engine import SalesArchetype, SalesPromptEngine


def test_resolve_archetype():
    """Valida o mapeamento de strings para arquétipos de vendas."""
    assert SalesPromptEngine.resolve_archetype("consultative") == SalesArchetype.CONSULTATIVE
    assert SalesPromptEngine.resolve_archetype("Consultivo") == SalesArchetype.CONSULTATIVE
    assert SalesPromptEngine.resolve_archetype("closer") == SalesArchetype.CLOSER
    assert SalesPromptEngine.resolve_archetype("Fechador") == SalesArchetype.CLOSER
    assert SalesPromptEngine.resolve_archetype("relational") == SalesArchetype.RELATIONAL
    assert SalesPromptEngine.resolve_archetype("empático") == SalesArchetype.RELATIONAL
    assert SalesPromptEngine.resolve_archetype("executive") == SalesArchetype.EXECUTIVE
    assert SalesPromptEngine.resolve_archetype("executivo") == SalesArchetype.EXECUTIVE
    assert SalesPromptEngine.resolve_archetype("casual") == SalesArchetype.CASUAL
    assert SalesPromptEngine.resolve_archetype("formal") == SalesArchetype.FORMAL

    # Fallbacks seguros para valores desconhecidos ou nulos
    assert SalesPromptEngine.resolve_archetype(None) == SalesArchetype.CASUAL
    assert SalesPromptEngine.resolve_archetype("") == SalesArchetype.CASUAL
    assert SalesPromptEngine.resolve_archetype("inexistente_qualquer") == SalesArchetype.CASUAL


def test_archetype_instructions():
    """Valida que cada arquétipo possui diretrizes distintas e especializadas."""
    for arch in SalesArchetype:
        instructions = SalesPromptEngine.get_archetype_instructions(arch)
        assert len(instructions) > 50
        assert "ESTILO COMERCIAL" in instructions

    # Validações semânticas específicas
    consultative = SalesPromptEngine.get_archetype_instructions(SalesArchetype.CONSULTATIVE)
    assert "diagnosticar antes de prescrever" in consultative

    closer = SalesPromptEngine.get_archetype_instructions(SalesArchetype.CLOSER)
    assert "Fechador Ágil" in closer

    relational = SalesPromptEngine.get_archetype_instructions(SalesArchetype.RELATIONAL)
    assert "confiança, relacionamento duradouro" in relational


def test_sales_playbook_techniques():
    """Valida a presença de técnicas essenciais de conversão no manual de vendas."""
    playbook = SalesPromptEngine.get_sales_playbook()
    # 1. Formatação para WhatsApp
    assert "negrito" in playbook
    assert "parágrafos curtos" in playbook
    assert "CTA" in playbook

    # 2. Fechamento por dupla alternativa
    assert "Dupla Alternativa" in playbook
    assert "Você prefere" in playbook

    # 3. Venda cruzada / Cross-sell
    assert "Cross-Sell" in playbook

    # 4. Matriz de contorno de objeções
    assert "Objeção de Preço" in playbook
    assert "Objeção de Dúvida" in playbook
    assert "Objeção de Frete" in playbook
    assert "Objeção de Confiança" in playbook

    # 5. Transbordo humano
    assert "acionar_atendente_humano" in playbook


def test_build_system_prompt_context_injection():
    """Testa a geração do prompt de sistema injetando dados do lojista, vendedor e cliente."""
    settings = CompanySettings(
        company_name="Ótica Visão Nobre",
        assistant_name="Lara",
        tone="consultative",
        ai_system_prompt="Promoção da semana: armações leves com 15% de desconto no PIX.",
    )
    user = User(
        name="Renata Albuquerque",
        phone="5585999998888",
        custom_fields={
            "seller_name": "Marcos Silva",
            "branch_name": "Unidade Aldeota",
        },
    )

    prompt = SalesPromptEngine.build_system_prompt(settings, user)

    # Identidade
    assert "Você é Lara, o consultor comercial inteligente da loja 'Ótica Visão Nobre'." in prompt
    assert "Renata Albuquerque" in prompt

    # Contexto de Vendedor e Filial
    assert "Marcos Silva" in prompt
    assert "Unidade Aldeota" in prompt

    # Arquétipo Consultivo
    assert "Vendedor Consultivo & Especialista" in prompt

    # Playbook de Vendas e Objeções
    assert "MANUAL DE CONVERSÃO E TÉCNICAS DE VENDAS ATIVAS NO WHATSAPP" in prompt
    assert "Dupla Alternativa" in prompt

    # Instruções específicas da loja
    assert "Promoção da semana: armações leves com 15% de desconto no PIX." in prompt


def test_sales_orchestrator_integration(db_session: Session):
    """Testa a integração transparente entre o SalesOrchestrator e o SalesPromptEngine."""
    user = User(name="Diego Santos", phone="5585911112222")
    db_session.add(user)
    db_session.commit()

    settings = CompanySettings(
        company_name="Hamburgueria Artesanal",
        assistant_name="Chef Burguer",
        tone="closer",
    )

    orchestrator = SalesOrchestrator(
        db=db_session,
        user=user,
        company_settings=settings,
        llm_client=MagicMock(),
    )

    system_prompt = orchestrator._build_system_prompt()

    assert "Chef Burguer" in system_prompt
    assert "Hamburgueria Artesanal" in system_prompt
    assert "Diego Santos" in system_prompt
    assert "Fechador Ágil & Dinâmico" in system_prompt
    assert "MANUAL DE CONVERSÃO" in system_prompt
