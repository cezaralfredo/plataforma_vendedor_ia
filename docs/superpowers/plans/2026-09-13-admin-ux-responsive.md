# Admin UX and Responsive Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Padronizar mensagens e confirmações e tornar as quatro grandes listagens confortáveis em telas pequenas.

**Architecture:** Adicionar utilitários de interface em `base.html`, consumidos pelas fábricas Alpine de cada página. Em 390 px, renderizar cartões administrativos; em `md` ou maior, preservar as tabelas existentes.

**Tech Stack:** Jinja2, Alpine.js local, Tailwind CSS atual, pytest, Node.js.

**Spec:** `docs/superpowers/specs/2026-09-12-admin-quality-hardening-design.md`

## Global Constraints

- Não alterar regras de negócio ou permissões de exclusão.
- Confirmações destrutivas precisam nomear o registro e a consequência.
- Modais fecham com `Esc`, mantêm foco preso e devolvem foco ao acionador.
- A página não pode criar rolagem horizontal em 390 px.

---

### Task 1: Sistema comum de notificações e confirmações

**Files:**
- Create: `app/admin/static/admin-ui.js`
- Modify: `app/admin/templates/base.html`
- Test: `tests/test_admin_ui_assets.py`
- Test: `tests/test_admin_csrf.py`

**Interfaces:**
- Produces: `window.adminNotify({type, message})`.
- Produces: `window.adminConfirm({title, message, confirmLabel, destructive, inputLabel, inputRequired}): Promise<{confirmed: boolean, value: string}>`.

- [ ] **Step 1: Write failing asset and markup tests**

```python
assert '/admin/static/admin-ui.js' in response.text
assert 'role="status"' in response.text
assert 'aria-modal="true"' in response.text
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_admin_ui_assets.py -v`
Expected: FAIL because the shared UI asset and dialog do not exist.

- [ ] **Step 3: Implement the shared Alpine store and dialog markup**

```javascript
document.addEventListener('alpine:init', () => {
    Alpine.store('adminUi', {
        notice: null,
        dialog: null,
        notify(payload) { this.notice = payload; },
        confirm(payload) { return new Promise(resolve => { this.dialog = {...payload, resolve}; }); }
    });
});
```

Implement focus capture, `Esc`, required input validation and focus restoration.

- [ ] **Step 4: Verify DOM and JavaScript tests**

Run: `pytest tests/test_admin_ui_assets.py tests/test_admin_csrf.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/admin/static/admin-ui.js app/admin/templates/base.html tests/test_admin_ui_assets.py tests/test_admin_csrf.py
git commit -m "feat(admin): add accessible feedback dialogs"
```

### Task 2: Replace native browser dialogs

**Files:**
- Modify: `app/admin/templates/appointments.html`
- Modify: `app/admin/templates/appointment_detail.html`
- Modify: `app/admin/templates/payments.html`
- Modify: `app/admin/templates/professional_detail.html`
- Modify: `app/admin/templates/services.html`
- Test: `tests/test_admin_csrf.py`
- Test: `tests/test_admin_ui_assets.py`

**Interfaces:**
- Consumes: `adminConfirm` and `adminNotify` from Task 1.
- Produces: no executable `alert(`, `confirm(` or `prompt(` in active admin templates.

- [ ] **Step 1: Add failing source assertions**

```python
for template in ACTIVE_MUTATION_TEMPLATES:
    source = template.read_text(encoding='utf-8')
    assert 'alert(' not in source
    assert 'confirm(' not in source
    assert 'prompt(' not in source
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_admin_ui_assets.py -k native_dialogs -v`
Expected: FAIL on every active mutation template.

- [ ] **Step 3: Migrate actions to contextual dialogs**

```javascript
const decision = await adminConfirm({
    title: 'Cancelar agendamento',
    message: `O horário do agendamento #${id} será liberado.`,
    confirmLabel: 'Cancelar agendamento',
    destructive: true,
    inputLabel: 'Motivo do cancelamento',
    inputRequired: true
});
if (!decision.confirmed) return;
```

Use distinct copy for completion, deletion, archive, offering removal and refund.

- [ ] **Step 4: Verify all mutation JavaScript tests**

Run: `pytest tests/test_admin_csrf.py tests/test_admin_ui_assets.py -v`
Expected: PASS and CSRF assertions unchanged.

- [ ] **Step 5: Commit**

```bash
git add app/admin/templates tests/test_admin_csrf.py tests/test_admin_ui_assets.py
git commit -m "feat(admin): replace native action dialogs"
```

### Task 3: Mobile management cards and privacy-conscious summaries

**Files:**
- Modify: `app/admin/templates/appointments.html`
- Modify: `app/admin/templates/payments.html`
- Modify: `app/admin/templates/professionals.html`
- Modify: `app/admin/templates/services.html`
- Create: `tests/test_admin_responsive_markup.py`

**Interfaces:**
- Produces: `.admin-mobile-list md:hidden` and `.admin-table hidden md:block` on each list page.
- Produces: `maskPhone(value: string): string` and `maskEmail(value: string): string` for list summaries; detail pages keep full values.

- [ ] **Step 1: Write failing responsive markup tests**

```python
assert 'admin-mobile-list md:hidden' in response.text
assert 'admin-table hidden md:block' in response.text
assert 'maskPhone(' in response.text
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_admin_responsive_markup.py -v`
Expected: FAIL because only horizontally scrollable tables exist.

- [ ] **Step 3: Add compact cards with primary action and status**

Each card must show title, essential date/value/status, masked contact and the same permitted actions as its table row. Do not duplicate request code; both views consume the same Alpine arrays and action methods.

```javascript
maskPhone(value) {
    if (!value || value.length < 6) return 'Não informado';
    return `${value.slice(0, 4)}••••${value.slice(-3)}`;
},
maskEmail(value) {
    if (!value || !value.includes('@')) return '';
    const [name, domain] = value.split('@');
    return `${name.slice(0, 2)}•••@${domain}`;
}
```

- [ ] **Step 4: Verify markup and page script tests**

Run: `pytest tests/test_admin_responsive_markup.py tests/test_admin_csrf.py -v`
Expected: PASS.

- [ ] **Step 5: Manually verify 390 px and desktop views without mutations**

Check Dashboard, Agendamentos, Pagamentos, Profissionais and Serviços. Expected: no page-level horizontal overflow, menu usable, cards visible below `md`, tables visible at and above `md`.

- [ ] **Step 6: Commit**

```bash
git add app/admin/templates tests/test_admin_responsive_markup.py
git commit -m "feat(admin): add responsive management cards"
```

### Task 4: Clarify empty states and service lifecycle actions

**Files:**
- Modify: `app/admin/templates/appointments.html`
- Modify: `app/admin/templates/payments.html`
- Modify: `app/admin/templates/professionals.html`
- Modify: `app/admin/templates/services.html`
- Test: `tests/test_admin_pages.py`

**Interfaces:**
- Produces explicit `Arquivar` button for active linked services and `Excluir` only when backend response states deletion is available.
- Produces empty-state action links without changing backend permissions.

- [ ] **Step 1: Add failing copy assertions**

```python
assert 'Arquivar/remover' not in services_page.text
assert 'Arquivar' in services_page.text
assert 'Cadastre o primeiro profissional' in professionals_page.text
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_admin_pages.py -k "empty or lifecycle" -v`
Expected: FAIL on ambiguous labels.

- [ ] **Step 3: Implement contextual labels and empty-state actions**

Use the API result message to say whether the record was archived or removed. Keep `Reativar` for archived services and preserve financial history.

- [ ] **Step 4: Verify page and service lifecycle tests**

Run: `pytest tests/test_admin_pages.py tests/test_company_service_catalog.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/admin/templates tests/test_admin_pages.py
git commit -m "fix(admin): clarify empty and lifecycle states"
```
