import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.chat_message import ChatMessage
from app.models.company_settings import CompanySettings
from app.models.user import User
from app.services.ai.prompt_engine import SalesPromptEngine
from app.services.ai.providers.base import (
    BaseLLMClient,
    LLMMessage,
    ToolCall,
    ToolDefinition,
)
from app.services.ai.providers.factory import get_llm_client
from app.services.ai.subagents.base import BaseSubagent
from app.services.ai.subagents.catalog_subagent import CatalogSubagent
from app.services.ai.subagents.checkout_subagent import CheckoutSubagent
from app.services.ai.subagents.order_status_subagent import OrderStatusSubagent
from app.services.ai.subagents.support_subagent import SupportSubagent

logger = logging.getLogger(__name__)


class SalesOrchestrator:
    """
    Orquestrador central de inteligência artificial de vendas.
    Coordena a conversa com o cliente, aciona o provedor de LLM escolhido pelo tenant,
    gerencia a execução de ferramentas nos subagentes especializados e fornece
    fallback determinístico de alta confiabilidade para garantir vendas ininterruptas.
    """

    def __init__(
        self,
        db: Session,
        user: User,
        company_settings: CompanySettings,
        llm_client: BaseLLMClient | None = None,
        payment_service: Any = None,
        product_service: Any = None,
        delivery_service: Any = None,
        gateway: Any = None,
    ):
        self.db = db
        self.user = user
        self.company_settings = company_settings
        self.llm_client = llm_client if llm_client is not None else get_llm_client(company_settings)
        self.gateway = gateway
        self.delivery_service = delivery_service

        # Inicializa subagentes especialistas com recursos multimídia e logísticos
        self.catalog_subagent = CatalogSubagent(
            db, product_service=product_service, user=user, gateway=gateway
        )
        self.checkout_subagent = CheckoutSubagent(
            db,
            user,
            payment_service=payment_service,
            product_service=product_service,
            delivery_service=delivery_service,
        )
        self.order_status_subagent = OrderStatusSubagent(db, user)
        self.support_subagent = SupportSubagent(company_settings, db=db, user=user, gateway=gateway)

        # Registro de ferramentas mapeadas para os respectivos subagentes
        self.subagents: list[BaseSubagent] = [
            self.catalog_subagent,
            self.checkout_subagent,
            self.order_status_subagent,
            self.support_subagent,
        ]
        self._tool_map: dict[str, BaseSubagent] = {}
        self._all_tools: list[ToolDefinition] = []
        self._register_subagents()

    def _register_subagents(self) -> None:
        for sa in self.subagents:
            for tool_def in sa.get_tools():
                self._tool_map[tool_def.name] = sa
                self._all_tools.append(tool_def)


    def _build_system_prompt(self) -> str:
        return SalesPromptEngine.build_system_prompt(
            company_settings=self.company_settings,
            user=self.user,
        )


    async def _execute_tool_call(self, tool_call: ToolCall) -> str:
        subagent = self._tool_map.get(tool_call.name)
        if not subagent:
            logger.warning("Ferramenta '%s' solicitada pelo LLM não foi encontrada em nenhum subagente.", tool_call.name)
            return json.dumps({"erro": f"Ferramenta '{tool_call.name}' não reconhecida."}, ensure_ascii=False)

        try:
            return await subagent.execute_tool(tool_call.name, tool_call.arguments)
        except Exception as exc:
            logger.error("Falha ao executar ferramenta '%s': %s", tool_call.name, exc)
            return json.dumps({"erro": f"Erro interno ao executar {tool_call.name}: {exc!s}"}, ensure_ascii=False)

    async def _run_llm_orchestration(
        self,
        user_message: str,
        history: list[ChatMessage],
    ) -> str | None:
        if not self.llm_client:
            return None

        system_prompt = self._build_system_prompt()
        messages: list[LLMMessage] = [LLMMessage(role="system", content=system_prompt)]

        for h in history:
            messages.append(LLMMessage(role=h.role, content=h.content))

        messages.append(LLMMessage(role="user", content=user_message))

        temperature = float(self.company_settings.ai_temperature or 0.3)

        # Loop de Tool Calling (máximo de 3 iterações para segurança)
        max_iterations = 3
        for _iteration in range(max_iterations):
            response = await self.llm_client.generate_response(
                messages=messages,
                tools=self._all_tools,
                temperature=temperature,
            )

            # Se o modelo devolveu texto final sem chamadas adicionais de ferramentas
            if not response.tool_calls:
                if response.content:
                    return response.content.strip()
                break

            # Se o modelo solicitou execução de ferramentas dos subagentes
            messages.append(
                LLMMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )

            for tc in response.tool_calls:
                logger.info("Orquestrador IA executando subagente ferramenta: %s(args=%s)", tc.name, tc.arguments)
                tool_result_str = await self._execute_tool_call(tc)
                messages.append(
                    LLMMessage(
                        role="tool",
                        content=tool_result_str,
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )

        return None

    async def _run_deterministic_fallback(self, user_message: str) -> str:
        """
        Mecanismo determinístico autônomo acionado quando a API do LLM não está configurada
        ou está temporariamente indisponível. Garante que nenhuma mensagem fique sem resposta.
        """
        lowered = user_message.lower().strip()
        customer_name = self.user.name or "Cliente"

        # 1. Atendimento Humano
        if any(w in lowered for w in ["atendente", "humano", "pessoa", "suporte", "ajuda humana"]):
            res = await self.support_subagent.execute_tool("acionar_atendente_humano", {"motivo": lowered})
            data = json.loads(res)
            return (
                f"Com certeza, {customer_name}! Já notifiquei nossa equipe.\n\n"
                f"Se preferir falar diretamente agora com um atendente, basta clicar:\n"
                f"👉 {data.get('link_suporte')}\n\n"
                "Em instantes você será atendido!"
            )

        # 2. Status de Pedidos
        if any(w in lowered for w in ["meu pedido", "status", "onde está", "rastreio", "foi aprovado", "confirmou"]):
            res = await self.order_status_subagent.execute_tool("consultar_status_pedido", {})
            data = json.loads(res)
            if data.get("status") == "sucesso" and data.get("pedidos"):
                lines = [f"📋 *Seus Pedidos Recentes - {customer_name}:*\n"]
                for p in data["pedidos"]:
                    lines.append(f"• *Pedido #{p['pedido_id']}* ({p['data']}): {p['valor_formatado']}\n  Status: {p['status_legivel']}")
                    if p.get("link_pagamento") and "aguardando" in p["status_legivel"].lower():
                        lines.append(f"  Link PIX: {p['link_pagamento']}")
                return "\n".join(lines)
            return f"Olá, {customer_name}! No momento não encontrei pedidos pendentes em seu nome."

        # 3. Compra Direta de Produto
        if any(w in lowered for w in ["comprar", "pedido", "pix", "quero", "levar"]):
            cat_res = await self.catalog_subagent.execute_tool("consultar_catalogo", {})
            cat_data = json.loads(cat_res)
            products = cat_data.get("produtos", [])

            matched_id: int | None = None
            id_match = re.search(r"#?(\d+)", lowered)
            if id_match:
                candidate_id = int(id_match.group(1))
                if any(p["id"] == candidate_id for p in products):
                    matched_id = candidate_id

            if not matched_id:
                for p in products:
                    if p["nome"].lower() in lowered:
                        matched_id = p["id"]
                        break

            if matched_id:
                checkout_res = await self.checkout_subagent.execute_tool(
                    "criar_pedido_cobranca",
                    {"produto_id": matched_id, "quantidade": 1},
                )
                checkout_data = json.loads(checkout_res)
                if checkout_data.get("status") == "sucesso":
                    peso_str = f" | Peso: {checkout_data['peso_total_kg']:.3f} kg" if checkout_data.get("peso_total_kg") else ""
                    return (
                        f"🎉 Excelente escolha, {customer_name}!\n\n"
                        f"📦 *Pedido #{checkout_data['pedido_id']} Criado:*\n"
                        f"• *Item:* {checkout_data['produto_nome']}{peso_str}\n"
                        f"• *Total:* {checkout_data['valor_total_formatado']}\n\n"
                        f"💳 *Efetue o pagamento PIX no link seguro:*\n"
                        f"{checkout_data['link_pagamento']}\n\n"
                        f"Assim que o pagamento for concluído, seu pedido será confirmado automaticamente! 🚀"
                    )

        # 4. Consulta de Catálogo
        cat_res = await self.catalog_subagent.execute_tool("consultar_catalogo", {})
        cat_data = json.loads(cat_res)
        products = cat_data.get("produtos", [])

        if not products:
            return f"Olá, {customer_name}! No momento nosso catálogo está sendo atualizado. Por favor, volte em breve!"

        company_name = self.company_settings.company_name or "Nossa Loja"
        lines = [f"🛍️ *Catálogo de Produtos - {company_name}*\n"]
        for p in products:
            peso_str = f" | Peso: {p['peso_kg']:.3f} kg" if p.get("peso_kg") else ""
            lines.append(f"• *#{p['id']} - {p['nome']}*: {p['preco_reais']}{peso_str}")

        lines.append("\nPara comprar qualquer produto, basta me responder dizendo o *nome* ou *número* dele que eu gero seu PIX!")
        return "\n".join(lines)

    async def process_message(self, user_message: str, history: list[ChatMessage]) -> str:
        """
        Ponto central de processamento de mensagens.
        Tenta a orquestração via LLM + subagentes; se falhar ou não houver chave,
        executa o fallback determinístico.
        """
        response_text: str | None = None

        if self.llm_client:
            try:
                response_text = await self._run_llm_orchestration(user_message, history)
            except Exception as exc:
                logger.warning("Falha na orquestração LLM (%s): %s. Executando fallback determinístico.", self.company_settings.ai_provider, exc)

        if not response_text:
            response_text = await self._run_deterministic_fallback(user_message)

        return response_text
