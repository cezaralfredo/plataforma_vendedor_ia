import json
import re
import shutil
import subprocess
from unittest.mock import AsyncMock

import pytest

from app.database import Base
from app.services.asaas_client import AsaasClient
from tests.seed import seed_appointment, seed_data, seed_payment
from tests.test_admin_login_flow import login, session_data

# Every existing business mutation; payments exposes POST actions only.
MUTATIONS = [
    ("POST", "/admin/api/appointments", {
        "user_id": 1, "professional_id": 1, "service_id": 1,
        "start_time": "2026-07-30T11:00:00-03:00", "end_time": "2026-07-30T12:00:00-03:00",
    }, 201, {"status": "pending"}),
    ("PUT", "/admin/api/appointments/1", {"notes": "CSRF validado"}, 200, {"notes": "CSRF validado"}),
    ("DELETE", "/admin/api/appointments/1", None, 204, None),
    ("POST", "/admin/appointments/1/action", {"action": "confirm"}, 200, {"status": "confirmed"}),
    ("POST", "/admin/payments/1/action", {"action": "refresh"}, 200, {"changed": True}),
    ("POST", "/admin/payments/1/action", {"action": "refund"}, 200, {"changed": True}),
    ("POST", "/admin/api/professionals", {"name": "Novo profissional", "phone": "11955556666"},
     201, {"name": "Novo profissional"}),
    ("PUT", "/admin/api/professionals/1", {"name": "Nome atualizado"}, 200, {"name": "Nome atualizado"}),
    ("DELETE", "/admin/api/professionals/1", None, 200, {"outcome": "archived"}),
    ("POST", "/admin/api/professionals/1/services", {
        "service_id": 1, "commission_percent": "15.00",
    }, 201, {"price_cents": 5000, "commission_percent": "15.00"}),
    ("DELETE", "/admin/api/professionals/1/services/1", None, 200, {"outcome": "archived"}),
    ("POST", "/admin/api/professionals/1/availability", {
        "day_of_week": 1, "start_time": "08:00", "end_time": "12:00",
    }, 201, {"day_of_week": 1}),
    ("PUT", "/admin/api/professionals/1/availability/1", {
        "start_time": "08:30", "end_time": "11:30",
    }, 200, {"start_time": "08:30:00"}),
    ("DELETE", "/admin/api/professionals/1/availability/1", None, 204, None),
    ("POST", "/admin/api/services", {
        "name": "Novo serviço", "price_cents": 6000, "duration_minutes": 45,
    }, 201, {"name": "Novo serviço"}),
    ("PUT", "/admin/api/services/1", {"name": "Serviço atualizado"}, 200, {"name": "Serviço atualizado"}),
    ("DELETE", "/admin/api/services/1", None, 200, {"outcome": "archived"}),
    ("POST", "/admin/api/services/1/reactivate", None, 200, {"active": True}),
    ("POST", "/admin/api/clients", {
        "name": "Novo cliente", "phone": "11988887777", "email": "novo@example.com",
    }, 201, {"name": "Novo cliente"}),
    ("PUT", "/admin/api/clients/1", {"name": "Cliente atualizado"}, 200, {"name": "Cliente atualizado"}),
    ("DELETE", "/admin/api/clients/1", None, 200, {"outcome": "archived"}),
    ("POST", "/admin/api/clients/1/reactivate", None, 200, {"active": True}),
]


def database_snapshot(db):
    return {table.name: db.execute(table.select()).all() for table in Base.metadata.sorted_tables}


@pytest.mark.parametrize("auth_method", ["session", "technical_key"])
@pytest.mark.parametrize("method,path,payload,status,expected", MUTATIONS)
def test_business_mutation_requires_session_csrf_but_not_technical_key(
    anonymous_client, db_session, monkeypatch, auth_method, method, path, payload, status, expected,
):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    appointment.status = "pending"
    appointment.expires_at = None
    if path == "/admin/appointments/1/action" and payload == {"action": "confirm"}:
        payment = seed_payment(db_session, appointment)
        payment.status = "received"
    if "/payments/" in path:
        payment = seed_payment(db_session, appointment)
        payment.status = "received"
        appointment.status = "confirmed"
        monkeypatch.setattr(AsaasClient, "get_payment", AsyncMock(return_value={"status": "CONFIRMED"}))
        monkeypatch.setattr(AsaasClient, "refund_payment", AsyncMock(return_value={"status": "REFUNDED"}))
    if path.endswith("/reactivate"):
        if "/clients/" in path:
            entities["user"].active = False
        else:
            entities["service"].active = False
    db_session.commit()

    if auth_method == "session":
        assert login(anonymous_client).status_code == 303
        before = database_snapshot(db_session)
        for token in [None, "incorrect-token"]:
            rejected = anonymous_client.request(
                method, path, json=payload, headers={} if token is None else {"X-CSRF-Token": token},
            )
            assert rejected.status_code == 403
            assert rejected.json() == {"detail": "Admin access denied"}
            assert database_snapshot(db_session) == before
        headers = {"X-CSRF-Token": session_data(anonymous_client)["csrf_token"]}
    else:
        headers = {"X-Admin-Key": anonymous_client.app.state.settings.admin_api_key}

    response = anonymous_client.request(method, path, json=payload, headers=headers)
    assert response.status_code == status, response.text
    if expected is None:
        assert response.content == b""
    else:
        assert response.json().items() >= expected.items()


@pytest.mark.parametrize("path", [
    "/admin", "/admin/appointments", "/admin/appointments/1", "/admin/payments",
    "/admin/professionals", "/admin/professionals/new", "/admin/professionals/1/edit", "/admin/services",
    "/admin/clients",
])
def test_csrf_meta_exposes_only_the_current_human_session(anonymous_client, db_session, path):
    seed_appointment(db_session, seed_data(db_session))
    assert login(anonymous_client).status_code == 303
    response = anonymous_client.get(path)
    assert response.status_code == 200
    meta = re.search(r'<meta name="csrf-token" content="([^"]+)">', response.text)
    assert meta is not None
    assert meta[1] == session_data(anonymous_client)["csrf_token"]
    # A technical key takes precedence even when the browser also has a session.
    technical = anonymous_client.get(path, headers={
        "X-Admin-Key": anonymous_client.app.state.settings.admin_api_key,
    })
    assert technical.status_code == 200
    assert '<meta name="csrf-token"' not in technical.text


NODE = shutil.which("node")
JS_RUNNER = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const calls = [], alerts = [], notices = [], confirmations = [];
const token = input.html.match(/<meta name="csrf-token" content="([^"]+)">/)?.[1];
const response = {
    ok: input.ok ?? true, status: input.status ?? 200,
    json: async () => input.json ?? ({id: 1, outcome: 'archived', data: [], detail: 'Falha de domínio', message: 'Atualizado'}),
    text: async () => '',
};
const context = vm.createContext({
    Headers, URLSearchParams, console, calls, alerts, notices, confirmations, response, assert,
    document: {querySelector: () => token ? {content: token} : null},
    fetch: (url, options = {}) => {
        calls.push({url, ...options, headers: Object.fromEntries(new Headers(options.headers))});
        return Promise.resolve(response);
    },
    alert: message => alerts.push(message), confirm: () => true, prompt: () => '09:00',
    adminNotify: payload => notices.push(payload),
    adminConfirm: payload => {
        confirmations.push(payload);
        let value = payload.value || '';
        if (payload.inputLabel?.includes('Início')) value = '09:00';
        if (payload.inputLabel?.includes('Fim')) value = '10:00';
        if (payload.inputRequired && !value) value = 'Motivo de teste';
        return Promise.resolve({confirmed: true, value});
    },
    location: {reload() {}, href: ''},
});
for (const script of input.html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) {
    vm.runInContext(script[1], context);
}
vm.runInContext('(async () => {' + input.action + '})()', context)
    .then(() => process.stdout.write(JSON.stringify({calls, alerts, notices, confirmations})))
    .catch(error => { console.error(error); process.exitCode = 1; });
"""


def run_page_javascript(html, action, **options):
    result = subprocess.run(  # noqa: S603
        [NODE, "-e", JS_RUNNER], input=json.dumps({"html": html, "action": action, **options}),
        text=True, encoding="utf-8", capture_output=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason="Node.js is required to execute rendered admin JavaScript")
@pytest.mark.parametrize("path,factory", [
    ("/admin/payments", "payments"),
    ("/admin/appointments/1", "appointmentDetail"),
])
def test_payment_pages_present_billing_types_in_portuguese(
    anonymous_client, db_session, path, factory,
):
    seed_appointment(db_session, seed_data(db_session))
    login(anonymous_client)

    page = anonymous_client.get(path)

    assert page.status_code == 200
    run_page_javascript(page.text, f"""
        const page = {factory}();
        assert.equal(page.formatBillingType('undefined'), 'A definir');
        assert.equal(page.formatBillingType(null), 'A definir');
        assert.equal(page.formatBillingType('pix'), 'PIX');
        assert.equal(page.formatBillingType('boleto'), 'Boleto');
        assert.equal(page.formatBillingType('credit_card'), 'Cartão de crédito');
    """)


@pytest.mark.skipif(NODE is None, reason="Node.js is required to execute rendered admin JavaScript")
def test_professionals_page_loads_its_json_endpoint_once(anonymous_client):
    login(anonymous_client)
    page = anonymous_client.get("/admin/professionals")

    result = run_page_javascript(
        page.text,
        "const page = professionals(); await page.loadProfessionals();",
    )

    assert [call["url"] for call in result["calls"]] == ["/admin/api/professionals"]


@pytest.mark.skipif(NODE is None, reason="Node.js is required to execute rendered admin JavaScript")
def test_payments_page_updates_only_the_synchronized_row(anonymous_client):
    login(anonymous_client)
    page = anonymous_client.get("/admin/payments")
    payment = {
        "id": 1,
        "appointment_id": 1,
        "amount_cents": 5000,
        "billing_type": "pix",
        "status": "confirmed",
        "created_at": "2026-09-13T10:00:00Z",
        "updated_at": "2026-09-13T10:01:00Z",
    }

    run_page_javascript(page.text, """
        const page = payments();
        page.payments = [{id: 1, status: 'pending'}, {id: 2, status: 'received'}];
        await page.refreshPayment(1);
        assert.equal(page.payments[0].status, 'confirmed');
        assert.equal(page.payments[1].status, 'received');
        assert.equal(page.notice, 'Pagamento sincronizado: confirmado.');
        assert.equal(page.syncingPaymentId, null);
        assert.equal(alerts.length, 0);
    """, json={
        "message": "Pagamento sincronizado: confirmado.",
        "changed": True,
        "payment": payment,
    })


@pytest.mark.skipif(NODE is None, reason="Node.js is required to execute rendered admin JavaScript")
@pytest.mark.parametrize("authenticated", [True, False])
def test_admin_fetch_preserves_request_and_response_and_only_adds_csrf_to_mutations(
    anonymous_client, authenticated,
):
    if authenticated:
        login(anonymous_client)
        page = anonymous_client.get("/admin")
    else:
        page = anonymous_client.get("/admin", headers={
            "X-Admin-Key": anonymous_client.app.state.settings.admin_api_key,
        })
    result = run_page_javascript(page.text, """
        for (const method of ['GET', 'HEAD', 'POST', 'put', 'PATCH', 'DELETE']) {
            const headers = new Headers({'Content-Type': 'application/json', 'X-Custom': 'preserved'});
            const options = {method, headers, body: 'payload', credentials: 'omit'};
            const actual = await adminFetch('/admin/api/services', options);
            assert.equal(actual, response);
            assert.equal(headers.has('X-CSRF-Token'), false);
            assert.equal(options.credentials, 'omit');
        }
    """, ok=False, status=403)
    assert len(result["calls"]) == 6
    for call in result["calls"]:
        assert call["credentials"] == "same-origin"
        assert call["body"] == "payload"
        assert call["headers"]["content-type"] == "application/json"
        assert call["headers"]["x-custom"] == "preserved"
        if authenticated and call["method"].upper() not in {"GET", "HEAD"}:
            assert call["headers"]["x-csrf-token"] == session_data(anonymous_client)["csrf_token"]
        else:
            assert "x-csrf-token" not in call["headers"]


PAGE_ACTIONS = [
    ("/admin", "const page = dashboard(); await page.loadKPIs();", 0),
    ("/admin/professionals", "const page = professionals(); await page.loadProfessionals();", 0),
    ("/admin/appointments", """
        const page = appointments();
        await page.loadAppointments(); await page.loadProfessionals();
        await page.createAppointment(); await page.editAppointmentNotes({id: 1});
        await page.deleteAppointment(1); await page.appointmentAction(1, 'confirm');
    """, 4),
    ("/admin/appointments/1", """
        const page = appointmentDetail();
        await page.appointmentAction('confirm', ''); await page.refreshPayment(1); await page.refundPayment(1);
    """, 3),
    ("/admin/payments", """
        const page = payments();
        await page.loadPayments(); await page.refreshPayment(1); await page.refundPayment(1);
    """, 2),
    ("/admin/professionals/new", "const page = professionalManagement(); await page.saveProfessional();", 1),
    ("/admin/professionals/1/edit", """
        const page = professionalManagement();
        await page.saveProfessional(); await page.archiveProfessional(); await page.addAvailability();
        await page.editAvailability(1, '08:00', '12:00'); await page.deleteAvailability(1);
        await page.saveOffering(); await page.removeOffering(1);
    """, 7),
    ("/admin/services", """
        const page = serviceCatalog([]);
        await page.reload(); await page.save(); page.editingId = 1; await page.save();
        await page.remove({id: 1, name: 'Corte'}); await page.reactivate({id: 1});
    """, 4),
    ("/admin/clients", """
        const page = clientsPage();
        await page.reload(); await page.save(); page.editingId = 1; await page.save();
        await page.remove({id: 1, name: 'Cliente'}); await page.reactivate({id: 1, name: 'Cliente'});
    """, 4),
]


@pytest.mark.skipif(NODE is None, reason="Node.js is required to execute rendered admin JavaScript")
@pytest.mark.parametrize("path,action,mutations", PAGE_ACTIONS)
def test_existing_page_actions_send_session_csrf_and_same_origin(
    anonymous_client, db_session, path, action, mutations,
):
    seed_appointment(db_session, seed_data(db_session))
    login(anonymous_client)
    page = anonymous_client.get(path)
    assert page.status_code == 200
    result = run_page_javascript(page.text, action)
    assert result["calls"]
    mutation_calls = [call for call in result["calls"] if call.get("method", "GET") != "GET"]
    assert len(mutation_calls) == mutations
    for call in result["calls"]:
        assert call["credentials"] == "same-origin"
        if call in mutation_calls:
            assert call["headers"]["x-csrf-token"] == session_data(anonymous_client)["csrf_token"]
        else:
            assert "x-csrf-token" not in call["headers"]
        if call.get("body"):
            assert call["headers"]["content-type"] == "application/json"


@pytest.mark.skipif(NODE is None, reason="Node.js is required to execute rendered admin JavaScript")
@pytest.mark.parametrize("path,action", [
    ("/admin/appointments", "const page = appointments(); await page.createAppointment(); assert.equal(page.createError, 'Falha de domínio');"),
    ("/admin/appointments/1", "await appointmentDetail().appointmentAction('confirm', ''); assert.equal(notices.length, 1); assert.equal(notices[0].message, 'Falha de domínio');"),
    ("/admin/payments", "await payments().refundPayment(1); assert.equal(notices.length, 1); assert.equal(notices[0].message, 'Falha de domínio');"),
    ("/admin/professionals/1/edit", "const page = professionalManagement(); await page.saveProfessional(); assert.equal(page.message, 'Falha de domínio'); assert.equal(page.messageError, true);"),
    ("/admin/services", "const page = serviceCatalog([]); await page.save(); assert.equal(page.message, 'Falha de domínio'); assert.equal(page.messageError, true);"),
])
def test_page_keeps_domain_error_handling(anonymous_client, db_session, path, action):
    seed_appointment(db_session, seed_data(db_session))
    login(anonymous_client)
    run_page_javascript(anonymous_client.get(path).text, action, ok=False, status=409)
