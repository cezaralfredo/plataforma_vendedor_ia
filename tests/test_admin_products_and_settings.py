import io
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.company_settings import CompanySettings
from app.models.product import Product
from tests.test_admin_login_flow import login, session_data


def test_products_and_settings_require_admin_authentication(client: TestClient):
    # GET /admin/products sem login
    res_prod = client.get("/admin/products", follow_redirects=False)
    assert res_prod.status_code in {303, 307, 401, 403}

    # GET /admin/settings sem login
    res_sett = client.get("/admin/settings", follow_redirects=False)
    assert res_sett.status_code in {303, 307, 401, 403}


def test_admin_products_page_renders_with_sidebar_and_data(
    client: TestClient, db_session: Session
):
    login(client)

    # Cria um produto no banco
    product = Product(
        name="Shampoo Hidratante Premium",
        description="Fórmula exclusiva",
        category="Cabelo",
        price_cents=4500,
        stock_quantity=10,
        active=True,
    )
    db_session.add(product)
    db_session.commit()

    res = client.get("/admin/products")
    assert res.status_code == 200
    assert "Catálogo de Produtos" in res.text
    assert "Shampoo Hidratante Premium" in res.text
    assert "href=\"/admin/products\"" in res.text
    assert "href=\"/admin/settings\"" in res.text


def test_admin_settings_page_renders_with_tabs(
    client: TestClient, db_session: Session
):
    login(client)

    res = client.get("/admin/settings")
    assert res.status_code == 200
    assert "Configurações da Empresa" in res.text
    assert "Financeiro & Pagamentos" in res.text
    assert "Atendimento & IA" in res.text
    assert "Canais WhatsApp" in res.text
    assert "Comissões" in res.text


def test_admin_product_mutations_require_csrf_protection(
    client: TestClient, db_session: Session
):
    login(client)

    # Tentativa de criar produto sem cabeçalho X-CSRF-Token deve ser rejeitada com 403
    res = client.post(
        "/admin/api/products",
        json={"name": "Produto Hacker", "price_cents": 1000, "stock_quantity": 5},
    )
    assert res.status_code == 403

    # Tentativa de alterar settings sem cabeçalho X-CSRF-Token deve ser rejeitada com 403
    res_sett = client.post(
        "/admin/api/settings",
        json={"company_name": "Empresa Invadida"},
    )
    assert res_sett.status_code == 403


def test_admin_product_lifecycle_with_valid_csrf(
    client: TestClient, db_session: Session
):
    login(client)
    csrf = session_data(client)["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    # 1. Criar produto
    create_payload = {
        "name": "Pomada Modeladora Matte",
        "description": "Fixação média",
        "category": "Cabelo",
        "price_cents": 5000,
        "stock_quantity": 20,
        "sku": "POM-001",
    }
    res_create = client.post(
        "/admin/api/products",
        headers=headers,
        json=create_payload,
    )
    assert res_create.status_code == 200
    created_id = res_create.json()["id"]
    assert created_id is not None
    assert res_create.json()["name"] == "Pomada Modeladora Matte"

    # 2. Atualizar produto
    update_payload = {"price_cents": 5500, "name": "Pomada Modeladora Matte Gold"}
    res_update = client.put(
        f"/admin/api/products/{created_id}",
        headers=headers,
        json=update_payload,
    )
    assert res_update.status_code == 200
    assert res_update.json()["price_cents"] == 5500
    assert res_update.json()["name"] == "Pomada Modeladora Matte Gold"

    # 3. Ajustar estoque (+5)
    res_stock = client.post(
        f"/admin/api/products/{created_id}/stock",
        headers=headers,
        json={"quantity_delta": 5},
    )
    assert res_stock.status_code == 200
    assert res_stock.json()["stock_quantity"] == 25

    # 4. Alternar status ativo/arquivado
    res_toggle = client.post(
        f"/admin/api/products/{created_id}/toggle-active",
        headers=headers,
    )
    assert res_toggle.status_code == 200
    assert res_toggle.json()["active"] is False


def test_admin_settings_update_persists_in_database(
    client: TestClient, db_session: Session
):
    login(client)
    csrf = session_data(client)["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    update_payload = {
        "company_name": "Studio & Barbearia Elite",
        "assistant_name": "Helena",
        "tone": "formal",
        "require_cpf": True,
        "payment_required": False,
        "default_gateway": "direct_pix",
        "pix_key": "12.345.678/0001-90",
        "pix_key_type": "cnpj",
        "pix_merchant_name": "Studio & Barbearia Elite",
        "pix_merchant_city": "Fortaleza",
        "pix_bank_name": "Banco Inter",
        "pix_copy_paste": "00020126580014br.gov.bcb.pix0136...",
        "accepted_payment_methods": ["pix", "credit_card", "in_person"],
        "whatsapp_provider": "meta",
        "meta_phone_number_id": "9988776655",
        "commission_model": "percentage",
        "default_commission_rate": 35.5,
    }

    res = client.post(
        "/admin/api/settings",
        headers=headers,
        json=update_payload,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["company_name"] == "Studio & Barbearia Elite"
    assert data["assistant_name"] == "Helena"
    assert data["payment_required"] is False
    assert data["default_gateway"] == "direct_pix"
    assert data["pix_key"] == "12.345.678/0001-90"
    assert data["pix_merchant_name"] == "Studio & Barbearia Elite"
    assert data["pix_merchant_city"] == "Fortaleza"
    assert data["pix_bank_name"] == "Banco Inter"
    assert data["pix_copy_paste"] == "00020126580014br.gov.bcb.pix0136..."
    assert data["accepted_payment_methods"] == ["pix", "credit_card", "in_person"]
    assert data["whatsapp_provider"] == "meta"

    # Verifica persistência real no banco
    db_setting = db_session.query(CompanySettings).first()
    assert db_setting.company_name == "Studio & Barbearia Elite"
    assert db_setting.payment_required is False
    assert db_setting.default_gateway == "direct_pix"
    assert db_setting.pix_key == "12.345.678/0001-90"
    assert db_setting.pix_merchant_name == "Studio & Barbearia Elite"
    assert db_setting.pix_merchant_city == "Fortaleza"
    assert db_setting.pix_bank_name == "Banco Inter"
    assert db_setting.pix_copy_paste == "00020126580014br.gov.bcb.pix0136..."
    assert db_setting.accepted_payment_methods == ["pix", "credit_card", "in_person"]


def test_admin_product_image_upload_validations_and_lifecycle(
    client: TestClient, db_session: Session
):
    login(client)
    csrf = session_data(client)["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    # 1. Sem CSRF -> 403
    dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa76S\x9c\x00\x00\x00\x00IEND\xaeB`\x82"
    res_no_csrf = client.post(
        "/admin/api/products/upload-image",
        files={"file": ("test.png", io.BytesIO(dummy_png), "image/png")},
    )
    assert res_no_csrf.status_code == 403

    # 2. Extensão inválida -> 400
    res_invalid_ext = client.post(
        "/admin/api/products/upload-image",
        headers=headers,
        files={"file": ("test.txt", io.BytesIO(b"not an image"), "text/plain")},
    )
    assert res_invalid_ext.status_code == 400
    assert "Formato de imagem inválido" in res_invalid_ext.json()["detail"]

    # 3. Arquivo vazio -> 400
    res_empty = client.post(
        "/admin/api/products/upload-image",
        headers=headers,
        files={"file": ("empty.png", io.BytesIO(b""), "image/png")},
    )
    assert res_empty.status_code == 400

    # 4. Upload com sucesso -> 200
    res_upload = client.post(
        "/admin/api/products/upload-image",
        headers=headers,
        files={"file": ("produto_foto.png", io.BytesIO(dummy_png), "image/png")},
    )
    assert res_upload.status_code == 200
    upload_data = res_upload.json()
    image_url = upload_data["url"]
    filename = upload_data["filename"]
    assert image_url.startswith("/admin/static/uploads/products/")
    assert filename.endswith(".png")

    # Verifica que o arquivo foi gravado no disco
    saved_file = Path("app/admin/static/uploads/products") / filename
    assert saved_file.exists()
    assert saved_file.read_bytes() == dummy_png

    # 5. Criar produto vinculando a imagem enviada
    create_payload = {
        "name": "Óleo para Barba Premium",
        "description": "Com óleo de argan e jojoba",
        "category": "Barba",
        "price_cents": 3990,
        "stock_quantity": 15,
        "sku": "OLEO-BARBA-01",
        "image_url": image_url,
    }
    res_create = client.post(
        "/admin/api/products",
        headers=headers,
        json=create_payload,
    )
    assert res_create.status_code == 200
    prod_data = res_create.json()
    assert prod_data["image_url"] == image_url

    # 6. Página de produtos renderiza a URL da foto no dataset e na página
    res_page = client.get("/admin/products")
    assert res_page.status_code == 200
    assert image_url in res_page.text
    assert "Carregar imagem do PC" in res_page.text

    # Limpeza do arquivo de teste
    saved_file.unlink(missing_ok=True)
