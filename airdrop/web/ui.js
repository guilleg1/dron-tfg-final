// Modales propios (alert / confirm / formulario) para no usar los pop-ups del
// navegador. Cada función devuelve una promesa con el resultado.

const UI = {
    _root() {
        let r = document.getElementById('ui-modal-root');
        if (!r) {
            r = document.createElement('div');
            r.id = 'ui-modal-root';
            document.body.appendChild(r);
        }
        return r;
    },

    _open(html) {
        const overlay = document.createElement('div');
        overlay.className = 'ui-overlay';
        overlay.innerHTML = `<div class="ui-modal">${html}</div>`;
        this._root().appendChild(overlay);
        return overlay;
    },

    _esc(s) {
        return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    },

    alert(message, title = 'Aviso') {
        return new Promise(res => {
            const ov = this._open(
                `<h3>${this._esc(title)}</h3><p class="ui-msg">${this._esc(message)}</p>`
                + `<div class="ui-actions"><button class="ui-ok">Aceptar</button></div>`);
            ov.querySelector('.ui-ok').onclick = () => { ov.remove(); res(); };
        });
    },

    confirm(message, title = 'Confirmar') {
        return new Promise(res => {
            const ov = this._open(
                `<h3>${this._esc(title)}</h3><p class="ui-msg">${this._esc(message)}</p>`
                + `<div class="ui-actions"><button class="secondary ui-cancel">Cancelar</button>`
                + `<button class="ui-ok">Aceptar</button></div>`);
            ov.querySelector('.ui-ok').onclick = () => { ov.remove(); res(true); };
            ov.querySelector('.ui-cancel').onclick = () => { ov.remove(); res(false); };
        });
    },

    // fields: [{name, label, type?:'text'|'number'|'select', options?:[], value?, step?}]
    // Resuelve con un objeto {name: valor} o null si se cancela.
    form({ title, fields, submitLabel = 'Aceptar' }) {
        return new Promise(res => {
            const body = fields.map(f => {
                if (f.type === 'select') {
                    const opts = (f.options || []).map(o =>
                        `<option value="${this._esc(o)}"${o === f.value ? ' selected' : ''}>${this._esc(o)}</option>`).join('');
                    return `<div class="form-group"><label>${this._esc(f.label)}</label>`
                        + `<select data-name="${f.name}">${opts}</select></div>`;
                }
                const step = f.step ? ` step="${f.step}"` : '';
                return `<div class="form-group"><label>${this._esc(f.label)}</label>`
                    + `<input type="${f.type || 'text'}" data-name="${f.name}" value="${this._esc(f.value ?? '')}"${step}></div>`;
            }).join('');
            const ov = this._open(
                `<h3>${this._esc(title)}</h3>${body}`
                + `<div class="ui-actions"><button class="secondary ui-cancel">Cancelar</button>`
                + `<button class="ui-ok">${this._esc(submitLabel)}</button></div>`);
            const collect = () => {
                const vals = {};
                ov.querySelectorAll('[data-name]').forEach(el => { vals[el.dataset.name] = el.value.trim(); });
                return vals;
            };
            ov.querySelector('.ui-ok').onclick = () => { const v = collect(); ov.remove(); res(v); };
            ov.querySelector('.ui-cancel').onclick = () => { ov.remove(); res(null); };
            const first = ov.querySelector('[data-name]');
            if (first) first.focus();
        });
    },
};
