import pytest

from tests.seed import seed_appointment, seed_data
from tests.test_admin_csrf import NODE, run_page_javascript
from tests.test_admin_login_flow import login


@pytest.mark.skipif(NODE is None, reason="Node.js is required to execute rendered admin JavaScript")
@pytest.mark.parametrize("path,factory,loader", [
    ("/admin", "dashboard", "loadKPIs"),
    ("/admin/appointments", "appointments", "loadAppointments"),
    ("/admin/payments", "payments", "loadPayments"),
    ("/admin/professionals", "professionals", "loadProfessionals"),
])
def test_admin_lists_distinguish_load_failure_from_empty_data(
    anonymous_client, db_session, path, factory, loader,
):
    seed_appointment(db_session, seed_data(db_session))
    login(anonymous_client)

    response = anonymous_client.get(path)

    assert response.status_code == 200
    assert "Tentar novamente" in response.text
    run_page_javascript(response.text, f"""
        const page = {factory}();
        await page.{loader}();
        assert.equal(page.loading, false);
        assert.equal(page.loadError, 'Não foi possível carregar os dados. Tente novamente.');
    """, ok=False, status=503)


@pytest.mark.skipif(NODE is None, reason="Node.js is required to execute rendered admin JavaScript")
@pytest.mark.parametrize("path,factory", [
    ("/admin", "dashboard"),
    ("/admin/appointments", "appointments"),
    ("/admin/payments", "payments"),
    ("/admin/professionals", "professionals"),
])
def test_admin_list_retry_entrypoint_exists(anonymous_client, db_session, path, factory):
    seed_appointment(db_session, seed_data(db_session))
    login(anonymous_client)

    response = anonymous_client.get(path)

    assert response.status_code == 200
    run_page_javascript(response.text, f"""
        const page = {factory}();
        assert.equal(typeof page.reload, 'function');
    """)


def test_admin_empty_states_and_service_lifecycle_are_unambiguous(
    anonymous_client, db_session,
):
    seed_appointment(db_session, seed_data(db_session))
    login(anonymous_client)

    services = anonymous_client.get("/admin/services")
    professionals = anonymous_client.get("/admin/professionals")
    appointments = anonymous_client.get("/admin/appointments")
    payments = anonymous_client.get("/admin/payments")

    assert "Arquivar/remover" not in services.text
    assert ">Arquivar<" in services.text
    assert "Cadastre o primeiro profissional" in professionals.text
    assert "Criar novo agendamento" in appointments.text
    assert "Limpar filtros" in payments.text
