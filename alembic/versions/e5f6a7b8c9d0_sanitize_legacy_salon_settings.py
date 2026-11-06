"""Sanitize legacy salon references from company_settings.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if "company_settings" in existing_tables:
        clean_welcome = (
            "Olá! Seja muito bem-vindo(a) à nossa loja! ✨\n\n"
            "Sou sua consultora virtual de vendas. Como posso te ajudar hoje?\n"
            "• Conhecer nossos Produtos e Catálogo\n"
            "• Fazer um Pedido e Consultar Preços\n"
            "• Informações sobre Entrega e Formas de Pagamento"
        )
        clean_prompt = (
            "Atendimento consultivo e focado exclusivamente no catálogo de produtos, "
            "pedidos de compras, entregas e opções de pagamento (PIX ou entrega). "
            "Não oferecemos agendamento de serviços de salão ou barbearia."
        )

        # Atualiza welcome_message se contiver termos legados de salão/barbearia
        bind.execute(
            sa.text(
                """
                UPDATE company_settings
                SET welcome_message = :clean_welcome
                WHERE welcome_message ILIKE '%cabelo%'
                   OR welcome_message ILIKE '%unha%'
                   OR welcome_message ILIKE '%estética%'
                   OR welcome_message ILIKE '%estetica%'
                   OR welcome_message ILIKE '%agendamento de servi%'
                   OR welcome_message ILIKE '%produtos profissionais%'
                   OR welcome_message ILIKE '%horários e preços%'
                   OR welcome_message ILIKE '%barbearia%'
                   OR welcome_message ILIKE '%barbeiro%'
                """
            ),
            {"clean_welcome": clean_welcome},
        )

        # Atualiza ai_system_prompt se contiver termos legados de salão/barbearia
        bind.execute(
            sa.text(
                """
                UPDATE company_settings
                SET ai_system_prompt = :clean_prompt
                WHERE ai_system_prompt ILIKE '%cabelo%'
                   OR ai_system_prompt ILIKE '%unha%'
                   OR ai_system_prompt ILIKE '%estética%'
                   OR ai_system_prompt ILIKE '%estetica%'
                   OR ai_system_prompt ILIKE '%agendamento de servi%'
                   OR ai_system_prompt ILIKE '%produtos profissionais%'
                   OR ai_system_prompt ILIKE '%barbearia%'
                   OR ai_system_prompt ILIKE '%barbeiro%'
                """
            ),
            {"clean_prompt": clean_prompt},
        )

        # Corrige assistant_name caso mencione barbeiro ou cabeleireiro
        bind.execute(
            sa.text(
                """
                UPDATE company_settings
                SET assistant_name = 'Consultor de Vendas'
                WHERE assistant_name ILIKE '%barbeir%'
                   OR assistant_name ILIKE '%cabeleireir%'
                """
            )
        )


def downgrade() -> None:
    pass
