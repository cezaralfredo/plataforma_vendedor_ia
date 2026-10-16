import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.branch import BranchCreate, BranchUpdate
from app.schemas.seller import SellerCreate, SellerUpdate
from app.services.branch_service import BranchService
from app.services.payment_service import PaymentService
from app.services.seller_service import SellerService
from tests.test_admin_login_flow import login, session_data

# -----------------------------------------------------------------------------
# 1. BranchService Tests
# -----------------------------------------------------------------------------

def test_branch_service_crud(db_session: Session):
    service = BranchService(db_session)

    # Criação
    create_dto = BranchCreate(
        name="Filial Matriz São Paulo",
        code="SP-01",
        cnpj="12.345.678/0001-90",
        phone="11999990001",
        whatsapp_number="5511999990001",
        address="Av. Paulista, 1000",
        city="São Paulo",
        state="SP",
        active=True,
    )
    branch = service.create(create_dto)
    assert branch.id is not None
    assert branch.code == "SP-01"
    assert branch.name == "Filial Matriz São Paulo"
    assert branch.sellers_count == 0

    # Duplicidade de código
    with pytest.raises(ValueError, match="Já existe uma filial cadastrada"):
        service.create(create_dto)

    # Busca
    fetched = service.get_by_id(branch.id)
    assert fetched is not None
    assert fetched.code == "SP-01"

    fetched_code = service.get_by_code("sp-01")
    assert fetched_code is not None
    assert fetched_code.id == branch.id

    # Listagem
    all_branches = service.list_branches()
    assert len(all_branches) == 1

    # Atualização
    updated = service.update(branch.id, BranchUpdate(name="Filial Paulista Central"))
    assert updated is not None
    assert updated.name == "Filial Paulista Central"

    # Deleção
    deleted = service.delete(branch.id)
    assert deleted is True
    assert service.get_by_id(branch.id) is None


# -----------------------------------------------------------------------------
# 2. SellerService & Authentication Tests
# -----------------------------------------------------------------------------

def test_seller_service_lifecycle_and_auth(db_session: Session):
    branch_service = BranchService(db_session)
    branch = branch_service.create(
        BranchCreate(name="Filial Rio de Janeiro", code="RJ-01", city="Rio de Janeiro", state="RJ")
    )

    seller_service = SellerService(db_session)

    # Criação de vendedor
    seller_dto = SellerCreate(
        branch_id=branch.id,
        name="Carlos Vendedor",
        email="carlos@vendas.com",
        password="senhaSegura123",
        phone="21988880001",
        whatsapp_number="5521988880001",
        code="VEND-01",
        commission_rate=7.5,
        pix_key="carlos@pix.com",
        active=True,
    )
    seller = seller_service.create(seller_dto)
    assert seller.id is not None
    assert seller.branch_id == branch.id
    assert seller.branch_name == "Filial Rio de Janeiro"
    assert seller.password_hash != "senhaSegura123"

    # Recusar filial inexistente
    with pytest.raises(ValueError, match="Filial com ID 9999"):
        seller_service.create(
            SellerCreate(
                branch_id=9999,
                name="Invalido",
                email="invalido@vendas.com",
                password="senhaValida123",
                whatsapp_number="5521900000000",
                code="INV-01",
            )
        )

    # Recusar duplicidade de email
    with pytest.raises(ValueError, match="já está em uso"):
        seller_service.create(
            SellerCreate(
                branch_id=branch.id,
                name="Outro",
                email="carlos@vendas.com",
                password="senhaValida123",
                whatsapp_number="5521900000000",
                code="OUTRO-01",
            )
        )

    # Recusar duplicidade de código
    with pytest.raises(ValueError, match="já está cadastrado"):
        seller_service.create(
            SellerCreate(
                branch_id=branch.id,
                name="Outro",
                email="outro@vendas.com",
                password="senhaValida123",
                whatsapp_number="5521900000000",
                code="VEND-01",
            )
        )

    # Autenticação correta
    authenticated = seller_service.authenticate("carlos@vendas.com", "senhaSegura123")
    assert authenticated is not None
    assert authenticated.id == seller.id
    assert authenticated.last_login_at is not None

    # Autenticação senha errada
    assert seller_service.authenticate("carlos@vendas.com", "senhaIncorreta") is None
    # Autenticação email errado
    assert seller_service.authenticate("inexistente@vendas.com", "senhaSegura123") is None

    # Vendedor inativo não autentica
    seller_service.update(seller.id, SellerUpdate(active=False))
    assert seller_service.authenticate("carlos@vendas.com", "senhaSegura123") is None


# -----------------------------------------------------------------------------
# 3. Payment Commission Attribution Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_payment_attribution_and_commission_calculation(db_session: Session):
    from app.services.company_settings_service import CompanySettingsService
    company_settings = CompanySettingsService(db_session).get_or_create_default()
    company_settings.default_gateway = "pix_direto"
    company_settings.gateway_credentials = {
        "pix_key": "12345678000199",
        "merchant_name": "Minha Empresa",
        "merchant_city": "Sao Paulo",
    }
    db_session.commit()

    branch_service = BranchService(db_session)
    branch = branch_service.create(
        BranchCreate(name="Filial BH", code="BH-01", city="Belo Horizonte", state="MG")
    )

    seller_service = SellerService(db_session)
    seller = seller_service.create(
        SellerCreate(
            branch_id=branch.id,
            name="Mariana Vendedora",
            email="mariana@vendas.com",
            password="senhaSegura123",
            whatsapp_number="5531988880002",
            code="VEND-BH-01",
            commission_rate=10.0,  # 10% de comissão
            pix_key="mariana@pix.com",
        )
    )

    # Cliente
    user = User(name="Cliente Comprador", phone="5531977770001", active=True)
    db_session.add(user)
    db_session.commit()

    payment_service = PaymentService(db_session)

    # Cria cobrança direta (ex: R$ 150,00 = 15000 centavos) com seller_id
    payment = await payment_service.create_direct_charge(
        user_id=user.id,
        amount_cents=15000,
        description="Venda com comissão",
        seller_id=seller.id,
    )

    assert payment.seller_id == seller.id
    assert payment.branch_id == branch.id
    # 10% de 15000 = 1500 centavos (R$ 15,00)
    assert payment.commission_amount_cents == 1500

    # Simula pagamento recebido
    payment.status = "received"
    db_session.commit()

    # Verifica métricas do vendedor
    metrics = seller_service.get_metrics(seller.id)
    assert metrics.seller_id == seller.id
    assert metrics.seller_name == "Mariana Vendedora"
    assert metrics.branch_name == "Filial BH"
    assert metrics.total_orders_count == 1
    assert metrics.total_sales_cents == 15000
    assert metrics.paid_commission_cents == 1500
    assert metrics.pending_commission_cents == 0
    assert metrics.total_commission_cents == 1500


# -----------------------------------------------------------------------------
# 4. Seller Portal Web & API Tests (/seller/...)
# -----------------------------------------------------------------------------

def test_seller_portal_endpoints(client: TestClient, db_session: Session):
    branch_service = BranchService(db_session)
    branch = branch_service.create(
        BranchCreate(name="Filial Curitiba", code="PR-01", city="Curitiba", state="PR")
    )

    seller_service = SellerService(db_session)
    seller = seller_service.create(
        SellerCreate(
            branch_id=branch.id,
            name="Roberto Vendas",
            email="roberto@vendas.com",
            password="portalPassword123",
            whatsapp_number="5541999990003",
            code="VEND-PR-01",
            commission_rate=5.0,
        )
    )

    # 1. Acesso à página de login
    res_login_page = client.get("/seller/login")
    assert res_login_page.status_code == 200
    assert "Vendedor" in res_login_page.text

    # 2. Tentar acessar dashboard sem estar autenticado -> redireciona para login
    res_dash_no_auth = client.get("/seller/dashboard", follow_redirects=False)
    assert res_dash_no_auth.status_code in {302, 303, 307}
    assert "/seller/login" in res_dash_no_auth.headers.get("location", "")

    # 3. Login com senha errada -> 401
    res_bad_login = client.post(
        "/seller/login",
        data={"email": "roberto@vendas.com", "password": "senhaErrada"},
        follow_redirects=False,
    )
    assert res_bad_login.status_code == 401
    assert "incorretos" in res_bad_login.text

    # 4. Login correto -> 303 redireciona para /seller/dashboard e define cookie vendedor_session
    res_good_login = client.post(
        "/seller/login",
        data={"email": "roberto@vendas.com", "password": "portalPassword123"},
        follow_redirects=False,
    )
    assert res_good_login.status_code == 303
    assert res_good_login.headers.get("location") == "/seller/dashboard"
    assert "vendedor_session" in client.cookies

    # 5. Acesso ao dashboard autenticado
    res_dash = client.get("/seller/dashboard")
    assert res_dash.status_code == 200
    assert "Roberto Vendas" in res_dash.text
    assert "Filial Curitiba" in res_dash.text
    assert "Meus Pedidos Recentes" in res_dash.text


    # 6. Acesso à API de métricas autenticado
    res_metrics = client.get("/seller/api/metrics")
    assert res_metrics.status_code == 200
    data = res_metrics.json()
    assert data["seller_id"] == seller.id
    assert data["seller_name"] == "Roberto Vendas"
    assert data["branch_name"] == "Filial Curitiba"

    # 7. Logout do vendedor
    res_logout = client.post("/seller/logout", follow_redirects=False)
    assert res_logout.status_code == 303
    assert res_logout.headers.get("location") == "/seller/login"


# -----------------------------------------------------------------------------
# 5. Admin API Management for Branches & Sellers (/admin/api/...)
# -----------------------------------------------------------------------------

def test_admin_branches_and_sellers_api(client: TestClient, db_session: Session):
    login(client)
    csrf_token = session_data(client)["csrf_token"]
    headers = {"x-csrf-token": csrf_token}

    # 1. Admin cria filial via API
    res_branch = client.post(
        "/admin/api/branches",
        json={
            "name": "Filial Porto Alegre",
            "code": "RS-01",
            "city": "Porto Alegre",
            "state": "RS",
            "whatsapp_number": "5551999990001",
        },
        headers=headers,
    )
    assert res_branch.status_code == 200
    branch_data = res_branch.json()
    assert branch_data["id"] is not None
    assert branch_data["code"] == "RS-01"
    branch_id = branch_data["id"]

    # 2. Admin lista filiais
    res_branches = client.get("/admin/api/branches")
    assert res_branches.status_code == 200
    branches_list = res_branches.json()
    assert any(b["code"] == "RS-01" for b in branches_list)

    # 3. Admin cria vendedor vinculado à filial
    res_seller = client.post(
        "/admin/api/sellers",
        json={
            "branch_id": branch_id,
            "name": "Lucas Vendedor Sul",
            "email": "lucas@vendas.com",
            "password": "senhaSegura456",
            "whatsapp_number": "5551988880002",
            "code": "VEND-RS-01",
            "commission_rate": 8.0,
            "pix_key": "lucas@pix.com",
        },
        headers=headers,
    )
    assert res_seller.status_code == 200
    seller_data = res_seller.json()
    assert seller_data["id"] is not None
    assert seller_data["branch_id"] == branch_id
    seller_id = seller_data["id"]

    # 4. Admin lista vendedores por filial
    res_sellers = client.get(f"/admin/api/sellers?branch_id={branch_id}")
    assert res_sellers.status_code == 200
    sellers_list = res_sellers.json()
    assert len(sellers_list) == 1
    assert sellers_list[0]["name"] == "Lucas Vendedor Sul"

    # 5. Admin consulta métricas do vendedor
    res_seller_metrics = client.get(f"/admin/api/sellers/{seller_id}/metrics")
    assert res_seller_metrics.status_code == 200
    metrics_data = res_seller_metrics.json()
    assert metrics_data["seller_name"] == "Lucas Vendedor Sul"
    assert metrics_data["branch_name"] == "Filial Porto Alegre"

    # 6. Admin atualiza taxa de comissão do vendedor
    res_update_seller = client.put(
        f"/admin/api/sellers/{seller_id}",
        json={"commission_rate": 12.0},
        headers=headers,
    )
    assert res_update_seller.status_code == 200
    assert float(res_update_seller.json()["commission_rate"]) == 12.0

    # 7. Admin deleta vendedor
    res_del_seller = client.delete(f"/admin/api/sellers/{seller_id}", headers=headers)
    assert res_del_seller.status_code == 200

    # 8. Admin deleta filial
    res_del_branch = client.delete(f"/admin/api/branches/{branch_id}", headers=headers)
    assert res_del_branch.status_code == 200
