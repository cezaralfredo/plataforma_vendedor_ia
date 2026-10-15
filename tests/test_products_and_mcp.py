import pytest
from sqlalchemy.orm import Session

from app.mcp.tools import handle_tool_call
from app.schemas.product import ProductCreate
from app.services.product_service import ProductService


def test_product_crud_and_stock(db_session: Session):
    service = ProductService(db_session)

    # 1. Criação de produtos
    p1 = service.create(
        ProductCreate(
            name="Pomada Modeladora Efeito Matte",
            description="Fixação forte e acabamento natural sem brilho",
            category="Cabelo",
            price_cents=4500,
            stock_quantity=15,
            sku="POM-001",
        )
    )

    service.create(
        ProductCreate(
            name="Óleo Hidratante de Barba",
            description="Óleo essencial com fragrância amadeirada",
            category="Barba",
            price_cents=3800,
            stock_quantity=8,
            sku="OLE-002",
        )
    )

    assert p1.id is not None
    assert p1.price_cents == 4500

    # 2. Listagem por categoria
    cabelo_items = service.list_products(category="Cabelo")
    assert len(cabelo_items) == 1
    assert cabelo_items[0].name == "Pomada Modeladora Efeito Matte"

    # 3. Listagem de categorias únicas
    categories = service.list_categories()
    assert "Cabelo" in categories
    assert "Barba" in categories

    # 4. Busca textual
    matches = service.list_products(search="hidratante")
    assert len(matches) == 1
    assert matches[0].sku == "OLE-002"

    # 5. Ajuste de estoque
    updated_p1 = service.adjust_stock(p1.id, -3)
    assert updated_p1.stock_quantity == 12

    # 6. Erro de estoque insuficiente
    with pytest.raises(ValueError, match="Estoque insuficiente"):
        service.adjust_stock(p1.id, -20)


@pytest.mark.asyncio
async def test_mcp_product_tools(db_session: Session):
    service = ProductService(db_session)
    service.create(
        ProductCreate(
            name="Shampoo Anticaspa Professional",
            description="Controle de oleosidade e caspa",
            category="Cuidados",
            price_cents=5500,
            stock_quantity=10,
        )
    )

    # Tool: listar_produtos
    res_list = await handle_tool_call(
        "listar_produtos",
        {"category": "Cuidados"},
        db_session,
    )
    assert "isError" not in res_list
    assert "Shampoo Anticaspa Professional" in res_list["content"][0]["text"]
    assert "R$ 55,00" in res_list["content"][0]["text"]

    # Tool: consultar_produto por nome
    res_get = await handle_tool_call(
        "consultar_produto",
        {"name": "Anticaspa"},
        db_session,
    )
    assert "isError" not in res_get
    assert "10 unidades disponíveis" in res_get["content"][0]["text"]
    assert "Controle de oleosidade e caspa" in res_get["content"][0]["text"]
