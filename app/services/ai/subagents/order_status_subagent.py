import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.models.user import User
from app.services.ai.providers.base import ToolDefinition
from app.services.ai.subagents.base import BaseSubagent

logger = logging.getLogger(__name__)

STATUS_TRANSLATIONS = {
    "pending": "Aguardando pagamento PIX ⏳",
    "received": "Pago com sucesso / Confirmado ✅",
    "confirmed": "Pago com sucesso / Confirmado ✅",
    "overdue": "Cobrança vencida ❌",
    "refunded": "Reembolsado ↩️",
}


class OrderStatusSubagent(BaseSubagent):
    """
    Subagente especialista em consulta de status de pedidos e confirmação de pagamentos.
    """

    def __init__(self, db: Session, user: User):
        self.db = db
        self.user = user

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="consultar_status_pedido",
                description="Consulta os últimos pedidos e status de pagamento do cliente atual na loja.",
                parameters={
                    "type": "object",
                    "properties": {
                        "pedido_id": {
                            "type": "integer",
                            "description": "ID opcional do pedido para consultar status específico.",
                        },
                    },
                },
            ),
        ]

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name != "consultar_status_pedido":
            return json.dumps({"erro": f"Ferramenta desconhecida: {tool_name}"}, ensure_ascii=False)

        pedido_id = arguments.get("pedido_id")
        query = self.db.query(Payment).filter(Payment.user_id == self.user.id)

        if pedido_id:
            query = query.filter(Payment.id == int(pedido_id))

        orders = query.order_by(Payment.created_at.desc()).limit(5).all()
        if not orders:
            return json.dumps({
                "status": "sem_pedidos",
                "mensagem": "Você ainda não possui pedidos recentes cadastrados conosco.",
            }, ensure_ascii=False)

        result_orders = []
        for o in orders:
            status_desc = STATUS_TRANSLATIONS.get(o.status.lower(), o.status)
            result_orders.append({
                "pedido_id": o.id,
                "valor_formatado": f"R$ {o.amount_cents / 100:.2f}",
                "status": o.status,
                "status_legivel": status_desc,
                "descricao": o.description,
                "link_pagamento": o.invoice_url,
                "data": o.created_at.strftime("%d/%m/%Y às %H:%M") if o.created_at else "",
            })

        return json.dumps({
            "status": "sucesso",
            "pedidos": result_orders,
        }, ensure_ascii=False)
