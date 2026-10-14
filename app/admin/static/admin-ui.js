(function () {
    let restoreFocus = null;

    document.addEventListener('alpine:init', () => {
        Alpine.store('adminUi', {
            notice: null,
            dialog: null,
            inputValue: '',
            inputError: '',

            notify(payload) {
                this.notice = {
                    type: payload.type || 'info',
                    message: payload.message || ''
                };
            },

            dismissNotice() {
                this.notice = null;
            },

            confirm(payload) {
                restoreFocus = document.activeElement;
                this.inputValue = payload.value || '';
                this.inputError = '';
                return new Promise((resolve) => {
                    this.dialog = {
                        title: payload.title || 'Confirmar ação',
                        message: payload.message || '',
                        confirmLabel: payload.confirmLabel || 'Confirmar',
                        destructive: Boolean(payload.destructive),
                        inputLabel: payload.inputLabel || '',
                        inputRequired: Boolean(payload.inputRequired),
                        resolve
                    };
                    queueMicrotask(() => this.focusInitialControl());
                });
            },

            accept() {
                if (!this.dialog) return;
                const value = this.inputValue.trim();
                if (this.dialog.inputRequired && !value) {
                    this.inputError = 'Este campo é obrigatório.';
                    queueMicrotask(() => this.focusInitialControl());
                    return;
                }
                this.finish({confirmed: true, value});
            },

            cancel() {
                if (this.dialog) this.finish({confirmed: false, value: ''});
            },

            finish(decision) {
                const resolve = this.dialog.resolve;
                this.dialog = null;
                this.inputError = '';
                resolve(decision);
                queueMicrotask(() => {
                    if (restoreFocus && typeof restoreFocus.focus === 'function') restoreFocus.focus();
                    restoreFocus = null;
                });
            },

            focusInitialControl() {
                const selector = this.dialog?.inputLabel
                    ? '[data-admin-dialog-input]'
                    : '[data-admin-dialog-confirm]';
                document.querySelector(selector)?.focus();
            },

            trapFocus(event) {
                const panel = document.querySelector('[data-admin-dialog]');
                if (!panel) return;
                const controls = Array.from(panel.querySelectorAll(
                    'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled])'
                ));
                if (!controls.length) return;
                const first = controls[0];
                const last = controls[controls.length - 1];
                if (event.shiftKey && document.activeElement === first) {
                    event.preventDefault();
                    last.focus();
                } else if (!event.shiftKey && document.activeElement === last) {
                    event.preventDefault();
                    first.focus();
                }
            }
        });

        window.adminNotify = (payload) => Alpine.store('adminUi').notify(payload);
        window.adminConfirm = (payload) => Alpine.store('adminUi').confirm(payload);
    });
})();
