from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User
from app.schemas.user import UserImportItem, UserImportRequest
from app.services.client_import_service import (
    ClientImportService,
    normalize_phone_number,
    parse_date_flexible,
    parse_tags_flexible,
)


def _api_headers() -> dict[str, str]:
    return {"X-API-Key": settings.api_key}


class TestClientImportHelpers:
    def test_normalize_phone_number_formats(self):
        assert normalize_phone_number("(85) 99999-8888") == "5585999998888"
        assert normalize_phone_number("85999998888") == "5585999998888"
        assert normalize_phone_number("085999998888") == "5585999998888"
        assert normalize_phone_number("+55 85 99999-8888") == "5585999998888"
        assert normalize_phone_number("5585999998888") == "5585999998888"
        assert normalize_phone_number("(11) 3333-4444") == "551133334444"
        # Incompleto ou inválido
        assert normalize_phone_number("99998888") is None
        assert normalize_phone_number("") is None
        assert normalize_phone_number(None) is None

    def test_parse_date_flexible(self):
        assert str(parse_date_flexible("2026-10-06")) == "2026-10-06"
        assert str(parse_date_flexible("06/10/2026")) == "2026-10-06"
        assert str(parse_date_flexible("06-10-2026")) == "2026-10-06"
        assert parse_date_flexible("invalido") is None
        assert parse_date_flexible("") is None

    def test_parse_tags_flexible(self):
        assert parse_tags_flexible("vip, cliente_antigo, sp") == ["vip", "cliente_antigo", "sp"]
        assert parse_tags_flexible(["VIP", "vip", "novo"]) == ["VIP", "novo"]
        assert parse_tags_flexible("tag1; tag2 | tag3") == ["tag1", "tag2", "tag3"]
        assert parse_tags_flexible("") == []


class TestClientImportService:
    def test_import_creates_new_clients(self, db_session: Session):
        service = ClientImportService(db_session)
        request = UserImportRequest(
            source="hubspot",
            items=[
                UserImportItem(
                    name="Carlos Silva",
                    phone="(11) 98765-4321",
                    email="carlos@example.com",
                    tags=["vip", "recorrente"],
                    city="São Paulo",
                    state="SP",
                ),
                UserImportItem(
                    name="Mariana Lima",
                    phone="21988887777",
                    notes="Cliente antiga",
                    birth_date="15/05/1990",
                ),
            ],
        )

        summary = service.import_items(request)
        assert summary.total == 2
        assert summary.created == 2
        assert summary.updated == 0
        assert summary.errors == 0
        assert summary.import_batch_id.startswith("batch_")

        carlos = db_session.query(User).filter(User.phone == "5511987654321").first()
        assert carlos is not None
        assert carlos.name == "Carlos Silva"
        assert carlos.email == "carlos@example.com"
        assert carlos.source == "hubspot"
        assert carlos.tags == ["vip", "recorrente"]
        assert carlos.city == "São Paulo"
        assert carlos.state == "SP"
        assert carlos.whatsapp_number == "5511987654321"

        mariana = db_session.query(User).filter(User.phone == "5521988887777").first()
        assert mariana is not None
        assert str(mariana.birth_date) == "1990-05-15"
        assert mariana.notes == "Cliente antiga"

    def test_import_upsert_merges_existing_client_data(self, db_session: Session):
        # Cria cliente inicial
        initial_user = User(
            name="João Santos",
            phone="5585991112222",
            email="joao@antigo.com",
            source="direct",
            tags=["antigo"],
            notes="Nota 1",
            custom_fields={"origem": "balcao"},
        )
        db_session.add(initial_user)
        db_session.commit()

        service = ClientImportService(db_session)
        request = UserImportRequest(
            source="planilha_2026",
            deduplication_strategy="update",
            items=[
                UserImportItem(
                    name="João Santos Atualizado",
                    phone="(85) 99111-2222",
                    tags=["vip", "antigo"],  # 'antigo' já existe, deve mesclar
                    city="Fortaleza",
                    state="CE",
                    notes="Nota 2",
                    custom_fields={"segmento": "premium"},
                )
            ],
        )

        summary = service.import_items(request)
        assert summary.total == 1
        assert summary.updated == 1
        assert summary.created == 0

        db_session.refresh(initial_user)
        assert initial_user.name == "João Santos Atualizado"
        assert "vip" in initial_user.tags
        assert "antigo" in initial_user.tags
        assert len(initial_user.tags) == 2
        assert initial_user.city == "Fortaleza"
        assert initial_user.state == "CE"
        assert initial_user.custom_fields == {"origem": "balcao", "segmento": "premium"}
        assert "Nota 1" in initial_user.notes and "Nota 2" in initial_user.notes

    def test_import_strategy_skip(self, db_session: Session):
        existing = User(name="Ana Maria", phone="5531999990000")
        db_session.add(existing)
        db_session.commit()

        service = ClientImportService(db_session)
        request = UserImportRequest(
            source="rd_station",
            deduplication_strategy="skip",
            items=[
                UserImportItem(name="Ana Maria Nova", phone="31999990000"),
                UserImportItem(name="Novo Cliente", phone="31988881111"),
            ],
        )
        summary = service.import_items(request)
        assert summary.total == 2
        assert summary.skipped == 1
        assert summary.created == 1

        db_session.refresh(existing)
        assert existing.name == "Ana Maria"  # Não alterado

    def test_import_csv_content(self, db_session: Session):
        csv_data = """Nome;Telefone;E-mail;Cidade;Estado;Tags;Observacoes
Beatriz Costa;(41) 99222-3333;beatriz@empresa.com;Curitiba;PR;vip, manicure;Cliente pontual
Lucas Rocha;41991112222;;Curitiba;PR;barba;
"""
        service = ClientImportService(db_session)
        summary = service.import_csv_content(
            csv_text=csv_data,
            source="csv_export",
            deduplication_strategy="update",
            import_batch_id="lote_curitiba_01",
        )

        assert summary.total == 2
        assert summary.created == 2
        assert summary.import_batch_id == "lote_curitiba_01"

        beatriz = db_session.query(User).filter(User.phone == "5541992223333").first()
        assert beatriz is not None
        assert beatriz.name == "Beatriz Costa"
        assert beatriz.email == "beatriz@empresa.com"
        assert beatriz.city == "Curitiba"
        assert beatriz.tags == ["vip", "manicure"]
        assert beatriz.notes == "Cliente pontual"

        lucas = db_session.query(User).filter(User.phone == "5541991112222").first()
        assert lucas is not None
        assert lucas.email is None  # E-mail vazio tratado como None


class TestClientImportAPI:
    def test_api_import_json(self, client: TestClient, db_session: Session):
        payload = {
            "source": "api_partner",
            "deduplication_strategy": "update",
            "items": [
                {
                    "name": "Cliente API 1",
                    "phone": "85991234567",
                    "email": "api1@teste.com",
                    "tags": ["parceiro"],
                }
            ],
        }

        response = client.post("/api/users/import", json=payload, headers=_api_headers())
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["created"] == 1
        assert data["errors"] == 0

    def test_api_import_csv_upload(self, client: TestClient, db_session: Session):
        csv_bytes = b"nome,telefone,email,cidade\nFernanda Lima,85987654321,fernanda@teste.com,Fortaleza\n"
        response = client.post(
            "/api/users/import/csv?source=planilha_balcao",
            files={"file": ("clientes.csv", csv_bytes, "text/csv")},
            headers=_api_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["created"] == 1
        assert data["details"][0]["name"] == "Fernanda Lima"
