import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.user import User
from app.services.ai.providers.base import ToolDefinition
from app.services.ai.subagents.base import BaseSubagent
from app.services.payment_service import PaymentService
from app.services.product_service import ProductService

logger = logging.getLogger(__name__)


class CheckoutSubagent(BaseSubagent):
    """
    Subagente especialista em checkout, criação de pedidos e cobranças via PIX (Asaas).
    Gera o pedido e link oficial de pagamento imediatamente para o cliente.
    """

    def __init__(
        self,
        db: Session,
        user: User,
        payment_service: PaymentService | None = None,
        product_service: ProductService | None = None,
    ):
        self.db = db
        self.user = user
        self.payment_service = payment_service or PaymentService(db)
        self.product_service = product_service or ProductService(db)

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="criar_pedido_cobranca",
                description="Gera uma cobrança PIX imediata no Asaas para compra de um ou mais itens de um produto selecionado pelo cliente.",
                parameters={
                    "type": "object",
                    "properties": {
                        "produto_id": {
                            "type": "integer",
                            "description": "ID numérico do produto que o cliente deseja comprar.",
                        },
                        "quantidade": {
                            "type": "integer",
                            "description": "Quantidade de unidades do produto (padrão: 1).",
                        },
                        "observacao": {
                            "type": "string",
                            "description": "Observações adicionais ou preferências de entrega informadas pelo cliente.",
                        },
                    },
                    "required": ["produto_id"],
                },
            ),
        ]

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name != "criar_pedido_cobranca":
            return json.dumps({"erro": f"Ferramenta desconhecida no CheckoutSubagent: {tool_name}"}, ensure_ascii=False)

        produto_id = arguments.get("produto_id")
        if not produto_id:
            return json.dumps({"erro": "produto_id é obrigatório para gerar a cobrança"}, ensure_ascii=False)

        quantidade = max(1, int(arguments.get("quantidade") or 1))
        observacao = arguments.get("observacao") or ""

        product = self.product_service.get_product(int(produto_id))
        if not product or not product.active:
            return json.dumps({"erro": f"Produto #{produto_id} não está disponível para venda no momento."}, ensure_ascii=False)

        total_cents = product.price_cents * quantidade
        desc = f"Pedido: {quantidade}x {product.name}"
        if observacao:
            desc += f" ({observacao})"

        try:
            custom_fields = self.user.custom_fields or {}
            seller_id = custom_fields.get("seller_id")
            branch_id = custom_fields.get("branch_id")

            payment = await self.payment_service.create_direct_charge(
                user_id=self.user.id,
                amount_cents=total_cents,
                product_id=product.id,
                description=desc,
                billing_type="PIX",
                seller_id=seller_id,
                branch_id=branch_id,
            )


            peso_total = None
            if product.weight_kg is not None:
                peso_total = round(float(product.weight_kg) * quantidade, 3)

            return json.dumps({
                "status": "sucesso",
                "pedido_id": payment.id,
                "produto_id": product.id,
                "produto_nome": product.name,
                "quantidade": quantidade,
                "valor_total_formatado": f"R$ {total_cents / 100:.2f}",
                "peso_total_kg": peso_total,
                "link_pagamento": payment.invoice_url or "Link será enviado em instantes",
                "instrucoes": "Informe ao cliente o valor, o link do PIX e avise que a confirmação é automática após o pagamento.",
            }, ensure_ascii=False)

        except Exception as exc:
            logger.error("Erro ao gerar cobrança no CheckoutSubagent: %s", exc)
            return json.dumps({
                "erro": "Não foi possível gerar a chave PIX no momento devido a uma instabilidade momentânea no gateway de pagamento.",
                "detalhes": str(exc),
            }, ensure_ascii=False)
