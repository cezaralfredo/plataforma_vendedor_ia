from starlette.testclient import TestClient

from app.models.branch import Branch
from app.models.seller import Seller
from app.models.user import User


def _admin_headers() -> dict[str, str]:
    from app.config import settings
    return {"X-Admin-Key": settings.admin_api_key}


def test_logistics_page_and_apis(anonymous_client: TestClient, db_session):
    client = anonymous_client

    # 1. Page renders
    resp = client.get("/admin/logistics", headers=_admin_headers())
    assert resp.status_code == 200
    assert "Logística & Entregas" in resp.text
    assert "Avisar: Produto a Caminho" in resp.text

    # 2. Criar cliente para entrega
    user = User(
        name="Cliente Logística Teste",
        phone="5585999887766",
        whatsapp_number="5585999887766",
        address="Av. Santos Dumont, 1000",
        address_number="1000",
        neighborhood="Aldeota",
        city="Fortaleza",
        state="CE",
        postal_code="60150-160",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    # 3. Criar loja e vendedor
    branch = Branch(
        name="Loja Logística Sul",
        code="LOGSUL",
        phone="558533334444",
        whatsapp_number="5585988887777",
        city="Fortaleza",
        state="CE",
    )
    db_session.add(branch)
    db_session.commit()
    db_session.refresh(branch)

    seller = Seller(
        name="Vendedor Entregas",
        email="vendedor.entrega@loja.com",
        password_hash="hash123",
        phone="5585977776666",
        whatsapp_number="5585977776666",
        code="VENT01",
        branch_id=branch.id,
    )
    db_session.add(seller)
    db_session.commit()
    db_session.refresh(seller)

    # 4. Criar entrega via API
    payload = {
        "user_id": user.id,
        "branch_id": branch.id,
        "seller_id": seller.id,
        "items_description": "1x Sofá Retrátil 3 Lugares Veludo Cinza",
        "total_amount_cents": 189900,
        "payment_method": "pix",
        "payment_timing": "na_entrega",
        "payment_status": "pendente",
        "delivery_status": "preparando",
        "delivery_address": user.full_address,
        "delivery_driver_name": "Carlos Motoboy",
    }
    create_resp = client.post("/admin/api/deliveries", json=payload, headers=_admin_headers())
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["id"] > 0
    assert created["order_code"].startswith("ENT-")
    assert created["payment_timing"] == "na_entrega"
    assert created["delivery_status"] == "preparando"

    delivery_id = created["id"]

    # 5. Listar entregas
    list_resp = client.get("/admin/api/deliveries", headers=_admin_headers())
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert any(d["id"] == delivery_id for d in items)

    # 6. Consultar KPIs
    kpis_resp = client.get("/admin/api/deliveries/kpis", headers=_admin_headers())
    assert kpis_resp.status_code == 200
    kpis = kpis_resp.json()
    assert kpis["total_deliveries"] >= 1
    assert kpis["to_collect_cents"] >= 189900

    # 7. Disparar notificação de WhatsApp "Produto a Caminho"
    notify_resp = client.post(
        f"/admin/api/deliveries/{delivery_id}/notify",
        json={"custom_message": None},
        headers=_admin_headers(),
    )
    assert notify_resp.status_code == 200
    notify_data = notify_resp.json()
    assert notify_data["success"] is True
    assert notify_data["dispatched"] is True
    assert "https://wa.me/" in notify_data["whatsapp_direct_url"]
    assert "a caminho" in notify_data["message"].lower()
    assert notify_data["delivery"]["delivery_status"] == "a_caminho"

    # 8. Marcar como entregue
    patch_resp = client.patch(
        f"/admin/api/deliveries/{delivery_id}/status",
        json={"delivery_status": "entregue", "payment_status": "pago"},
        headers=_admin_headers(),
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["delivery_status"] == "entregue"
    assert updated["payment_status"] == "pago"
    assert updated["delivered_at"] is not None
