import json
import logging
from typing import Any

from app.models.company_settings import CompanySettings
from app.services.ai.providers.base import ToolDefinition
from app.services.ai.subagents.base import BaseSubagent

logger = logging.getLogger(__name__)


class SupportSubagent(BaseSubagent):
    """
    Subagente especialista em transbordo e encaminhamento para atendimento humano.
    """

    def __init__(
        self,
        company_settings: CompanySettings,
        db: Any = None,
        user: Any = None,
    ):
        self.company_settings = company_settings
        self.db = db
        self.user = user

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="acionar_atendente_humano",
                description="Aciona a equipe de suporte humano para assumir a conversa ou tirar dúvidas complexas fora do escopo de vendas.",
                parameters={
                    "type": "object",
                    "properties": {
                        "motivo": {
                            "type": "string",
                            "description": "Motivo resumido pelo qual o cliente solicitou atendimento humano.",
                        },
                    },
                },
            ),
        ]

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        from datetime import UTC, datetime, timedelta

        if tool_name != "acionar_atendente_humano":
            return json.dumps({"erro": f"Ferramenta desconhecida: {tool_name}"}, ensure_ascii=False)

        motivo = arguments.get("motivo") or "Solicitação direta de contato humano"
        logger.info("Transbordo humano solicitado: motivo='%s'", motivo)

        # Pausa o autoatendimento da IA para este cliente por 2 horas para não interferir
        if self.user and self.db:
            custom_fields = dict(self.user.custom_fields or {})
            paused_until = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
            custom_fields["ai_paused_until"] = paused_until
            self.user.custom_fields = custom_fields
            try:
                self.db.commit()
            except Exception as e:
                logger.warning("Falha ao registrar pausa da IA no usuário: %s", e)

        # Canal de suporte da filial, vendedor ou empresa
        support_phone = None
        if self.user:
            custom_fields = self.user.custom_fields or {}
            seller_id = custom_fields.get("seller_id")
            if seller_id and self.db:
                from app.models.seller import Seller
                seller = self.db.query(Seller).filter(Seller.id == seller_id).first()
                if seller and seller.whatsapp_number:
                    support_phone = seller.whatsapp_number

        if not support_phone:
            support_phone = "5585996277707"

        support_link = f"https://wa.me/{support_phone}"

        return json.dumps({
            "status": "sucesso",
            "mensagem": "Equipe de atendimento humano notificada.",
            "link_suporte": support_link,
            "instrucoes": "Informe ao cliente com empatia que a equipe humana foi acionada, forneça o link de contato e explique que um atendente responderá em instantes.",
        }, ensure_ascii=False)

