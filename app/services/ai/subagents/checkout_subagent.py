import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.delivery import DeliveryCreate
from app.services.ai.providers.base import ToolDefinition
from app.services.ai.subagents.base import BaseSubagent
from app.services.delivery_service import DeliveryService
from app.services.payment_service import PaymentService
from app.services.product_service import ProductService

logger = logging.getLogger(__name__)


class CheckoutSubagent(BaseSubagent):
    """
    Subagente especialista em checkout, criação de pedidos e cobranças.
    Suporta pagamento antecipado (PIX online) e pagamento no ato da entrega (na_entrega).
    Registra automaticamente o pedido na Logística e gera o código de despacho.
    """

    def __init__(
        self,
        db: Session,
        user: User,
        payment_service: PaymentService | None = None,
        product_service: ProductService | None = None,
        delivery_service: DeliveryService | None = None,
    ):
        self.db = db
        self.user = user
        self.payment_service = payment_service or PaymentService(db)
        self.product_service = product_service or ProductService(db)
        self.delivery_service = delivery_service or DeliveryService(db)

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="criar_pedido_entrega",
                description=(
                    "Registra um pedido completo de venda com entrega no endereço do cliente. "
                    "Permite ao cliente escolher pagar antecipadamente (PIX) ou pagar no ato da entrega (Dinheiro, PIX ou Cartão com o entregador)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "produto_id": {
                            "type": "integer",
                            "description": "ID numérico do produto comprado.",
                        },
                        "quantidade": {
                            "type": "integer",
                            "description": "Quantidade de unidades do produto (padrão: 1).",
                        },
                        "momento_pagamento": {
                            "type": "string",
                            "enum": ["antecipado", "na_entrega"],
                            "description": "Se o cliente vai pagar antecipado (PIX) ou na entrega (no local ao receber).",
                        },
                        "forma_pagamento": {
                            "type": "string",
                            "enum": ["pix", "dinheiro", "cartao_credito", "cartao_debito"],
                            "description": "Meio de pagamento escolhido pelo cliente (PIX, dinheiro, cartão de crédito ou cartão de débito).",
                        },
                        "endereco_entrega": {
                            "type": "string",
                            "description": "Endereço completo de entrega fornecido pelo cliente (rua, número, bairro, cidade).",
                        },
                        "observacao": {
                            "type": "string",
                            "description": "Instruções adicionais ou ponto de referência informado pelo cliente.",
                        },
                    },
                    "required": ["produto_id", "momento_pagamento"],
                },
            ),
            ToolDefinition(
                name="criar_pedido_cobranca",
                description="Gera uma cobrança PIX imediata online para compra de um produto selecionado pelo cliente.",
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
                            "description": "Observações adicionais ou preferências informadas pelo cliente.",
                        },
                    },
                    "required": ["produto_id"],
                },
            ),
        ]

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name == "criar_pedido_entrega":
            return await self._handle_create_delivery_order(arguments)
        elif tool_name == "criar_pedido_cobranca":
            return await self._handle_create_payment_charge(arguments)

        return json.dumps({"erro": f"Ferramenta desconhecida no CheckoutSubagent: {tool_name}"}, ensure_ascii=False)

    async def _handle_create_delivery_order(self, arguments: dict[str, Any]) -> str:
        produto_id = arguments.get("produto_id")
        if not produto_id:
            return json.dumps({"erro": "produto_id é obrigatório"}, ensure_ascii=False)

        product = self.product_service.get_product(int(produto_id))
        if not product or not product.active:
            return json.dumps({"erro": f"Produto #{produto_id} não está disponível."}, ensure_ascii=False)

        quantidade = max(1, int(arguments.get("quantidade") or 1))
        total_cents = product.price_cents * quantidade
        momento = arguments.get("momento_pagamento") or "na_entrega"
        forma = arguments.get("forma_pagamento") or "pix"
        observacao = arguments.get("observacao") or ""

        # Atualiza endereço do cliente se fornecido na conversa
        address_arg = arguments.get("endereco_entrega")
        if address_arg and address_arg.strip():
            self.user.address = address_arg.strip()
            self.db.commit()

        final_address = self.user.full_address or self.user.address or address_arg or "Endereço a confirmar com o cliente"

        custom_fields = self.user.custom_fields or {}
        seller_id = custom_fields.get("seller_id")
        branch_id = custom_fields.get("branch_id")

        payment_id = None
        invoice_url = None

        if momento == "antecipado":
            try:
                payment = await self.payment_service.create_direct_charge(
                    user_id=self.user.id,
                    amount_cents=total_cents,
                    product_id=product.id,
                    description=f"{quantidade}x {product.name}",
                    billing_type="PIX",
                    seller_id=seller_id,
                    branch_id=branch_id,
                )
                payment_id = payment.id
                invoice_url = payment.invoice_url
            except Exception as e:
                logger.warning("Falha ao gerar cobrança antecipada no checkout: %s", e)

        # Cadastra o pedido diretamente no controle de Logística
        desc_itens = f"{quantidade}x {product.name}"
        if product.sku:
            desc_itens += f" (SKU: {product.sku})"

        delivery_dto = DeliveryCreate(
            user_id=self.user.id,
            branch_id=branch_id,
            seller_id=seller_id,
            payment_id=payment_id,
            items_description=desc_itens,
            total_amount_cents=total_cents,
            payment_method=forma,
            payment_timing=momento,
            payment_status="pago" if (momento == "antecipado" and invoice_url is None) else "pendente",
            delivery_status="preparando",
            delivery_address=final_address,
            notes=observacao or None,
        )

        delivery = self.delivery_service.create_delivery(delivery_dto)
        order_code = delivery.get("order_code", "ENT-XXXX")

        if momento == "na_entrega":
            return json.dumps({
                "status": "sucesso",
                "codigo_pedido": order_code,
                "produto_nome": product.name,
                "quantidade": quantidade,
                "valor_total_formatado": f"R$ {total_cents / 100:.2f}",
                "momento_pagamento": "na_entrega",
                "forma_pagamento": forma,
                "endereco_entrega": final_address,
                "instrucoes": (
                    f"Confirme ao cliente que o pedido {order_code} foi registrado com sucesso para entrega no endereço informado! "
                    f"Diga que o entregador levará a mercadoria e receberá o valor de R$ {total_cents / 100:.2f} via {forma.upper()} no ato da entrega."
                ),
            }, ensure_ascii=False)
        else:
            return json.dumps({
                "status": "sucesso",
                "codigo_pedido": order_code,
                "produto_nome": product.name,
                "quantidade": quantidade,
                "valor_total_formatado": f"R$ {total_cents / 100:.2f}",
                "momento_pagamento": "antecipado",
                "link_pagamento": invoice_url or "Código PIX será enviado em instantes",
                "endereco_entrega": final_address,
                "instrucoes": (
                    f"Informe ao cliente o valor de R$ {total_cents / 100:.2f}, envie o link de pagamento PIX e diga que o pedido {order_code} "
                    f"será despachado para {final_address} assim que o pagamento for liquidado."
                ),
            }, ensure_ascii=False)

    async def _handle_create_payment_charge(self, arguments: dict[str, Any]) -> str:
        produto_id = arguments.get("produto_id")
        if not produto_id:
            return json.dumps({"erro": "produto_id é obrigatório"}, ensure_ascii=False)

        quantidade = max(1, int(arguments.get("quantidade") or 1))
        observacao = arguments.get("observacao") or ""

        product = self.product_service.get_product(int(produto_id))
        if not product or not product.active:
            return json.dumps({"erro": f"Produto #{produto_id} não está disponível."}, ensure_ascii=False)

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

            # Cria também a entrega pendente
            try:
                self.delivery_service.create_delivery(
                    DeliveryCreate(
                        user_id=self.user.id,
                        branch_id=branch_id,
                        seller_id=seller_id,
                        payment_id=payment.id,
                        items_description=f"{quantidade}x {product.name}",
                        total_amount_cents=total_cents,
                        payment_method="pix",
                        payment_timing="antecipado",
                        payment_status="pendente",
                        delivery_status="preparando",
                        delivery_address=self.user.full_address or self.user.address or "Endereço a confirmar",
                    )
                )
            except Exception as e:
                logger.debug("Falha ao registrar entrega vinculada ao pagamento: %s", e)

            return json.dumps({
                "status": "sucesso",
                "pedido_id": payment.id,
                "produto_id": product.id,
                "produto_nome": product.name,
                "peso_total_kg": round(float(product.weight_kg) * quantidade, 3) if product.weight_kg is not None else None,
                "quantidade": quantidade,
                "valor_total_formatado": f"R$ {total_cents / 100:.2f}",
                "link_pagamento": payment.invoice_url or "Link será enviado em instantes",
                "instrucoes": "Informe ao cliente o valor, o link do PIX e avise que a confirmação é automática após o pagamento.",
            }, ensure_ascii=False)

        except Exception as exc:
            logger.error("Erro ao gerar cobrança no CheckoutSubagent: %s", exc)
            return json.dumps({
                "erro": "Não foi possível gerar a chave PIX no momento.",
                "detalhes": str(exc),
            }, ensure_ascii=False)
