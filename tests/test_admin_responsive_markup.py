import pytest

from tests.seed import seed_appointment, seed_data
from tests.test_admin_csrf import NODE, run_page_javascript
from tests.test_admin_login_flow import login


@pytest.mark.skipif(NODE is None, reason="Node.js is required to execute rendered admin JavaScript")
@pytest.mark.parametrize("path,factory", [
    ("/admin/appointments", "appointments()"),
    ("/admin/payments", "payments()"),
    ("/admin/professionals", "professionals()"),
    ("/admin/clients", "clientsPage()"),
    (
        "/admin/services",
        "serviceCatalog({services: [], metrics: {}, issues: []})",
    ),
])
def test_admin_management_lists_offer_mobile_cards_with_masked_contacts(
    anonymous_client, db_session, path, factory,
):
    seed_appointment(db_session, seed_data(db_session))
    login(anonymous_client)

    response = anonymous_client.get(path)

    assert response.status_code == 200
    assert "admin-mobile-list md:hidden" in response.text
    assert "admin-table hidden md:block" in response.text
    run_page_javascript(response.text, f"""
        const page = {factory};
        assert.equal(page.maskPhone('11987654321'), '1198••••321');
        assert.equal(page.maskPhone('123'), 'Não informado');
        assert.equal(page.maskEmail('joao@example.com'), 'jo•••@example.com');
        assert.equal(page.maskEmail(''), '');
    """)
