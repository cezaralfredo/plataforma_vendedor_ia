from app.config import settings
from app.models.branch import Branch


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": settings.admin_api_key}


def test_admin_stores_and_sellers_pages_render(anonymous_client):
    stores_resp = anonymous_client.get("/admin/stores", headers=_admin_headers())
    assert stores_resp.status_code == 200
    assert "Gestão de Lojas & Filiais" in stores_resp.text
    assert 'href="/admin/sellers"' in stores_resp.text

    sellers_resp = anonymous_client.get("/admin/sellers", headers=_admin_headers())
    assert sellers_resp.status_code == 200
    assert "Gestão de Vendedores & Lojas" in sellers_resp.text
    assert 'href="/admin/stores"' in sellers_resp.text


def test_branch_lifecycle_and_validation(anonymous_client, db_session):
    # Criar loja
    create_resp = anonymous_client.post(
        "/admin/api/branches",
        headers=_admin_headers(),
        json={
            "name": "Loja Matriz SP",
            "code": "SP01",
            "whatsapp_number": "11999990001",
            "address": "Av. Paulista",
            "address_number": "1500",
            "neighborhood": "Bela Vista",
            "city": "São Paulo",
            "state": "SP",
            "postal_code": "01310-200",
            "email": "matriz@anauedesign.com.br",
        },
    )
    assert create_resp.status_code == 200
    branch_data = create_resp.json()
    assert branch_data["code"] == "SP01"
    assert branch_data["name"] == "Loja Matriz SP"
    branch_id = branch_data["id"]

    # Código duplicado rejeitado
    dup_resp = anonymous_client.post(
        "/admin/api/branches",
        headers=_admin_headers(),
        json={
            "name": "Outra Loja",
            "code": "SP01",
        },
    )
    assert dup_resp.status_code == 400

    # Listar lojas
    list_resp = anonymous_client.get("/admin/api/branches", headers=_admin_headers())
    assert list_resp.status_code == 200
    assert any(b["id"] == branch_id for b in list_resp.json())

    # Atualizar loja
    update_resp = anonymous_client.put(
        f"/admin/api/branches/{branch_id}",
        headers=_admin_headers(),
        json={"name": "Loja Matriz São Paulo Centro"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Loja Matriz São Paulo Centro"


def test_seller_lifecycle_and_branch_association(anonymous_client, db_session):
    # Cria filial para teste
    branch = Branch(
        name="Loja Santos Centro",
        code="SAN01",
        city="Santos",
        state="SP",
        address="Rua do Comércio, 10",
    )
    db_session.add(branch)
    db_session.commit()
    db_session.refresh(branch)

    # Cadastrar vendedor vinculado à filial
    seller_resp = anonymous_client.post(
        "/admin/api/sellers",
        headers=_admin_headers(),
        json={
            "branch_id": branch.id,
            "name": "Lucas Vendedor Santos",
            "email": "lucas.santos@anauedesign.com.br",
            "password": "senha_segura_123",
            "whatsapp_number": "13988887777",
            "code": "VEND-SAN01",
            "commission_rate": 7.5,
            "pix_key": "lucas.santos@anauedesign.com.br",
        },
    )
    assert seller_resp.status_code == 200
    seller_data = seller_resp.json()
    assert seller_data["name"] == "Lucas Vendedor Santos"
    assert seller_data["branch_id"] == branch.id
    assert seller_data["branch_name"] == "Loja Santos Centro"
    assert seller_data["commission_rate"] == 7.5
    seller_id = seller_data["id"]

    # Tentativa de cadastrar com loja inexistente falha
    inv_branch_resp = anonymous_client.post(
        "/admin/api/sellers",
        headers=_admin_headers(),
        json={
            "branch_id": 999999,
            "name": "Vendedor Fantasma",
            "email": "fantasma@teste.com",
            "password": "senha_fantasma",
            "whatsapp_number": "11999998888",
            "code": "VEND-GHOST",
        },
    )
    assert inv_branch_resp.status_code == 400

    # Listar vendedores filtrando por branch_id
    list_resp = anonymous_client.get(
        f"/admin/api/sellers?branch_id={branch.id}",
        headers=_admin_headers(),
    )
    assert list_resp.status_code == 200
    sellers = list_resp.json()
    assert len(sellers) >= 1
    assert any(s["id"] == seller_id for s in sellers)

    # Busca textual por vendedor
    search_resp = anonymous_client.get(
        "/admin/api/sellers?search=Lucas",
        headers=_admin_headers(),
    )
    assert search_resp.status_code == 200
    assert any(s["id"] == seller_id for s in search_resp.json())

    # Métricas do vendedor
    metrics_resp = anonymous_client.get(
        f"/admin/api/sellers/{seller_id}/metrics",
        headers=_admin_headers(),
    )
    assert metrics_resp.status_code == 200
    metrics = metrics_resp.json()
    assert metrics["seller_id"] == seller_id
    assert metrics["seller_name"] == "Lucas Vendedor Santos"
    assert metrics["branch_name"] == "Loja Santos Centro"
    assert "total_sales_cents" in metrics
    assert "total_commission_cents" in metrics
