import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import settings

NODE = shutil.which("node")
ACTIVE_MUTATION_TEMPLATES = [
    "appointments.html",
    "appointment_detail.html",
    "payments.html",
    "professional_detail.html",
    "services.html",
    "users.html",
]


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": settings.admin_api_key}


def test_admin_assets_are_served_locally(anonymous_client):
    response = anonymous_client.get("/admin/services", headers=_admin_headers())
    assert response.status_code == 200
    for host in ("unpkg.com", "cdn.tailwindcss.com", "cdnjs.cloudflare.com"):
        assert host not in response.text
    for asset in (
        "/admin/static/admin.css",
        "/admin/static/vendor/fontawesome/css/all.min.css",
        "/admin/static/vendor/fontawesome/webfonts/fa-solid-900.woff2",
    ):
        resource = anonymous_client.get(asset)
        assert resource.status_code == 200
        assert len(resource.content) > 100


def test_admin_shell_exposes_accessible_shared_feedback(anonymous_client):
    response = anonymous_client.get("/admin/services", headers=_admin_headers())

    assert response.status_code == 200
    assert 'src="/admin/static/admin-ui.js"' in response.text
    assert 'role="status"' in response.text
    assert 'role="dialog"' in response.text
    assert 'aria-modal="true"' in response.text

    asset = anonymous_client.get("/admin/static/admin-ui.js")
    assert asset.status_code == 200


@pytest.mark.skipif(NODE is None, reason="Node.js is required to execute the admin UI runtime")
def test_admin_confirmation_requires_input_and_resolves_decision(anonymous_client):
    source = anonymous_client.get("/admin/static/admin-ui.js").text
    runner = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = JSON.parse(fs.readFileSync(0, 'utf8'));
const listeners = {}, stores = {};
const input = {focusCalled: false, focus() { this.focusCalled = true; }};
const trigger = {focusCalled: false, focus() { this.focusCalled = true; }};
const document = {
    activeElement: trigger,
    addEventListener: (name, callback) => { listeners[name] = callback; },
    querySelector: selector => selector.includes('input') ? input : null,
};
const Alpine = {
    store(name, value) {
        if (value !== undefined) stores[name] = value;
        return stores[name];
    },
};
const context = vm.createContext({window: {}, document, Alpine, queueMicrotask: callback => callback()});
vm.runInContext(source, context);
listeners['alpine:init']();

(async () => {
    const decisionPromise = context.window.adminConfirm({
        title: 'Cancelar', message: 'Informe o motivo', inputRequired: true,
    });
    stores.adminUi.accept();
    assert.equal(stores.adminUi.inputError, 'Este campo é obrigatório.');
    stores.adminUi.inputValue = 'Cliente solicitou';
    stores.adminUi.accept();
    const decision = await decisionPromise;
    assert.equal(decision.confirmed, true);
    assert.equal(decision.value, 'Cliente solicitou');
    assert.equal(trigger.focusCalled, true);
    context.window.adminNotify({type: 'success', message: 'Atualizado'});
    assert.equal(stores.adminUi.notice.message, 'Atualizado');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(  # noqa: S603
        [NODE, "-e", runner],
        input=json.dumps(source),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_active_admin_actions_do_not_use_native_browser_dialogs():
    templates = Path("app/admin/templates")

    for name in ACTIVE_MUTATION_TEMPLATES:
        source = (templates / name).read_text(encoding="utf-8")
        assert "alert(" not in source, name
        assert "confirm(" not in source, name
        assert "prompt(" not in source, name
