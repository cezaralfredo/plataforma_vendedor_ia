import json
import logging
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.delivery import Delivery
from app.models.payment import Payment
from app.models.user import User
from app.services.ai.providers.base import ToolDefinition
from app.services.ai.subagents.base import BaseSubagent

logger = logging.getLogger(__name__)

PAYMENT_TRANSLATIONS = {
    "pending": "Aguardando pagamento ⏳",
    "received": "Pago com sucesso / Confirmado ✅",
    "confirmed": "Pago com sucesso / Confirmado ✅",
    "overdue": "Cobrança vencida ❌",
    "refunded": "Reembolsado ↩️",
}

DELIVERY_TRANSLATIONS = {
    "preparando": "📦 Em separação / preparação na loja",
    "a_caminho": "🚚 A caminho / Saiu para entrega ao seu endereço!",
    "entregue": "✅ Entregue com sucesso!",
    "cancelado": "❌ Cancelado",
}


class OrderStatusSubagent(BaseSubagent):
    """
    Subagente especialista em consulta de status de pedidos, rastreamento de entregas
    e confirmação de pagamentos.
    """

    def __init__(self, db: Session, user: User):
        self.db = db
        self.user = user

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="consultar_status_pedido",
                description="Consulta os últimos pedidos, entregas em andamento e status de pagamento do cliente na loja.",
                parameters={
                    "type": "object",
                    "properties": {
                        "codigo_pedido": {
                            "type": "string",
                            "description": "Código opcional da entrega (ex: ENT-0001) ou ID do pedido para consulta direta.",
                        },
                    },
                },
            ),
        ]

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name != "consultar_status_pedido":
            return json.dumps({"erro": f"Ferramenta desconhecida: {tool_name}"}, ensure_ascii=False)

        codigo_arg = (arguments.get("codigo_pedido") or "").strip().upper()
        digits = "".join(filter(str.isdigit, codigo_arg))

        # 1. Busca entregas do cliente
        query_del = self.db.query(Delivery).filter(Delivery.user_id == self.user.id)
        if codigo_arg:
            del_filters = [Delivery.order_code == codigo_arg]
            if digits:
                del_filters.append(Delivery.order_code == f"ENT-{int(digits):04d}")
                del_filters.append(Delivery.id == int(digits))
            query_del = query_del.filter(or_(*del_filters))

        deliveries = query_del.order_by(Delivery.created_at.desc()).limit(3).all()

        # 2. Busca pagamentos do cliente
        query_pay = self.db.query(Payment).filter(Payment.user_id == self.user.id)
        if digits:
            query_pay = query_pay.filter(Payment.id == int(digits))
        payments = query_pay.order_by(Payment.created_at.desc()).limit(3).all()

        if not deliveries and not payments:
            return json.dumps({
                "status": "sem_pedidos",
                "mensagem": "Você ainda não possui pedidos ou entregas recentes registradas conosco.",
            }, ensure_ascii=False)

        results = []

        # Formata entregas
        for d in deliveries:
            del_status_text = DELIVERY_TRANSLATIONS.get(d.delivery_status, d.delivery_status)
            timing_text = "Pago antecipadamente" if d.payment_timing == "antecipado" or d.payment_status == "pago" else f"Pagar na entrega: R$ {d.total_amount_cents / 100:.2f} ({d.payment_method})"

            results.append({
                "tipo": "entrega",
                "codigo": d.order_code,
                "itens": d.items_description,
                "status": d.delivery_status,
                "status_legivel": del_status_text,
                "status_entrega": d.delivery_status,
                "status_entrega_legivel": del_status_text,
                "endereco": d.delivery_address,
                "entregador": d.delivery_driver_name or "A ser designado",
                "despachado_em": d.dispatched_at.strftime("%d/%m/%Y às %H:%M") if d.dispatched_at else None,
                "entregue_em": d.delivered_at.strftime("%d/%m/%Y às %H:%M") if d.delivered_at else None,
                "pagamento_info": timing_text,
                "data_pedido": d.created_at.strftime("%d/%m/%Y às %H:%M") if d.created_at else "",
            })

        # Formata pagamentos avulsos
        for p in payments:
            pay_status_text = PAYMENT_TRANSLATIONS.get(p.status.lower(), p.status)
            results.append({
                "tipo": "cobranca",
                "id": p.id,
                "pedido_id": p.id,
                "descricao": p.description,
                "valor_formatado": f"R$ {p.amount_cents / 100:.2f}",
                "status": p.status,
                "status_legivel": pay_status_text,
                "status_pagamento": p.status,
                "status_pagamento_legivel": pay_status_text,
                "link_pagamento": p.invoice_url,
                "data": p.created_at.strftime("%d/%m/%Y às %H:%M") if p.created_at else "",
            })

        return json.dumps({
            "status": "sucesso",
            "total_pedidos": len(results),
            "pedidos": results,
            "instrucoes": (
                "Apresente ao cliente de forma clara e objetiva o status da entrega e do pagamento. "
                "Se a entrega estiver 'a_caminho', destaque que o entregador já saiu e reforce o endereço de entrega."
            ),
        }, ensure_ascii=False)
