import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.product import Product
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
    Suporta múltiplos itens no mesmo pedido, quantidades fracionadas/quilos,
    pagamento antecipado (PIX online) e pagamento no ato da entrega (na_entrega).
    Registra automaticamente o pedido na Logística, debita o estoque e gera o código de despacho.
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
                    "Suporta um ou múltiplos produtos (ou quantidades fracionadas/quilos). "
                    "Permite ao cliente escolher pagar antecipadamente (PIX) ou pagar no ato da entrega (Dinheiro, PIX ou Cartão com o entregador)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "itens": {
                            "type": "array",
                            "description": "Lista de produtos comprados pelo cliente. Use sempre que houver 1 ou mais itens no pedido.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "produto_id": {"type": "integer", "description": "ID numérico do produto no catálogo."},
                                    "produto_nome": {"type": "string", "description": "Nome ou descrição do produto."},
                                    "quantidade": {"type": "number", "description": "Quantidade ou peso em kg (ex: 1, 1.5, 2). Padrão: 1."},
                                    "observacao": {"type": "string", "description": "Observações específicas deste item."},
                                },
                                "required": ["produto_id"],
                            },
                        },
                        "produto_id": {
                            "type": "integer",
                            "description": "ID numérico do produto comprado (caso compre apenas 1 produto único sem usar a lista 'itens').",
                        },
                        "quantidade": {
                            "type": "number",
                            "description": "Quantidade de unidades ou peso do produto (padrão: 1).",
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
                        "nome_cliente": {
                            "type": "string",
                            "description": "Nome completo do cliente ou de quem receberá a entrega no local (essencial para a identificação na entrega e etiqueta).",
                        },
                        "endereco_entrega": {
                            "type": "string",
                            "description": "Endereço completo de entrega fornecido pelo cliente (rua, número, bairro, cidade).",
                        },
                        "banco_preferido": {
                            "type": "string",
                            "description": "Banco ou instituição financeira de preferência informada pelo cliente (ex: Nubank, Inter, Itaú, Bradesco, etc.).",
                        },
                        "instrucoes_entrega": {
                            "type": "string",
                            "description": "Instruções específicas de entrega (ex: deixar na portaria, interfone 201, casa dos fundos).",
                        },
                        "observacao": {
                            "type": "string",
                            "description": "Instruções adicionais ou ponto de referência informado pelo cliente.",
                        },
                    },
                    "required": ["momento_pagamento"],
                },
            ),
            ToolDefinition(
                name="criar_pedido_cobranca",
                description=(
                    "Gera uma cobrança PIX imediata online para compra de um ou mais produtos selecionados pelo cliente "
                    "e registra o pedido pendente na logística com o endereço informado."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "itens": {
                            "type": "array",
                            "description": "Lista de produtos que o cliente deseja comprar. Use sempre que houver múltiplos produtos ou peso em kg.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "produto_id": {"type": "integer", "description": "ID numérico do produto no catálogo."},
                                    "produto_nome": {"type": "string", "description": "Nome ou categoria do produto."},
                                    "quantidade": {"type": "number", "description": "Quantidade ou peso em kg (ex: 1, 1.5, 2). Padrão: 1."},
                                    "observacao": {"type": "string", "description": "Observações do item."},
                                },
                                "required": ["produto_id"],
                            },
                        },
                        "produto_id": {
                            "type": "integer",
                            "description": "ID numérico do produto que o cliente deseja comprar (caso seja um item único).",
                        },
                        "quantidade": {
                            "type": "number",
                            "description": "Quantidade ou peso do produto (padrão: 1).",
                        },
                        "nome_cliente": {
                            "type": "string",
                            "description": "Nome completo do cliente informado na conversa.",
                        },
                        "endereco_entrega": {
                            "type": "string",
                            "description": "Endereço completo de entrega fornecido pelo cliente (rua, número, bairro, cidade).",
                        },
                        "banco_preferido": {
                            "type": "string",
                            "description": "Banco ou instituição financeira de preferência informada pelo cliente (ex: Nubank, Inter, etc.).",
                        },
                        "observacao": {
                            "type": "string",
                            "description": "Observações adicionais ou preferências informadas pelo cliente.",
                        },
                    },
                },
            ),
        ]

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name == "criar_pedido_entrega":
            return await self._handle_create_delivery_order(arguments)
        elif tool_name == "criar_pedido_cobranca":
            return await self._handle_create_payment_charge(arguments)

        return json.dumps({"erro": f"Ferramenta desconhecida no CheckoutSubagent: {tool_name}"}, ensure_ascii=False)

    def _extract_items(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        """Extrai a lista de itens tanto do array 'itens' quanto dos campos legados produto_id/quantidade."""
        raw_items = arguments.get("itens")
        items_to_process: list[dict[str, Any]] = []

        if isinstance(raw_items, list) and len(raw_items) > 0:
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                p_id = item.get("produto_id")
                p_name = item.get("produto_nome")
                try:
                    qty = float(item.get("quantidade") or 1.0)
                except (ValueError, TypeError):
                    qty = 1.0
                obs = item.get("observacao") or ""
                if p_id is not None or p_name:
                    items_to_process.append({
                        "produto_id": int(p_id) if p_id is not None else None,
                        "produto_nome": p_name,
                        "quantidade": max(0.01, qty),
                        "observacao": obs,
                    })

        if not items_to_process:
            p_id = arguments.get("produto_id")
            p_name = arguments.get("produto_nome")
            try:
                qty = float(arguments.get("quantidade") or 1.0)
            except (ValueError, TypeError):
                qty = 1.0
            obs = arguments.get("observacao") or ""
            if p_id is not None or p_name:
                items_to_process.append({
                    "produto_id": int(p_id) if p_id is not None else None,
                    "produto_nome": p_name,
                    "quantidade": max(0.01, qty),
                    "observacao": obs,
                })

        return items_to_process

    async def _handle_create_delivery_order(self, arguments: dict[str, Any]) -> str:
        items_raw = self._extract_items(arguments)
        if not items_raw:
            return json.dumps({"erro": "Nenhum produto informado para o pedido."}, ensure_ascii=False)

        # 1. Validação de cada produto e disponibilidade de estoque
        validated_items: list[dict[str, Any]] = []
        total_cents = 0
        total_weight_kg = 0.0

        for it in items_raw:
            product: Product | None = None
            if it["produto_id"] is not None:
                product = self.product_service.get_product(it["produto_id"])
            if not product and it.get("produto_nome"):
                found = self.product_service.find_by_name(str(it["produto_nome"]))
                if found:
                    product = found[0]

            if not product or not product.active:
                ref = it.get("produto_id") or it.get("produto_nome")
                return json.dumps({"erro": f"Produto '{ref}' não está disponível para venda."}, ensure_ascii=False)

            qty = it["quantidade"]
            needed_stock = max(1, round(qty))
            if product.stock_quantity is not None and product.stock_quantity < needed_stock:
                return json.dumps({
                    "status": "estoque_insuficiente",
                    "produto_id": product.id,
                    "produto_nome": product.name,
                    "disponivel": product.stock_quantity,
                    "solicitado": int(qty) if qty.is_integer() else qty,
                    "mensagem": (
                        f"Desculpe, temos apenas {product.stock_quantity} unidade(s) de '{product.name}' "
                        f"em estoque no momento. Deseja pedir essa quantidade?"
                    ),
                }, ensure_ascii=False)

            subtotal = round(product.price_cents * qty)
            total_cents += subtotal
            if product.weight_kg is not None:
                total_weight_kg += float(product.weight_kg) * qty

            prod_label = f"{product.name} ({product.category})" if product.category else product.name
            qty_str = f"{int(qty)}x" if qty.is_integer() else f"{qty}x"
            desc_line = f"{qty_str} {prod_label}"
            if it.get("observacao"):
                desc_line += f" ({it['observacao']})"

            validated_items.append({
                "product": product,
                "quantidade": int(qty) if qty.is_integer() else qty,
                "subtotal_cents": subtotal,
                "prod_label": prod_label,
                "desc_line": desc_line,
            })

        momento = arguments.get("momento_pagamento") or "na_entrega"
        forma = arguments.get("forma_pagamento") or "pix"
        observacao = arguments.get("observacao") or ""

        # 2. Atualização dos dados cadastrais do cliente (Nome, Endereço, etc.)
        changed = False
        nome_arg = arguments.get("nome_cliente")
        if nome_arg and str(nome_arg).strip():
            clean_n = str(nome_arg).strip()
            if clean_n.lower() not in ("cliente", "desconhecido", "nenhum", "null", "undefined", "nao", "não"):
                self.user.name = " ".join(part.capitalize() for part in clean_n.split())
                changed = True

        address_arg = arguments.get("endereco_entrega")
        if address_arg and str(address_arg).strip():
            clean_addr = str(address_arg).strip()
            if clean_addr.lower() not in ("null", "undefined", "nenhum", "a confirmar", "não informado"):
                self.user.address = clean_addr
                changed = True

        banco_arg = arguments.get("banco_preferido")
        if banco_arg and str(banco_arg).strip():
            self.user.preferred_bank = str(banco_arg).strip()
            changed = True

        instrucoes_arg = arguments.get("instrucoes_entrega")
        if instrucoes_arg and str(instrucoes_arg).strip():
            self.user.delivery_instructions = str(instrucoes_arg).strip()
            changed = True

        if changed:
            self.db.commit()

        final_address = (
            (address_arg and str(address_arg).strip())
            or self.user.full_address
            or self.user.address
            or "Endereço a confirmar com o cliente"
        )

        custom_fields = self.user.custom_fields or {}
        seller_id = custom_fields.get("seller_id")
        branch_id = custom_fields.get("branch_id")

        primary_product = validated_items[0]["product"]
        if len(validated_items) == 1:
            desc_itens = validated_items[0]["desc_line"]
        else:
            desc_itens = " + ".join(it["desc_line"] for it in validated_items)

        # 3. Geração de cobrança para pagamento antecipado
        payment_id = None
        invoice_url = None

        if momento == "antecipado":
            try:
                payment = await self.payment_service.create_direct_charge(
                    user_id=self.user.id,
                    amount_cents=total_cents,
                    product_id=primary_product.id,
                    description=f"Pedido: {desc_itens}",
                    billing_type="PIX",
                    seller_id=seller_id,
                    branch_id=branch_id,
                )
                payment_id = payment.id
                invoice_url = payment.invoice_url
            except Exception as e:
                logger.error("Falha ao gerar cobrança antecipada no checkout: %s", e)
                if arguments.get("_is_charge_only"):
                    return json.dumps({
                        "erro": "Não foi possível gerar a chave PIX no momento.",
                        "detalhes": str(e),
                    }, ensure_ascii=False)

        # 4. Cadastra o pedido diretamente no controle de Logística
        # NOTA: O status do pagamento inicial é SEMPRE 'pendente' até confirmação via webhook/admin.
        delivery_dto = DeliveryCreate(
            user_id=self.user.id,
            branch_id=branch_id,
            seller_id=seller_id,
            payment_id=payment_id,
            items_description=desc_itens,
            total_amount_cents=total_cents,
            payment_method=forma,
            payment_timing=momento,
            payment_status="pendente",
            delivery_status="preparando",
            delivery_address=final_address,
            notes=observacao or None,
        )

        delivery = self.delivery_service.create_delivery(delivery_dto)
        order_code = delivery.get("order_code", "ENT-XXXX")

        # 5. Deduz do estoque para todos os itens comprados
        for it in validated_items:
            try:
                qty_deduct = max(1, round(it["quantidade"]))
                self.product_service.adjust_stock(it["product"].id, -qty_deduct)
            except Exception as e:
                logger.warning("Falha ao debitar estoque para produto #%s: %s", it["product"].id, e)

        nome_lembrete = ""
        if (self.user.name or "").strip().lower() in ("cliente", "desconhecido", ""):
            nome_lembrete = " REGRA OBRIGATÓRIA: O nome do cliente ainda não foi identificado. Peça com gentileza o nome completo dele para colocar na etiqueta de entrega!"

        items_summary = [
            {
                "produto_id": it["product"].id,
                "produto_nome": it["prod_label"],
                "quantidade": it["quantidade"],
                "subtotal_formatado": f"R$ {it['subtotal_cents'] / 100:.2f}",
            }
            for it in validated_items
        ]

        if momento == "na_entrega":
            instrucoes = (
                f"Confirme ao cliente que o pedido {order_code} foi registrado com sucesso para entrega no endereço informado ({final_address})! "
                f"Diga que o entregador levará a mercadoria e receberá o valor de R$ {total_cents / 100:.2f} via {forma.upper()} no ato da entrega."
                f"{nome_lembrete}"
            )
        else:
            instrucoes = (
                f"Informe ao cliente o valor total de R$ {total_cents / 100:.2f}, envie o link/código de pagamento PIX e diga que o pedido {order_code} "
                f"será despachado para {final_address} assim que o pagamento for confirmado."
                f"{nome_lembrete}"
            )

        return json.dumps({
            "status": "sucesso",
            "codigo_pedido": order_code,
            "pedido_id": payment_id,
            "produto_id": primary_product.id,
            "produto_nome": validated_items[0]["prod_label"] if len(validated_items) == 1 else desc_itens,
            "quantidade": validated_items[0]["quantidade"] if len(validated_items) == 1 else len(validated_items),
            "itens": items_summary,
            "peso_total_kg": round(total_weight_kg, 3) if total_weight_kg > 0 else None,
            "valor_total_formatado": f"R$ {total_cents / 100:.2f}",
            "valor_total_cents": total_cents,
            "momento_pagamento": momento,
            "forma_pagamento": forma,
            "link_pagamento": invoice_url or "Código PIX será enviado em instantes",
            "endereco_entrega": final_address,
            "instrucoes": instrucoes,
        }, ensure_ascii=False)

    async def _handle_create_payment_charge(self, arguments: dict[str, Any]) -> str:
        args = dict(arguments)
        args.setdefault("momento_pagamento", "antecipado")
        args.setdefault("forma_pagamento", "pix")
        args["_is_charge_only"] = True
        return await self._handle_create_delivery_order(args)
