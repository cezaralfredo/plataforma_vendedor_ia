from tests.seed import seed_data
from tests.test_admin_csrf import run_page_javascript
from tests.test_admin_professional_management import _admin_headers


def test_service_choices_explain_variant_and_company_price(anonymous_client, db_session):
    entities = seed_data(db_session)
    page = anonymous_client.get('/admin/appointments', headers=_admin_headers())
    run_page_javascript(page.text, """
        const choices = appointments().appointmentOptions.services;
        assert.equal(choices[0].label, 'Corte de cabelo — Corte masculino e feminino · R$ 50,00 · 60 min');
        assert.equal(choices[1].label, 'Escova — Escova modeladora · R$ 35,00 · 45 min');
    """)
    detail = anonymous_client.get(
        f"/admin/professionals/{entities['professional'].id}/edit", headers=_admin_headers(),
    )
    assert 'Corte de cabelo — Corte masculino e feminino · R$ 50,00 · 60 min</option>' in detail.text
    assert 'Quarta-feira' in detail.text


def test_professionals_loading_state_covers_pending_request_and_failure(anonymous_client):
    page = anonymous_client.get('/admin/professionals', headers=_admin_headers())
    run_page_javascript(page.text, """
        const page = professionals();
        assert.equal(page.loading, true);
        let rejectRequest;
        page.loadProfessionals = page.loadProfessionals.bind(page);
        adminFetch = () => new Promise((resolve, reject) => { rejectRequest = reject; });
        const pending = page.reload();
        assert.equal(page.loading, true);
        rejectRequest(new Error('offline'));
        await pending;
        assert.equal(page.loading, false);
        assert.ok(page.loadError);
    """)
