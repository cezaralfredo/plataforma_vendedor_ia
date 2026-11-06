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
    "cancelled": "Cancelado ❌",
}

DELIVERY_TRANSLATIONS = {
    "preparando": "📦 Em separação / preparação na loja",
    "a_caminho": "🚚 A caminho / Saiu para entrega ao seu endereço!",
    "entregue": "✅ Entregue com sucesso!",
    "cancelado": "❌ Cancelado",
}


class OrderStatusSubagent(BaseSubagent):
    """
    Subagente especialista em consulta de status de pedidos, rastreamento de entregas,
    confirmação de pagamentos e cancelamento autônomo de pedidos em aberto.
    """

    def __init__(self, db: Session, user: User, company_settings: Any = None):
        self.db = db
        self.user = user
        self.company_settings = company_settings

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
            ToolDefinition(
                name="cancelar_pedido",
                description="Cancela um pedido/entrega pendente ou cobrança em aberto do cliente. Se o pedido já estiver a caminho ou entregue, informa a situação e transfere para atendimento humano.",
                parameters={
                    "type": "object",
                    "properties": {
                        "codigo_pedido": {
                            "type": "string",
                            "description": "Código do pedido (ex: ENT-0001 ou #1). Opcional: se omitido, localiza o pedido em aberto mais recente do cliente.",
                        },
                        "motivo": {
                            "type": "string",
                            "description": "Motivo do cancelamento informado pelo cliente.",
                        },
                    },
                },
            ),
        ]

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name == "consultar_status_pedido":
            return await self._consultar_status_pedido(arguments)
        elif tool_name == "cancelar_pedido":
            return await self._cancelar_pedido(arguments)
        else:
            return json.dumps({"erro": f"Ferramenta desconhecida: {tool_name}"}, ensure_ascii=False)

    async def _cancelar_pedido(self, arguments: dict[str, Any]) -> str:
        codigo_arg = (arguments.get("codigo_pedido") or "").strip().upper()
        digits = "".join(filter(str.isdigit, codigo_arg))
        motivo = (arguments.get("motivo") or "Solicitado pelo cliente no WhatsApp").strip()

        # Busca entrega do cliente (específica por código ou a mais recente que não esteja já cancelada)
        query = self.db.query(Delivery).filter(Delivery.user_id == self.user.id)
        if codigo_arg:
            del_filters = [Delivery.order_code == codigo_arg]
            if digits:
                del_filters.append(Delivery.order_code == f"ENT-{int(digits):04d}")
                del_filters.append(Delivery.id == int(digits))
            query = query.filter(or_(*del_filters))
        else:
            query = query.filter(Delivery.delivery_status != "cancelado")

        delivery = query.order_by(Delivery.created_at.desc()).first()

        # Configurações de suporte para contato
        human_phone = "5585996277707"
        human_name = "Equipe Anauê"
        if self.company_settings:
            human_phone = getattr(self.company_settings, "human_support_phone", None) or human_phone
            human_name = getattr(self.company_settings, "human_support_name", None) or human_name
        clean_phone = "".join(filter(str.isdigit, human_phone))
        if len(clean_phone) in (10, 11) and not clean_phone.startswith("55"):
            clean_phone = "55" + clean_phone
        support_link = f"https://wa.me/{clean_phone}"

        if delivery:
            if delivery.delivery_status == "a_caminho":
                return json.dumps({
                    "status": "em_rota",
                    "codigo_pedido": delivery.order_code,
                    "mensagem": (
                        f"O pedido {delivery.order_code} já foi despachado e está a caminho do seu endereço! "
                        f"Por conta disso, não consigo cancelá-lo automaticamente pelo sistema. "
                        f"Por favor, fale com a {human_name} no WhatsApp ({support_link}) para orientações sobre devolução."
                    ),
                    "link_suporte": support_link,
                }, ensure_ascii=False)

            if delivery.delivery_status == "entregue":
                return json.dumps({
                    "status": "ja_entregue",
                    "codigo_pedido": delivery.order_code,
                    "mensagem": f"O pedido {delivery.order_code} já consta como entregue.",
                    "link_suporte": support_link,
                }, ensure_ascii=False)

            # Pedido em preparação ou pendente -> Cancelar com segurança
            delivery.delivery_status = "cancelado"
            note_entry = f"Cancelado a pedido do cliente no WhatsApp ({motivo})"
            delivery.notes = f"{delivery.notes} | {note_entry}".strip(" |") if delivery.notes else note_entry

            # Cancela pagamento associado se houver
            if delivery.payment_id:
                pay = self.db.get(Payment, delivery.payment_id)
                if pay and pay.status in ("pending", "awaiting_payment"):
                    pay.status = "cancelled"

            # Cancela pagamentos pendentes do usuário para evitar cobrança pendente
            pending_pays = (
                self.db.query(Payment)
                .filter(Payment.user_id == self.user.id, Payment.status == "pending")
                .all()
            )
            for p in pending_pays:
                p.status = "cancelled"

            self.db.commit()

            valor_str = f"R$ {delivery.total_amount_cents / 100:.2f}".replace(".", ",")
            return json.dumps({
                "status": "sucesso",
                "pedido_cancelado": delivery.order_code,
                "itens": delivery.items_description,
                "valor_formatado": valor_str,
                "mensagem": f"Seu pedido *{delivery.order_code}* ({delivery.items_description}) no valor de *{valor_str}* foi CANCELADO com sucesso!",
                "instrucoes": (
                    "Confirme o cancelamento com carinho e tranquilidade para o cliente. "
                    "Explique que o pedido não será enviado e nada será cobrado. "
                    "Pergunte com gentileza se você pode ajudar com mais alguma coisa ou com outro produto do catálogo."
                ),
            }, ensure_ascii=False)

        # Se não encontrou entrega, verifica se havia pagamento pendente avulso
        pending_payment = (
            self.db.query(Payment)
            .filter(Payment.user_id == self.user.id, Payment.status == "pending")
            .order_by(Payment.created_at.desc())
            .first()
        )
        if pending_payment:
            pending_payment.status = "cancelled"
            self.db.commit()
            valor_str = f"R$ {pending_payment.amount_cents / 100:.2f}".replace(".", ",")
            return json.dumps({
                "status": "sucesso",
                "pedido_cancelado": f"COB-{pending_payment.id}",
                "valor_formatado": valor_str,
                "mensagem": f"A cobrança pendente #{pending_payment.id} no valor de *{valor_str}* foi CANCELADA com sucesso!",
                "instrucoes": "Confirme que a cobrança foi cancelada e não precisa ser paga.",
            }, ensure_ascii=False)

        return json.dumps({
            "status": "sem_pedidos_cancelaveis",
            "mensagem": "Não localizei nenhum pedido em aberto ou cobrança pendente em seu nome para cancelamento no momento.",
            "instrucoes": (
                f"Informe gentilmente ao cliente que não há pedidos em aberto aguardando envio em seu nome. "
                f"Se ele tiver dúvidas ou se referir a outro pedido, informe que a {human_name} pode ajudar pelo WhatsApp: {support_link}"
            ),
            "link_suporte": support_link,
        }, ensure_ascii=False)

    async def _consultar_status_pedido(self, arguments: dict[str, Any]) -> str:
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

        # Formata entregas (garantindo chaves unificadas para o Orquestrador)
        for d in deliveries:
            del_status_text = DELIVERY_TRANSLATIONS.get(d.delivery_status, d.delivery_status)
            if d.payment_status == "pago":
                timing_text = "Pago com sucesso ✅"
            elif d.payment_timing == "antecipado":
                timing_text = f"Aguardando pagamento PIX: R$ {d.total_amount_cents / 100:.2f} ⏳"
            else:
                timing_text = f"Pagar na entrega: R$ {d.total_amount_cents / 100:.2f} ({d.payment_method})"

            invoice_link = None
            if d.payment and d.payment.invoice_url:
                invoice_link = d.payment.invoice_url

            data_str = d.created_at.strftime("%d/%m/%Y às %H:%M") if d.created_at else ""

            results.append({
                "tipo": "entrega",
                "id": d.id,
                "pedido_id": d.id,
                "codigo": d.order_code,
                "codigo_pedido": d.order_code,
                "itens": d.items_description,
                "descricao": d.items_description,
                "valor_formatado": f"R$ {d.total_amount_cents / 100:.2f}",
                "total_cents": d.total_amount_cents,
                "status": d.delivery_status,
                "status_legivel": del_status_text,
                "status_entrega": d.delivery_status,
                "status_entrega_legivel": del_status_text,
                "status_pagamento": d.payment_status,
                "status_pagamento_legivel": "Pago ✅" if d.payment_status == "pago" else "Pendente ⏳",
                "endereco": d.delivery_address,
                "entregador": d.delivery_driver_name or "A ser designado",
                "despachado_em": d.dispatched_at.strftime("%d/%m/%Y às %H:%M") if d.dispatched_at else None,
                "entregue_em": d.delivered_at.strftime("%d/%m/%Y às %H:%M") if d.delivered_at else None,
                "pagamento_info": timing_text,
                "link_pagamento": invoice_link,
                "data": data_str,
                "data_pedido": data_str,
            })

        # Formata pagamentos avulsos
        for p in payments:
            pay_status_text = PAYMENT_TRANSLATIONS.get(p.status.lower(), p.status)
            data_str = p.created_at.strftime("%d/%m/%Y às %H:%M") if p.created_at else ""
            results.append({
                "tipo": "cobranca",
                "id": p.id,
                "pedido_id": p.id,
                "codigo": f"COB-{p.id}",
                "codigo_pedido": f"COB-{p.id}",
                "descricao": p.description or "Cobrança de produto",
                "itens": p.description or "Cobrança de produto",
                "valor_formatado": f"R$ {p.amount_cents / 100:.2f}",
                "total_cents": p.amount_cents,
                "status": p.status,
                "status_legivel": pay_status_text,
                "status_pagamento": p.status,
                "status_pagamento_legivel": pay_status_text,
                "status_entrega": "cobranca",
                "status_entrega_legivel": pay_status_text,
                "link_pagamento": p.invoice_url,
                "data": data_str,
                "data_pedido": data_str,
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
