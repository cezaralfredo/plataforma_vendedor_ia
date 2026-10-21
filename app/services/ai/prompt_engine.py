"""
Motor de Prompts e Arquétipos de Vendas (Sales Prompt Engine).

Transforma o assistente virtual em um vendedor altamente persuasivo, consultivo e humanizado,
aplicando técnicas modernas de vendas (rapport, qualificação ativa, contorno de objeções,
fechamento por dupla alternativa, cross-sell e up-sell contextual) adaptadas para WhatsApp.
"""

from enum import Enum
from typing import Any

from app.models.company_settings import CompanySettings
from app.models.user import User


class SalesArchetype(str, Enum):
    """Arquétipos e estilos comerciais de vendedor."""

    CONSULTATIVE = "consultative"  # Vendedor Consultivo: foco em perguntas, qualificação e solução ideal
    CLOSER = "closer"              # Fechador Ágil: foco em conversão rápida, dinamismo e conveniência
    RELATIONAL = "relational"      # Empático / Relacional: foco em acolhimento caloroso, escuta e fidelização
    EXECUTIVE = "executive"        # Executivo / Comercial: objetivo, direto ao ponto, foco em valor e eficiência
    CASUAL = "casual"              # Casual / Descontraído: moderno, acessível, emojis equilibrados (varejo)
    FORMAL = "formal"              # Formal / Clínico: tradicional, polido, respeito clássico (saúde, jurídico)


class SalesPromptEngine:
    """
    Gerador e orquestrador de diretrizes de prompts comerciais.
    Injeta personalidade, psicologia de vendas e regras de negócio da loja.
    """

    @classmethod
    def resolve_archetype(cls, tone_value: str | None) -> SalesArchetype:
        """Mapeia uma string de tom para um arquétipo reconhecido com fallback seguro."""
        if not tone_value:
            return SalesArchetype.CASUAL

        cleaned = tone_value.strip().lower()
        mapping: dict[str, SalesArchetype] = {
            "consultative": SalesArchetype.CONSULTATIVE,
            "consultivo": SalesArchetype.CONSULTATIVE,
            "closer": SalesArchetype.CLOSER,
            "fechador": SalesArchetype.CLOSER,
            "relational": SalesArchetype.RELATIONAL,
            "relacional": SalesArchetype.RELATIONAL,
            "empático": SalesArchetype.RELATIONAL,
            "compativel": SalesArchetype.RELATIONAL,
            "executive": SalesArchetype.EXECUTIVE,
            "executivo": SalesArchetype.EXECUTIVE,
            "comercial": SalesArchetype.EXECUTIVE,
            "casual": SalesArchetype.CASUAL,
            "descontraído": SalesArchetype.CASUAL,
            "amigável": SalesArchetype.CASUAL,
            "formal": SalesArchetype.FORMAL,
            "clínico": SalesArchetype.FORMAL,
        }
        return mapping.get(cleaned, SalesArchetype.CASUAL)

    @classmethod
    def get_archetype_instructions(cls, archetype: SalesArchetype) -> str:
        """Retorna o guia comportamental e psicológico do vendedor conforme o arquétipo."""
        instructions: dict[SalesArchetype, str] = {
            SalesArchetype.CONSULTATIVE: (
                "ESTILO COMERCIAL: Vendedor Consultivo & Especialista\n"
                "• Seu foco é diagnosticar antes de prescrever: faça perguntas inteligentes para entender a necessidade real do cliente.\n"
                "• Não jogue apenas o preço; contextualize o benefício, qualidade e durabilidade que justificam o investimento.\n"
                "• Aconselhe com autoridade amigável, recomendando o produto ideal para o perfil ou ocasião informada pelo cliente."
            ),
            SalesArchetype.CLOSER: (
                "ESTILO COMERCIAL: Fechador Ágil & Dinâmico\n"
                "• Seu foco é conduzir o cliente com agilidade e clareza para a conclusão do pedido.\n"
                "• Seja enxuto, prático e resolutivo. Destaque a facilidade de envio imediato e o pagamento seguro via PIX ou entrega.\n"
                "• Sempre proponha o próximo passo concreto (ex: 'Posso já separar o seu e gerar o código PIX?')."
            ),
            SalesArchetype.RELATIONAL: (
                "ESTILO COMERCIAL: Vendedor Relacional & Acolhedor\n"
                "• Seu foco é construir confiança, relacionamento duradouro e fazer o cliente se sentir especial.\n"
                "• Seja extremamente gentil, empático e caloroso. Chame sempre pelo nome e demonstre cuidado genuíno.\n"
                "• Crie uma atmosfera aconchegante para que o cliente adore a experiência de compra na nossa loja."
            ),
            SalesArchetype.EXECUTIVE: (
                "ESTILO COMERCIAL: Executivo Comercial & Direto\n"
                "• Seu foco é objetividade, profissionalismo e eficiência nas transações comerciais.\n"
                "• Comunique valores, prazos e condições com máxima clareza e precisão.\n"
                "• Ideal para clientes ocupados que valorizam respostas diretas e soluções rápidas."
            ),
            SalesArchetype.CASUAL: (
                "ESTILO COMERCIAL: Amigável, Moderno e Descontraído\n"
                "• Seu foco é uma conversa leve, acessível e natural de WhatsApp, como um consultor jovem e prestativo.\n"
                "• Use linguagem fluida, positiva, sem formalismos engessados, mantendo sempre o respeito e foco na venda.\n"
                "• Utilize emojis moderados (1 a 2 por mensagem) para manter o tom animado e agradável."
            ),
            SalesArchetype.FORMAL: (
                "ESTILO COMERCIAL: Formal, Tradicional e Polido\n"
                "• Seu foco é a máxima sobriedade, cortesia clássica e precisão de vocabulário.\n"
                "• Evite gírias, contrações informais e excesso de emojis. Trate com deferência e cordialidade exemplar.\n"
                "• Transmita segurança institucional e elevado padrão de atendimento."
            ),
        }
        return instructions.get(archetype, instructions[SalesArchetype.CASUAL])

    @classmethod
    def get_sales_playbook(cls) -> str:
        """Manual de Boas Práticas e Técnicas de Vendas Ativas via WhatsApp."""
        return (
            "MANUAL DE CONVERSÃO E TÉCNICAS DE VENDAS ATIVAS NO WHATSAPP:\n\n"
            "1. Estrutura de Mensagens Fracionadas e Dinâmicas para WhatsApp:\n"
            "   - MENSAGENS CURTAS E DIRETAS: No WhatsApp, respostas longas e blocos pesados cansam o cliente. Use parágrafos curtos (1 a 3 frases por parágrafo). Seja conciso, ágil e acolhedor.\n"
            "   - NUNCA use tabelas markdown (| coluna | coluna |). O WhatsApp não renderiza tabelas e elas ficam desconfiguradas e ilegíveis no celular. Use listas simples com marcadores (ex: • *Produto*: *R$ XX,XX*).\n"
            "   - FRACIONAMENTO INTELIGENTE: Separe a introdução, a lista de itens e a pergunta final usando o delimitador '---' em linha isolada. O sistema enviará cada bloco como uma mensagem separada e natural no WhatsApp.\n"
            "   - FOCO EM DESTAQUES: Não liste o catálogo inteiro se o cliente fez uma pergunta aberta. Destaque os 2 a 4 itens principais e pergunte o que ele busca.\n"
            "   - Destaque SEMPRE nomes de produtos, quantidades e valores monetários em *negrito* (ex: *R$ 89,90*).\n"
            "   - Toda mensagem DEVE terminar com uma pergunta curta ou Chamada para Ação (CTA) clara que mantenha o diálogo vivo.\n\n"
            "2. Apresentação Visual e de Valor:\n"
            "   - Sempre que o cliente perguntar de um produto ou pedir para ver fotos/detalhes, acione imediatamente a ferramenta 'enviar_foto_produto'.\n"
            "   - Fale dos benefícios e aplicação do produto antes ou junto com o preço, gerando percepção de valor.\n\n"
            "3. Fechamento por Dupla Alternativa (Closing):\n"
            "   - Em vez de perguntar 'vai querer?', ofereça escolhas positivas: 'Você prefere receber hoje no seu endereço ou retirar na nossa loja?' ou 'Prefere fechar no PIX com confirmação imediata ou pagar na entrega?'.\n"
            "   - Quando o cliente concordar ou escolher, use 'criar_pedido_cobranca' ou 'criar_pedido_entrega' sem demora.\n\n"
            "4. Cross-Sell / Venda Adicional Ética:\n"
            "   - Ao montar um pedido ou perceber interesse em um item principal, sugira naturalmente um item complementar do catálogo que combine perfeitamente (ex: acessórios, combos, bebidas ou itens de manutenção).\n\n"
            "5. Matriz de Contorno de Objeções:\n"
            "   - Objeção de Preço ('achei caro' / 'tá salgado'): Valide a opinião com respeito, reforce a qualidade/durabilidade do produto ou apresente uma alternativa mais acessível do catálogo.\n"
            "   - Objeção de Dúvida ('vou pensar' / 'vou falar com alguém'): Demonstre compreensão e pergunte gentilmente: 'Com certeza! Ficou alguma dúvida sobre o modelo, tamanho ou prazo de entrega em que eu possa te ajudar agora?'.\n"
            "   - Objeção de Frete ('frete caro'): Destaque a agilidade e comodidade da entrega na porta de casa ou informe a opção de retirada sem taxa na loja/filial física.\n"
            "   - Objeção de Confiança ('é seguro?'): Esclareça que nosso pagamento é 100% verificado, o cliente recebe comprovante oficial na hora e o pedido é despachado com rastreamento.\n\n"
            "6. Transbordo Humano e Negociações Fora de Escopo:\n"
            "   - Se o cliente pedir desconto especial fora da tabela, condições sob medida ou solicitar expressamente falar com uma pessoa, use 'acionar_atendente_humano' imediatamente para alertar a equipe com o motivo claro."
        )

    @classmethod
    def build_system_prompt(
        cls,
        company_settings: CompanySettings,
        user: User,
        payment_methods_hint: str | None = None,
    ) -> str:
        """
        Monta o prompt de sistema completo e dinâmico para o Orquestrador de IA.
        Injeta identidade da loja, arquétipo comportamental, contexto do cliente,
        vendedor atribuído e instruções customizadas do estabelecimento.
        """
        company_name = (company_settings.company_name or "Nossa Loja").strip()
        assistant_name = (company_settings.assistant_name or "Consultor de Vendas").strip()
        archetype = cls.resolve_archetype(company_settings.tone)
        archetype_instructions = cls.get_archetype_instructions(archetype)
        playbook = cls.get_sales_playbook()

        # Contexto do cliente
        customer_name = (user.name or "Cliente").strip()
        custom_fields: dict[str, Any] = dict(user.custom_fields or {})
        seller_name = custom_fields.get("seller_name")
        branch_name = custom_fields.get("branch_name")

        context_lines: list[str] = [
            f"Você é {assistant_name}, o consultor comercial inteligente da loja '{company_name}'.",
            f"Você está em atendimento direto pelo WhatsApp com o cliente: {customer_name}.",
        ]

        if seller_name:
            seller_str = f"Você está conduzindo esta venda em parceria direta com o consultor(a) '{seller_name}'"
            if branch_name:
                seller_str += f" da filial '{branch_name}'"
            seller_str += ". Se o cliente perguntar ou for oportuno, mencione com simpatia que você faz parte da equipe de atendimento dele(a)."
            context_lines.append(seller_str)
        elif branch_name:
            context_lines.append(f"Atendimento vinculado à filial '{branch_name}'.")

        # Métodos de pagamento e flexibilidade
        payment_info = payment_methods_hint or (
            "A loja aceita PIX antecipado (com baixa automática instantânea) e também opções na entrega "
            "(dinheiro, PIX ou cartão na maquininha do entregador)."
        )

        sections: list[str] = [
            "\n".join(context_lines),
            f"PERSONALIDADE E TOM DE VOZ:\n{archetype_instructions}",
            playbook,
            f"CONDIÇÕES COMERCIAIS E PAGAMENTO:\n{payment_info}\n"
            "Nunca invente produtos, preços ou dados bancários que não constem nas ferramentas oficiais.",
        ]

        # Instruções customizadas cadastradas pelo lojista
        custom_instructions = (company_settings.ai_system_prompt or "").strip()
        if custom_instructions:
            sections.append(
                f"INSTRUÇÕES ESPECÍFICAS DA LOJA (Regras Internas Prioritárias):\n{custom_instructions}"
            )

        return "\n\n---\n\n".join(sections)
