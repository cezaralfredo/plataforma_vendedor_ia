import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.product import Product
from app.services.ai.providers.base import ToolDefinition
from app.services.ai.subagents.base import BaseSubagent
from app.services.product_service import ProductService

logger = logging.getLogger(__name__)


class CatalogSubagent(BaseSubagent):
    """
    Subagente especialista em catálogo, estoque e especificações de produtos.
    Fornece aos modelos informações precisas sobre preços, estoque, peso (weight_kg)
    e envio de fotos dos produtos no chat do WhatsApp.
    """

    def __init__(
        self,
        db: Session,
        product_service: ProductService | None = None,
        user: Any = None,
        gateway: Any = None,
    ):
        self.db = db
        self.product_service = product_service or ProductService(db)
        self.user = user
        self.gateway = gateway

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="consultar_catalogo",
                description=(
                    "Consulta os produtos disponíveis na loja para venda com seus preços, categorias/tamanhos "
                    "(ex: Pequeno, Médio, Grande, Filé), pesos e saldo de estoque. Permite filtrar por busca de texto ou categoria."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "termo_busca": {
                            "type": "string",
                            "description": "Termo de busca, nome ou tamanho/corte (ex: 'camarão', 'filé', 'grande', 'médio', 'pequeno', 'tilápia') desejado.",
                        },
                        "categoria": {
                            "type": "string",
                            "description": "Categoria, corte ou tamanho específico do produto (ex: 'Filé', 'Grande', 'Médio', 'Pequeno', 'Tilápia').",
                        },
                    },
                },
            ),
            ToolDefinition(
                name="obter_detalhes_produto",
                description="Obtém detalhes completos de um produto específico através do seu ID.",
                parameters={
                    "type": "object",
                    "properties": {
                        "produto_id": {
                            "type": "integer",
                            "description": "ID numérico do produto.",
                        },
                    },
                    "required": ["produto_id"],
                },
            ),
            ToolDefinition(
                name="enviar_foto_produto",
                description="Envia a foto oficial de um produto diretamente para o WhatsApp do cliente para que ele possa visualizar o item.",
                parameters={
                    "type": "object",
                    "properties": {
                        "produto_id": {
                            "type": "integer",
                            "description": "ID numérico do produto cuja foto será enviada.",
                        },
                        "legenda": {
                            "type": "string",
                            "description": "Legenda opcional para acompanhar a imagem (ex: nome e valor).",
                        },
                    },
                    "required": ["produto_id"],
                },
            ),
        ]

    def _format_product(self, p: Product) -> dict[str, Any]:
        peso = float(p.weight_kg) if p.weight_kg is not None else None
        categoria = (p.category or "").strip()
        nome_completo = f"{p.name} ({categoria})" if categoria else p.name
        descricao_efetiva = (p.description or "").strip()
        if not descricao_efetiva and categoria:
            descricao_efetiva = f"{p.name} tamanho/corte '{categoria}'"
        return {
            "id": p.id,
            "nome": p.name,
            "categoria": categoria,
            "tipo_ou_tamanho": categoria,
            "nome_completo": nome_completo,
            "preco_reais": f"R$ {p.price_cents / 100:.2f}",
            "preco_centavos": p.price_cents,
            "peso_kg": round(peso, 3) if peso is not None else None,
            "estoque": p.stock_quantity,
            "sku": p.sku or "",
            "descricao": descricao_efetiva,
            "foto_url": p.image_url,
            "possui_foto": bool(p.image_url),
        }

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name == "consultar_catalogo":
            termo = (arguments.get("termo_busca") or "").strip().lower()
            categoria_arg = (arguments.get("categoria") or "").strip().lower()
            products = self.product_service.list_products(active_only=True, in_stock_only=True)

            if categoria_arg:
                products = [p for p in products if p.category and categoria_arg in p.category.lower()]

            if termo:
                products = [
                    p for p in products
                    if termo in p.name.lower()
                    or (p.category and termo in p.category.lower())
                    or (p.description and termo in p.description.lower())
                ]

            if not products:
                return json.dumps({"status": "vazio", "mensagem": "Nenhum produto encontrado com os critérios informados."}, ensure_ascii=False)

            formatted = [self._format_product(p) for p in products]
            return json.dumps({
                "status": "sucesso",
                "total": len(formatted),
                "produtos": formatted,
                "nota_para_o_agente": (
                    "REGRA FUNDAMENTAL: Quando produtos tiverem o mesmo nome (ex: Camarão), "
                    "a diferença de preço entre eles decorre estritamente da categoria/tamanho/corte "
                    "(campo 'categoria', como Pequeno, Médio, Grande, Filé). "
                    "Apresente sempre o item com seu respectivo tamanho/corte (ex: 'Camarão Pequeno: R$ 15,00', 'Camarão Filé: R$ 65,00') "
                    "e explique a variação de preço com base no tamanho e no tipo de corte/limpeza, nunca inventando qualidades subjetivas."
                ),
            }, ensure_ascii=False)

        elif tool_name == "obter_detalhes_produto":
            prod_id = arguments.get("produto_id")
            if not prod_id:
                return json.dumps({"erro": "produto_id é obrigatório"}, ensure_ascii=False)

            p = self.product_service.get_product(int(prod_id))
            if not p or not p.active:
                return json.dumps({"erro": f"Produto #{prod_id} não encontrado ou inativo"}, ensure_ascii=False)

            return json.dumps({"status": "sucesso", "produto": self._format_product(p)}, ensure_ascii=False)

        elif tool_name == "enviar_foto_produto":
            prod_id = arguments.get("produto_id")
            if not prod_id:
                return json.dumps({"erro": "produto_id é obrigatório"}, ensure_ascii=False)

            p = self.product_service.get_product(int(prod_id))
            if not p or not p.active:
                return json.dumps({"erro": f"Produto #{prod_id} não encontrado."}, ensure_ascii=False)

            if not p.image_url:
                return json.dumps({
                    "status": "sem_foto",
                    "produto_id": p.id,
                    "produto_nome": p.name,
                    "preco_formatado": f"R$ {p.price_cents / 100:.2f}",
                    "descricao": p.description or "",
                    "categoria": p.category or "",
                    "instrucoes": (
                        f"O produto '{p.name}' não possui imagem cadastrada no catálogo. "
                        "Explique gentilmente ao cliente as características, qualidade e valor do item."
                    ),
                    "mensagem": f"O produto '{p.name}' não possui imagem cadastrada no momento.",
                }, ensure_ascii=False)

            legenda = arguments.get("legenda") or f"📸 {p.name}\n💰 R$ {p.price_cents / 100:.2f}"
            sent = False
            phone = getattr(self.user, "whatsapp_number", None) or getattr(self.user, "phone", None)

            if self.gateway and phone:
                try:
                    res = await self.gateway.send_image(phone, p.image_url, caption=legenda)
                    sent = getattr(res, "success", False)
                except Exception as e:
                    logger.warning("Falha ao enviar imagem do produto via gateway: %s", e)

            return json.dumps({
                "status": "sucesso",
                "produto_nome": p.name,
                "foto_url": p.image_url,
                "foto_enviada": sent,
                "mensagem": f"Foto de '{p.name}' despachada para o WhatsApp do cliente.",
            }, ensure_ascii=False)

        return json.dumps({"erro": f"Ferramenta desconhecida no CatalogSubagent: {tool_name}"}, ensure_ascii=False)
