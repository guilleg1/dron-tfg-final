// Panel de administración: login, edición de perfiles/rutas sobre el mapa y
// monitorización de pedidos. Reutiliza makeBadge() de app.js.

const admin = {
    token: null,
    data: null,        // documento {profiles:[...]}
    profile: null,     // perfil seleccionado (referencia dentro de data)
    orders: [],
    map: null,
    layer: null,
    pick: null,        // modo de captura de clic en el mapa
    routeDraft: null,  // ruta en construcción
    needsSetup: false,
    fleetLayer: null,        // marcadores de la flota en el mapa
    trackedDroneId: null,    // dron que el mapa sigue
    followingDrone: false,   // se apaga al arrastrar el mapa

    async init() {
        this.token = localStorage.getItem('admin_token');
        try {
            const ns = await fetch('/api/admin/needs-setup').then(r => r.json());
            this.needsSetup = !!ns.needs_setup;
        } catch (e) {}
        if (this.needsSetup) {
            document.getElementById('login-subtitle').innerText =
                'No hay administrador. Crea la cuenta de admin.';
            document.getElementById('btn-admin-login').innerText = 'Crear admin';
        }
        if (this.token) this.enterPanel();
    },

    authHeaders() {
        return { 'Authorization': 'Bearer ' + this.token, 'Content-Type': 'application/json' };
    },

    async submitAuth(e) {
        e.preventDefault();
        const username = document.getElementById('admin-user').value.trim();
        const password = document.getElementById('admin-pass').value;
        const ep = this.needsSetup ? '/api/admin/register' : '/api/admin/login';
        try {
            const res = await fetch(ep, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
            });
            const d = await res.json();
            if (d.error) throw new Error(d.error);
            this.token = d.token;
            localStorage.setItem('admin_token', this.token);
            this.needsSetup = false;
            this.enterPanel();
        } catch (err) {
            UI.alert(err.message, 'Error');
        }
    },

    logout() {
        localStorage.removeItem('admin_token');
        this.token = null;
        document.getElementById('admin-panel-view').classList.remove('active');
        document.getElementById('admin-login-view').style.display = 'block';
    },

    async enterPanel() {
        document.getElementById('admin-login-view').style.display = 'none';
        document.getElementById('admin-panel-view').classList.add('active');
        if (!this.map) this.initMap();
        // ¿Hay dron conectado (modo local) o estamos en cloud (stub)?
        try {
            const t = await fetch('/api/drone/telemetry').then(r => r.json());
            this.hasDrone = t.backend === 'local';
        } catch (e) { this.hasDrone = false; }
        this.applyDroneMode();
        await this.loadProfiles();
        this.loadFleet();
        this.setupCollapsibles();
        this.startFleetMapPolling();
        // Telemetría en vivo solo si hay dron (en cloud no aporta nada).
        if (this.telInterval) clearInterval(this.telInterval);
        if (this.hasDrone) {
            this.pollTelemetry();
            this.telInterval = setInterval(() => this.pollTelemetry(), 2000);
        }
    },

    // Oculta los controles específicos del dron cuando no hay conexión (cloud).
    applyDroneMode() {
        const show = !!this.hasDrone;
        const mon = document.getElementById('drone-monitor');
        const ops = document.getElementById('drone-ops-section');
        if (mon) mon.classList.toggle('hidden', !show);
        if (ops) ops.classList.toggle('hidden', !show);
    },

    initMap() {
        this.map = L.map('admin-map', { attributionControl: false }).setView([41.283, 1.985], 15);
        L.tileLayer('https://mt0.google.com/vt/lyrs=s&hl=es&x={x}&y={y}&z={z}', { maxZoom: 20 }).addTo(this.map);
        this.layer = L.layerGroup().addTo(this.map);
        this.draftLayer = L.layerGroup().addTo(this.map);  // ruta en construcción
        this.droneMarker = L.marker([0, 0], {
            icon: makeBadge('#00e5ff', DRONE_SVG, 34, true), zIndexOffset: 1000,
        }).addTo(this.map);
        this.droneMarker.setOpacity(0);
        this.map.on('click', (e) => this.onMapClick(e));
        setTimeout(() => this.map.invalidateSize(), 150);
        // Las pestañas ocultan y muestran el mapa; sin volver a medirlo,
        // Leaflet dejaba teselas grises hasta recargar la página.
        if (window.ResizeObserver) {
            new ResizeObserver(() => this.map.invalidateSize())
                .observe(document.getElementById('admin-map'));
        }
    },

    toggleMonitor() {
        const body = document.getElementById('dm-body');
        const open = body.classList.toggle('hidden') === false;
        document.getElementById('dm-toggle').innerText = open ? '▾' : '▸';
    },

    async pollTelemetry() {
        try {
            const d = await fetch('/api/drone/telemetry').then(r => r.json());
            const tel = d.telemetry || {};
            const hasFix = tel.lat != null && tel.lon != null;

            document.getElementById('dm-state').innerText = d.state || '—';
            const fmt = (v, dec, unit) => (v == null ? '—' : Number(v).toFixed(dec) + (unit || ''));
            document.getElementById('dm-rows').innerHTML =
                this._dmRow('Modo de vuelo', tel.flightMode || '—')
                + this._dmRow('Latitud', tel.lat != null ? Number(tel.lat).toFixed(6) : '—')
                + this._dmRow('Longitud', tel.lon != null ? Number(tel.lon).toFixed(6) : '—')
                + this._dmRow('Altitud', fmt(tel.alt, 1, ' m'))
                + this._dmRow('Velocidad', fmt(tel.groundSpeed != null ? tel.groundSpeed : tel.speed, 1, ' m/s'))
                + this._dmRow('Rumbo', fmt(tel.heading, 0, '°'));

            if (hasFix) {
                this.droneMarker.setLatLng([tel.lat, tel.lon]).setOpacity(1);
            } else {
                this.droneMarker.setOpacity(0);
            }
        } catch (e) { /* sin telemetría */ }
    },

    _dmRow(label, value) {
        return `<div class="dm-row"><span>${label}</span><b>${value}</b></div>`;
    },

    // ── Perfiles ─────────────────────────────────────────────────────────
    async loadProfiles() {
        const res = await fetch('/api/admin/profiles', { headers: this.authHeaders() });
        if (res.status === 401) return this.logout();
        this.data = await res.json();
        const sel = document.getElementById('profile-select');
        sel.innerHTML = this.data.profiles.map(p => `<option>${p.name}</option>`).join('');
        if (this.data.profiles.length) {
            this.selectProfile(this.data.profiles[0].name);
        } else {
            // Se puede borrar el ultimo perfil: sin esto, el resto del panel
            // seguiria pintando el perfil recien borrado.
            this.profile = null;
            if (this.layer) this.layer.clearLayers();
            document.getElementById('routes-status').innerText =
                'No hay escenarios de rutas. Crea uno con «Nuevo escenario».';
        }
    },

    selectProfile(name) {
        this.profile = this.data.profiles.find(p => p.name === name);
        if (!this.profile) return;
        document.getElementById('profile-select').value = name;
        document.getElementById('profile-speed').value = this.profile.speed ?? 7;
        this.renderProfile();
        this.drawProfile();
        this.renderFlightLevels();
    },

    renderProfile() {
        const p = this.profile;
        document.getElementById('hub-line').innerText = p.hub
            ? `HUB: ${p.hub.lat.toFixed(5)}, ${p.hub.lon.toFixed(5)}` : 'HUB: no definido';
        const row = (label, onDel) =>
            `<li><span>${label}</span><button class="x" onclick="${onDel}">✕</button></li>`;
        document.getElementById('parkings-list').innerHTML =
            (p.parkings || []).map((pk, i) => row(pk.name, `admin.removePoint('parking',${i})`)).join('')
            || '<li class="muted">—</li>';
        document.getElementById('dests-list').innerHTML =
            (p.destinations || []).map((d, i) => row(d.name, `admin.removePoint('destination',${i})`)).join('')
            || '<li class="muted">—</li>';
        document.getElementById('routes-list').innerHTML =
            (p.routes || []).map((r, i) => {
                const n = (r.intermediates || []).length;
                const meta = `${r.parking}→${r.destination}${n ? `, ${n} int.` : ''}`;
                return `<li><span>${r.name} <small>(${meta})</small></span>`
                    + `<span class="li-btns">`
                    + `<button class="x" title="Editar waypoints" onclick="admin.editRoute(${i})">✎</button>`
                    + `<button class="x" title="Borrar" onclick="admin.removeRoute(${i})">✕</button></span></li>`;
            }).join('') || '<li class="muted">—</li>';
    },

    drawProfile() {
        if (!this.layer) return;
        this.layer.clearLayers();
        const p = this.profile;
        if (!p) return;
        const bounds = [];
        (p.parkings || []).forEach(pk => { this.marker([pk.lat, pk.lon], '#43a047', 'P', pk.name); bounds.push([pk.lat, pk.lon]); });
        if (p.hub) { this.marker([p.hub.lat, p.hub.lon], '#fbc02d', 'H', 'HUB'); bounds.push([p.hub.lat, p.hub.lon]); }
        (p.destinations || []).forEach(d => { this.marker([d.lat, d.lon], '#e53935', '◆', d.name); bounds.push([d.lat, d.lon]); });
        (p.routes || []).forEach(r => {
            const pk = (p.parkings || []).find(x => x.name === r.parking);
            const d = (p.destinations || []).find(x => x.name === r.destination);
            if (!pk || !d) return;
            const pts = [[pk.lat, pk.lon]];
            if (p.hub) pts.push([p.hub.lat, p.hub.lon]);
            (r.intermediates || []).forEach(it => pts.push([it.lat, it.lon]));
            pts.push([d.lat, d.lon]);
            L.polyline(pts, { color: '#ffffff', weight: 7, opacity: 0.85 }).addTo(this.layer);
            L.polyline(pts, { color: '#00bcd4', weight: 4, opacity: 1 }).addTo(this.layer);
        });
        if (bounds.length) this.map.fitBounds(bounds, { padding: [50, 50], maxZoom: 16 });
    },

    marker(pos, color, glyph, label) {
        const m = L.marker(pos, { icon: makeBadge(color, glyph, 24) }).addTo(this.layer);
        if (label) m.bindTooltip(label, { permanent: true, direction: 'top', offset: [0, -12], className: 'wp-label' });
        return m;
    },

    // ── Captura de puntos en el mapa ─────────────────────────────────────
    startPick(type) {
        this.pick = { type };
        this.showBanner(type === 'hub' ? 'Haz clic en el mapa para fijar el HUB.' : 'Haz clic en el mapa.');
    },

    async addPointPrompt(kind) {
        const r = await UI.form({
            title: kind === 'parking' ? 'Nuevo parking' : 'Nuevo destino',
            fields: [{ name: 'name', label: 'Nombre' }],
            submitLabel: 'Continuar',
        });
        if (!r || !r.name) return;
        this.pick = { type: 'point', kind, name: r.name };
        this.showBanner(`Haz clic en el mapa para colocar "${r.name}".`);
    },

    onMapClick(e) {
        // Clicar en el mapa fuera del modo de captura sale del foco de un
        // pedido y devuelve la vista general.
        if (!this.pick) return this.clearOrderFocus();
        if (!this.profile) return;
        const lat = e.latlng.lat, lon = e.latlng.lng;
        const p = this.profile;
        if (this.pick.type === 'hub') {
            p.hub = { lat, lon, alt: (p.hub && p.hub.alt) || 20 };
        } else if (this.pick.type === 'point') {
            const pt = { name: this.pick.name, lat, lon, alt: this.pick.kind === 'parking' ? 0 : 15 };
            if (this.pick.kind === 'parking') (p.parkings = p.parkings || []).push(pt);
            else (p.destinations = p.destinations || []).push(pt);
        } else if (this.pick.type === 'intermediate') {
            this.routeDraft.intermediates.push({ lat, lon, alt: (p.hub && p.hub.alt) || 20 });
            this.drawDraft();          // muestra el intermedio en el mapa
            this.renderRouteEditor();  // y en la lista del panel
            return; // sigue en modo intermedio
        }
        this.pick = null;
        this.hideBanner();
        this.renderProfile();
        this.drawProfile();
    },

    // Dibuja la ruta que se está creando (naranja discontinua) con sus
    // intermedios numerados, en una capa aparte para no tocar lo ya guardado.
    drawDraft() {
        if (!this.draftLayer) return;
        this.draftLayer.clearLayers();
        const p = this.profile, dr = this.routeDraft;
        if (!dr) return;
        const pk = (p.parkings || []).find(x => x.name === dr.parking);
        const d = (p.destinations || []).find(x => x.name === dr.destination);
        if (!pk || !d) return;
        const pts = [[pk.lat, pk.lon]];
        if (p.hub) pts.push([p.hub.lat, p.hub.lon]);
        dr.intermediates.forEach(it => pts.push([it.lat, it.lon]));
        pts.push([d.lat, d.lon]);
        L.polyline(pts, { color: '#ff9800', weight: 4, opacity: 0.95, dashArray: '6, 8' }).addTo(this.draftLayer);
        dr.intermediates.forEach((it, i) => {
            L.marker([it.lat, it.lon], { icon: makeBadge('#ff9800', String(i + 1), 22) }).addTo(this.draftLayer);
        });
    },

    removePoint(kind, i) {
        if (kind === 'parking') this.profile.parkings.splice(i, 1);
        else this.profile.destinations.splice(i, 1);
        this.renderProfile();
        this.drawProfile();
    },

    removeRoute(i) {
        this.profile.routes.splice(i, 1);
        this.renderProfile();
        this.drawProfile();
    },

    // ── Creación de ruta ─────────────────────────────────────────────────
    async startRouteCreation() {
        const p = this.profile;
        if (!(p.parkings || []).length || !(p.destinations || []).length)
            return UI.alert('Define al menos un parking y un destino primero.');
        const r = await UI.form({
            title: 'Crear ruta',
            fields: [
                { name: 'name', label: 'Nombre de la ruta' },
                { name: 'parking', label: 'Parking', type: 'select', options: p.parkings.map(x => x.name), value: p.parkings[0].name },
                { name: 'destination', label: 'Destino', type: 'select', options: p.destinations.map(x => x.name), value: p.destinations[0].name },
            ],
            submitLabel: 'Continuar',
        });
        if (!r || !r.name || !r.parking || !r.destination) return;
        this.routeDraft = { name: r.name, parking: r.parking, destination: r.destination, intermediates: [] };
        this.editing = false;   // ruta nueva (se añadirá al terminar)
        this.pick = { type: 'intermediate' };
        this.drawDraft();
        this.renderRouteEditor();
    },

    // Editar una ruta ya guardada: se trabaja sobre el mismo objeto (por
    // referencia), así que añadir/quitar intermedios la modifica in situ.
    editRoute(i) {
        this.routeDraft = this.profile.routes[i];
        this.routeDraft.intermediates = this.routeDraft.intermediates || [];
        this.editing = true;
        this.pick = { type: 'intermediate' };
        this.drawDraft();
        this.renderRouteEditor();
    },

    renderRouteEditor() {
        const dr = this.routeDraft;
        const ed = document.getElementById('route-editor');
        if (!dr) { ed.classList.add('hidden'); return; }
        const items = dr.intermediates.map((it, i) =>
            `<li><span>Intermedio ${i + 1}</span>`
            + `<button class="x" title="Quitar" onclick="admin.removeIntermediate(${i})">✕</button></li>`).join('')
            || '<li class="muted">Sin intermedios. Haz clic en el mapa para añadir.</li>';
        ed.innerHTML = `<div class="re-title">${this.editing ? 'Editando' : 'Nueva ruta'}: `
            + `<b>${dr.name}</b> <small>(${dr.parking}→${dr.destination})</small></div>`
            + `<p class="re-hint">Haz clic en el mapa para añadir waypoints intermedios.</p>`
            + `<ul class="edit-list">${items}</ul>`
            + `<div class="re-actions"><button class="small" onclick="admin.finishRoute()">Hecho</button>`
            + `<button class="secondary small" onclick="admin.cancelPick()">Cancelar</button></div>`;
        ed.classList.remove('hidden');
    },

    removeIntermediate(i) {
        if (!this.routeDraft) return;
        this.routeDraft.intermediates.splice(i, 1);
        this.drawDraft();
        this.renderRouteEditor();
    },

    finishRoute() {
        if (!this.routeDraft) return;
        // Si es nueva, se añade; si se editaba, ya estaba en la lista (referencia).
        if (!this.editing) {
            (this.profile.routes = this.profile.routes || []).push(this.routeDraft);
        }
        this.routeDraft = null;
        this.editing = false;
        this.pick = null;
        this.draftLayer.clearLayers();
        document.getElementById('route-editor').classList.add('hidden');
        this.renderProfile();
        this.drawProfile();
    },

    showBanner(text, withFinish) {
        const b = document.getElementById('pick-banner');
        const action = withFinish
            ? ' <button onclick="admin.finishRoute()">Terminar ruta</button>'
            : ' <button onclick="admin.cancelPick()">Cancelar</button>';
        b.innerHTML = text + action;
        b.classList.remove('hidden');
    },
    hideBanner() { document.getElementById('pick-banner').classList.add('hidden'); },
    cancelPick() {
        this.pick = null;
        this.routeDraft = null;
        this.editing = false;
        this.draftLayer.clearLayers();
        this.hideBanner();
        document.getElementById('route-editor').classList.add('hidden');
        this.drawProfile();
    },

    // ── Secciones plegables ──────────────────────────────────────────────
    // Cada <h3> pasa a ser la cabecera de un desplegable con todo lo que hay
    // hasta el siguiente <h3>. Se hace por JS y no reescribiendo el HTML para
    // que añadir una sección nueva no obligue a acordarse de envolverla.
    //
    // Abiertas de inicio solo las que se miran durante un reparto; el resto
    // son configuración que se toca una vez y estorba el resto del tiempo.
    ABIERTAS_POR_DEFECTO: ['Flota', 'Pedidos', 'Rutas', 'Cuentas de cliente'],

    setupCollapsibles() {
        document.querySelectorAll('.tab-content').forEach(tab => {
            [...tab.querySelectorAll(':scope > h3')].forEach(h3 => {
                if (h3.classList.contains('collapsible')) return;   // idempotente

                const cuerpo = document.createElement('div');
                cuerpo.className = 'collapsible-body';
                // Se mueve todo lo que sigue hasta el proximo h3.
                let nodo = h3.nextElementSibling;
                while (nodo && nodo.tagName !== 'H3') {
                    const siguiente = nodo.nextElementSibling;
                    cuerpo.appendChild(nodo);
                    nodo = siguiente;
                }
                h3.after(cuerpo);

                const titulo = h3.textContent.trim();
                const abierta = this.ABIERTAS_POR_DEFECTO.includes(titulo);
                h3.classList.add('collapsible');
                h3.insertAdjacentHTML('afterbegin',
                    `<span class="chevron">${abierta ? '▾' : '▸'}</span>`);
                cuerpo.classList.toggle('hidden', !abierta);
                h3.onclick = () => {
                    const oculto = cuerpo.classList.toggle('hidden');
                    h3.querySelector('.chevron').textContent = oculto ? '▸' : '▾';
                    // El mapa de Leaflet mide mal si su contenedor cambia de
                    // tamaño mientras está oculto.
                    if (this.map) setTimeout(() => this.map.invalidateSize(), 120);
                };
            });
        });
    },

    // ── Alta y baja de perfiles ──────────────────────────────────────────
    // El backend guarda el documento entero, asi que crear y borrar es
    // operar sobre `this.data` y volver a guardarlo. No hacia falta endpoint
    // nuevo; lo que faltaba era la interfaz.
    async createProfile() {
        const v = await UI.form({
            title: 'Nuevo escenario de rutas',
            fields: [{ name: 'name', label: 'Nombre del escenario' }],
            submitLabel: 'Crear',
        });
        if (!v || !v.name) return;
        if ((this.data.profiles || []).some(p => p.name === v.name)) {
            return UI.alert('Ya existe un escenario con ese nombre.', 'Nombre repetido');
        }
        // Mismos valores por defecto que RouteService.create_profile, para que
        // un perfil creado aqui y otro creado por codigo sean indistinguibles.
        this.data.profiles.push({
            name: v.name, takeOffAlt: 8, speed: 7,
            hub: null, parkings: [], destinations: [], routes: [],
        });
        await this.saveProfiles();
        await this.loadProfiles();
        this.selectProfile(v.name);
        document.getElementById('profile-select').value = v.name;
    },

    // Vuelve a los escenarios del repositorio. Hace falta en un despliegue que
    // ya estaba en marcha: la base de datos guarda los de su primer arranque.
    async resetProfiles() {
        if (!(await UI.confirm(
            'Se restaurarán los escenarios y rutas del repositorio y se perderán '
            + 'los cambios hechos aquí. ¿Seguir?', 'Restaurar'))) return;
        const status = document.getElementById('routes-status');
        try {
            const r = await this.swarmFetch('/api/admin/scenarios/reset-defaults', 'POST');
            status.textContent = 'Escenarios restaurados: ' + r.scenarios.join(', ')
                + (r.restart_required ? '. Reinicia el portal para que el enjambre los use.' : '.');
        } catch (e) {
            status.textContent = e.message;
        }
        this.profile = null;
        await this.loadProfiles();
        if (this.loadScenarios) await this.loadScenarios();
    },

    async deleteProfile() {
        if (!this.profile) return;
        const nombre = this.profile.name;

        // Un escenario apunta a su perfil por nombre: borrarlo dejaria al
        // enjambre sin rutas y los pedidos sin destino asignable. Se avisa
        // antes en vez de dejar que falle al despachar.
        let enUso = [];
        try {
            const d = await this.swarmFetch('/api/admin/scenarios');
            enUso = (d.scenarios || [])
                .filter(s => s.route_profile_name === nombre)
                .map(s => s.name);
        } catch (e) { /* sin enjambre no hay escenarios que comprobar */ }

        const aviso = enUso.length
            ? `\n\nLo usan estos escenarios: ${enUso.join(', ')}. `
              + 'Se quedarán sin rutas.'
            : '';
        if (!(await UI.confirm(
            `¿Eliminar el escenario "${nombre}" con sus rutas y puntos?${aviso}`,
            'Eliminar escenario'))) return;

        this.data.profiles = this.data.profiles.filter(p => p.name !== nombre);
        this.profile = null;
        await this.saveProfiles();
        await this.loadProfiles();
    },

    // ── Plantillas de niveles de vuelo ───────────────────────────────────
    // Una plantilla describe como se reparte el espacio aereo en vertical:
    // primera capa, salto entre capas y techo. De ahi salen los niveles de
    // ida (base + k*salto) y los de vuelta, que ocupan el bloque inmediato
    // superior para que ida y vuelta nunca compartan altura.
    //
    // Viven en el documento de rutas, junto a los corredores, porque son
    // geometria del espacio aereo y no un parametro de operacion. Aplicarlas
    // escribe altitud base, salto y techo en el escenario operacional.
    // Cada preset deja sitio bajo el techo para el bloque de vuelta: con N
    // capas de ida hacen falta 2N huecos. Un preset que no lo cumpla sale
    // marcado en rojo nada mas abrirlo, que es mal ejemplo.
    FL_POR_DEFECTO: [
        // 4 ida (25-40) + 4 vuelta (45-60), muy por debajo de los 120 m legales.
        { name: 'Urbano (120 m)', alt_base_m: 25, alt_step_m: 5, alt_ceiling_m: 120, layers: 4 },
        // DroneLab: techo de 4 m, saltos de medio metro. 2 ida (2 / 2,5) y
        // 2 vuelta (3 / 3,5).
        { name: 'Interior / DroneLab', alt_base_m: 2, alt_step_m: 0.5, alt_ceiling_m: 4, layers: 2 },
        // 3 ida (15-35) + 3 vuelta (45-65) bajo un techo de 90.
        { name: 'Rural bajo', alt_base_m: 15, alt_step_m: 10, alt_ceiling_m: 90, layers: 3 },
    ],

    flightLevels() {
        if (!this.data) return [];
        if (!Array.isArray(this.data.flight_levels) || !this.data.flight_levels.length) {
            this.data.flight_levels = JSON.parse(JSON.stringify(this.FL_POR_DEFECTO));
        }
        return this.data.flight_levels;
    },

    // Niveles que produce una plantilla: los de ida y, encima, los de vuelta.
    computeLevels(fl) {
        const capas = Math.max(1, Math.min(12, Number(fl.layers) || 4));
        const ida = [], vuelta = [];
        for (let k = 0; k < capas; k++) {
            const a = Number(fl.alt_base_m) + k * Number(fl.alt_step_m);
            if (a > Number(fl.alt_ceiling_m)) break;
            ida.push(a);
        }
        // El bloque de vuelta se desplaza tantas capas como haya de ida. Si no
        // cabe bajo el techo se degrada a la de ida, igual que en vuelo.
        for (const a of ida) {
            const v = a + ida.length * Number(fl.alt_step_m);
            vuelta.push(v <= Number(fl.alt_ceiling_m) ? v : a);
        }
        return { ida, vuelta, capas: ida.length };
    },

    renderFlightLevels() {
        const box = document.getElementById('fl-panel');
        if (!box) return;
        const plantillas = this.flightLevels();
        const idx = Math.min(this.flIndex || 0, plantillas.length - 1);
        this.flIndex = idx;
        const fl = plantillas[idx];

        box.innerHTML = `
          <select id="fl-select" onchange="admin.selectFlightLevel(this.value)">
            ${plantillas.map((p, i) =>
              `<option value="${i}"${i === idx ? ' selected' : ''}>${p.name}</option>`).join('')}
          </select>
          <div class="fl-fields">
            ${[['alt_base_m', 'Base (m)'], ['alt_step_m', 'Salto (m)'],
               ['alt_ceiling_m', 'Techo (m)'], ['layers', 'Capas']].map(([k, l]) => `
              <div>
                <label>${l}</label>
                <input type="number" step="any" min="0" id="fl-${k}" value="${fl[k]}"
                       oninput="admin.editFlightLevel('${k}', this.value)">
              </div>`).join('')}
          </div>
          <div id="fl-view">${this.flightLevelChart(fl)}</div>
          <div class="swarm-actions">
            <button class="secondary small" onclick="admin.newFlightLevel()">Nueva</button>
            <button class="secondary small" onclick="admin.renameFlightLevel()">Renombrar</button>
            <button class="secondary small" onclick="admin.deleteFlightLevel()">Eliminar</button>
          </div>
          <button class="secondary small" onclick="admin.applyFlightLevel()">
            Aplicar al escenario operacional</button>
          <p class="status-line" id="fl-status"></p>`;
    },

    // Perfil vertical del espacio aereo. Se dibuja a escala: si el techo esta
    // lejos de la ultima capa, se ve el hueco, que es justo lo que hay que
    // ver para saber si caben los niveles de vuelta.
    flightLevelChart(fl) {
        const { ida, vuelta } = this.computeLevels(fl);
        const techo = Number(fl.alt_ceiling_m) || 1;
        const W = 320, H = 190, ML = 42, MR = 78, MT = 12, MB = 20;
        const y = a => MT + (H - MT - MB) * (1 - a / techo);

        const linea = (a, color, texto, guion) => `
          <line x1="${ML}" y1="${y(a).toFixed(1)}" x2="${W - MR}" y2="${y(a).toFixed(1)}"
                stroke="${color}" stroke-width="2"${guion ? ' stroke-dasharray="5,4"' : ''}/>
          <text x="${W - MR + 6}" y="${(y(a) + 3.5).toFixed(1)}"
                font-size="10" fill="${color}">${texto}</text>`;

        return `
          <svg class="fl-chart" viewBox="0 0 ${W} ${H}" role="img"
               aria-label="Perfil vertical de niveles de vuelo">
            <line x1="${ML}" y1="${MT}" x2="${ML}" y2="${H - MB}" stroke="#bbb"/>
            <line x1="${ML}" y1="${H - MB}" x2="${W - MR}" y2="${H - MB}" stroke="#8d6e63" stroke-width="2"/>
            <text x="${ML - 6}" y="${H - MB + 4}" font-size="9" fill="#777" text-anchor="end">0</text>
            ${linea(techo, '#e53935', `techo ${techo} m`, true)}
            ${ida.map((a, i) => linea(a, '#1e88e5', `ida ${i + 1} · ${a} m`)).join('')}
            ${vuelta.map((a, i) => linea(a, '#fb8c00', `vuelta ${i + 1} · ${a} m`)).join('')}
          </svg>
          <p class="fl-legend">
            <span class="fl-key" style="background:#1e88e5"></span> ida
            <span class="fl-key" style="background:#fb8c00"></span> vuelta
            <span class="fl-key" style="background:#e53935"></span> techo
            ${vuelta.some((v, i) => v === ida[i])
              ? '<b class="fl-warn">Los niveles de vuelta no caben bajo el techo: '
                + 'ida y vuelta compartirían altura.</b>' : ''}
          </p>`;
    },

    selectFlightLevel(i) { this.flIndex = Number(i); this.renderFlightLevels(); },

    editFlightLevel(clave, valor) {
        const fl = this.flightLevels()[this.flIndex];
        const n = parseFloat(valor);
        if (Number.isNaN(n)) return;
        fl[clave] = n;
        // Solo se repinta el grafico: volver a montar el formulario en cada
        // pulsacion sacaria el foco del campo que se esta escribiendo.
        //
        // Se sustituye el CONTENIDO del contenedor, no el <svg>: la funcion
        // devuelve grafico + leyenda, asi que reemplazar solo el svg dejaba la
        // leyenda vieja y anyadia otra en cada tecla.
        const vista = document.getElementById('fl-view');
        if (vista) vista.innerHTML = this.flightLevelChart(fl);
    },

    async newFlightLevel() {
        const v = await UI.form({
            title: 'Nueva plantilla de niveles',
            fields: [{ name: 'name', label: 'Nombre' }], submitLabel: 'Crear',
        });
        if (!v || !v.name) return;
        this.flightLevels().push({
            name: v.name, alt_base_m: 25, alt_step_m: 5, alt_ceiling_m: 120, layers: 4,
        });
        this.flIndex = this.flightLevels().length - 1;
        await this.saveProfiles();
        this.renderFlightLevels();
    },

    async renameFlightLevel() {
        const fl = this.flightLevels()[this.flIndex];
        const v = await UI.form({
            title: 'Renombrar plantilla',
            fields: [{ name: 'name', label: 'Nombre', value: fl.name }],
        });
        if (!v || !v.name) return;
        fl.name = v.name;
        await this.saveProfiles();
        this.renderFlightLevels();
    },

    async deleteFlightLevel() {
        const plantillas = this.flightLevels();
        if (plantillas.length <= 1) {
            return UI.alert('Debe quedar al menos una plantilla.', 'No se puede eliminar');
        }
        const fl = plantillas[this.flIndex];
        if (!(await UI.confirm(`¿Eliminar la plantilla "${fl.name}"?`, 'Eliminar'))) return;
        plantillas.splice(this.flIndex, 1);
        this.flIndex = 0;
        await this.saveProfiles();
        this.renderFlightLevels();
    },

    // Lleva la plantilla al escenario operacional de ESTE escenario de rutas.
    async applyFlightLevel() {
        const fl = this.flightLevels()[this.flIndex];
        const destino = (this.scenarios || []).find(
            s => s.route_profile_name === this.profile?.name);
        const aviso = document.getElementById('fl-status');
        if (!destino) {
            aviso.textContent = 'Abre la pestaña Enjambre una vez para crear '
                + 'los parámetros de este escenario.';
            return;
        }
        try {
            await this.swarmFetch(
                `/api/admin/scenarios/${encodeURIComponent(destino.name)}`, 'PUT', {
                    alt_base_m: Number(fl.alt_base_m),
                    alt_step_m: Number(fl.alt_step_m),
                    alt_ceiling_m: Number(fl.alt_ceiling_m),
                });
            await this.saveProfiles();
            aviso.textContent = `Aplicada a «${destino.route_profile_name}».`;
            this.loadScenarios();
        } catch (e) {
            aviso.textContent = e.message;
        }
    },

    async saveProfiles() {
        if (this.profile) {
            this.profile.speed = parseFloat(document.getElementById('profile-speed').value) || 7;
        }
        const res = await fetch('/api/admin/profiles', {
            method: 'PUT', headers: this.authHeaders(), body: JSON.stringify(this.data),
        });
        const d = await res.json();
        document.getElementById('routes-status').innerText =
            d.success ? 'Cambios guardados.' : ('Error: ' + (d.error || ''));
    },

    // ── Pedidos / flota ──────────────────────────────────────────────────
    showTab(tab) {
        // Cambiar de apartado devuelve el mapa a la vista general: dejar el
        // foco de un pedido puesto al salir desconcierta.
        this.clearOrderFocus();
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
        ['routes', 'orders', 'accounts', 'swarm'].forEach(t =>
            document.getElementById('tab-' + t).classList.toggle('active', t === tab));
        if (tab === 'orders') this.loadOrders();
        if (tab === 'routes') this.drawProfile();
        if (tab === 'accounts') this.loadAccounts();
        // El sondeo debe pararse al salir, o sigue pidiendo la flota cada
        // segundo aunque la pestaña no se vea.
        if (tab === 'swarm') { this.startSwarmPolling(); } else { this.stopSwarmPolling(); }
    },

    // ── Enjambre ─────────────────────────────────────────────────────────
    swarmTimer: null,

    async swarmFetch(path, method = 'GET', body = null) {
        const opciones = { method, headers: this.authHeaders() };
        if (body !== null) {
            opciones.headers = { ...opciones.headers, 'Content-Type': 'application/json' };
            opciones.body = JSON.stringify(body);
        }
        const res = await fetch(path, opciones);
        if (res.status === 401) { this.logout(); throw new Error('Sesión caducada'); }
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
        return data;
    },

    // ── Escenarios ───────────────────────────────────────────────────────
    scenarios: [],
    scenarioName: null,

    // Los parametros editables, agrupados como se presentan en el panel.
    SCENARIO_FIELDS: [
        // parking_lat/lon ya no se teclean: salen del parking que se elige
        // arriba y se dibuja en Rutas. Dejarlos editables permitia guardar
        // unas coordenadas y operar con otras.
        ['Geometría', [
            ['pad_spacing_m', 'Separación pads (m)'],
            ['alt_base_m', 'Altitud base (m)'], ['alt_step_m', 'Salto capas (m)'],
            ['alt_ceiling_m', 'Techo (m)'], ['geofence_radius_m', 'Geovalla (m)'],
        ]],
        ['Separación', [
            ['separation_min_m', 'Separación mín. (m)'],
            ['takeoff_gap_s', 'Escalonado (s)'],
            ['waypoint_tolerance_m', 'Tolerancia wp (m)'],
            // 0/1 en vez de casilla: el formulario entero se lee con
            // parseFloat y un booleano suelto obligaria a un caso especial.
            // La columna es Boolean y SQLAlchemy convierte el 0/1.
            ['hub_exclusive', 'Hub exclusivo (1 sí / 0 no)'],
            ['hub_capacity', 'Aforo del HUB (drones)'],
        ]],
        ['Seguridad', [
            ['battery_reserve_pct', 'Reserva batería (%)'],
            ['delivery_pause_s', 'Pausa entrega (s)'],
            ['delivery_stagger_s', 'Escalonado mismo destino (s)'],
        ]],
    ],

    async loadScenarios() {
        try {
            const data = await this.swarmFetch('/api/admin/scenarios');
            this.scenarios = data.scenarios;
            const activo = this.scenarios.find(s => s.active);
            this.scenarioName = this.scenarioName || (activo && activo.name);
            const sel = document.getElementById('scenario-select');
            // Se muestra el nombre del escenario de RUTAS, que es el que el
            // administrador reconoce y el que aparece en el otro apartado.
            // El name propio queda solo como identificador interno: enseñar
            // dos nombres para la misma cosa era la raiz de la confusion.
            sel.innerHTML = this.scenarios.map(s =>
                `<option value="${s.name}"${s.name === this.scenarioName ? ' selected' : ''}>` +
                `${s.orphan ? s.name : s.route_profile_name}` +
                `${s.active ? ' (activo)' : ''}` +
                `${s.orphan ? ' — sin rutas' : ''}` +
                `${s.duplicate ? ' — duplicado (' + s.name + ')' : ''}</option>`).join('');
            this.renderScenarioForm();
            // Solo la primera vez: redibujar en cada sondeo reencuadraria el
            // mapa una vez por segundo y no se podria ni mirar.
            if (!this.scenarioLayer) this.drawScenario();
        } catch (e) {
            document.getElementById('scenario-status').textContent = e.message;
        }
    },

    selectScenario(name) {
        this.scenarioName = name;
        this.renderScenarioForm();
        this.drawScenario();
    },

    // Dibuja el volumen operacional: parking y geovalla. Sin esto, elegir un
    // escenario solo cambiaba numeros en un formulario y no se veia nada, asi
    // que era imposible entender que es lo que define.
    drawScenario() {
        if (!this.map) return;
        if (!this.scenarioLayer) this.scenarioLayer = L.layerGroup().addTo(this.map);
        this.scenarioLayer.clearLayers();

        const s = this.scenarios.find(x => x.name === this.scenarioName);
        if (!s || s.parking_lat == null || s.parking_lon == null) return;

        const centro = [s.parking_lat, s.parking_lon];
        const radio = Number(s.geofence_radius_m) || 0;
        const activo = !!s.active;

        // El activo se pinta solido y el resto punteado: deja ver de un
        // vistazo cual manda de verdad, que es la confusion habitual entre
        // "seleccionado en el desplegable" y "activo".
        if (radio > 0) {
            L.circle(centro, {
                radius: radio,
                color: activo ? '#43a047' : '#9e9e9e',
                weight: 2,
                dashArray: activo ? null : '6, 6',
                fillColor: activo ? '#43a047' : '#9e9e9e',
                fillOpacity: 0.06,
            }).addTo(this.scenarioLayer);
        }

        L.marker(centro, { icon: makeBadge(activo ? '#43a047' : '#9e9e9e', 'P', 26) })
            .addTo(this.scenarioLayer);

        this.renderGeofenceBadge(s, radio, activo);

        // Encuadra la geovalla entera: cambiar de escenario debe llevarte
        // hasta el, aunque este a 25 km.
        if (radio > 0) {
            this.map.fitBounds(L.circle(centro, { radius: radio }).getBounds(),
                { padding: [40, 40] });
        } else {
            this.map.setView(centro, 15);
        }
    },

    // Selector del parking que usa el escenario. Las coordenadas ya no se
    // teclean: se elige uno de los parkings dibujados en Rutas, que es la
    // unica fuente. Antes habia dos juegos de coordenadas que podian discrepar
    // sin que nada avisara.
    renderParkingLink(s) {
        const box = document.getElementById('scenario-parking');
        if (!box) return;
        const opciones = s.parking_options || [];
        const actual = s.parking_name || '';

        if (s.orphan || s.duplicate) {
            const motivo = s.orphan
                ? `apuntan a «${s.route_profile_name}», un escenario de rutas que ya no existe`
                : `son un segundo juego de parámetros para «${s.route_profile_name}», que ya tiene el suyo`;
            box.innerHTML = `<p class="scenario-mismatch">
                Estos parámetros (${s.name}) ${motivo}.
                <button class="secondary small"
                        onclick="admin.deleteScenario('${s.name}')">Eliminar</button></p>`;
            return;
        }

        if (!opciones.length) {
            box.innerHTML = `<p class="scenario-help">El escenario
                «${s.route_profile_name}» no tiene parkings. Dibuja uno en
                <b>Rutas</b> para poder enlazarlo.</p>`;
            return;
        }

        box.innerHTML = `
          <label>Parking (de «${s.route_profile_name}»)</label>
          <select id="sc-parking-name" onchange="admin.setParkingName(this.value)">
            <option value=""${actual ? '' : ' selected'}>— coordenadas guardadas —</option>
            ${opciones.map(o =>
                `<option value="${o}"${o === actual ? ' selected' : ''}>${o}</option>`).join('')}
          </select>
          <p class="scenario-help">
            Define d&oacute;nde nacen los drones y d&oacute;nde se centra la geovalla.
            Se edita en <b>Rutas</b>, sobre el mapa.
            Ahora mismo: ${Number(s.parking_lat).toFixed(5)}, ${Number(s.parking_lon).toFixed(5)}
          </p>
          ${s.parking_mismatch ? `<p class="scenario-mismatch">
            Las coordenadas guardadas no coinciden con el parking del mapa.
            Manda el mapa.</p>` : ''}`;
    },

    async deleteScenario(nombre) {
        if (!(await UI.confirm(
            `¿Eliminar los parámetros operacionales de "${nombre}"?`,
            'Eliminar'))) return;
        try {
            await this.swarmFetch(
                `/api/admin/scenarios/${encodeURIComponent(nombre)}`, 'DELETE');
            this.scenarioName = null;
        } catch (e) {
            document.getElementById('scenario-status').textContent = e.message;
        }
        await this.loadScenarios();
        this.drawScenario();
    },

    async setParkingName(nombre) {
        try {
            await this.swarmFetch(
                `/api/admin/scenarios/${encodeURIComponent(this.scenarioName)}`,
                'PUT', { parking_name: nombre });
            document.getElementById('scenario-status').textContent =
                nombre ? `Parking enlazado: ${nombre}.` : 'Parking desenlazado.';
        } catch (e) {
            document.getElementById('scenario-status').textContent = e.message;
        }
        await this.loadScenarios();
        this.drawScenario();
    },

    renderScenarioForm() {
        const s = this.scenarios.find(x => x.name === this.scenarioName);
        if (!s) return;
        document.getElementById('scenario-warn')
            .classList.toggle('hidden', !s.coords_approximate);
        this.renderParkingLink(s);
        document.getElementById('scenario-form').innerHTML =
            this.SCENARIO_FIELDS.map(([titulo, campos]) =>
                `<div class="group-title">${titulo}</div>` +
                campos.map(([clave, etiqueta]) => {
                    // Los booleanos se editan como 0/1. Volcados tal cual,
                    // 'true' en un input numerico se ve como campo vacio y al
                    // guardar se pierde el valor.
                    const valor = typeof s[clave] === 'boolean'
                        ? (s[clave] ? 1 : 0) : s[clave];
                    return `
                  <div>
                    <label>${etiqueta}</label>
                    <input type="number" step="any" id="sc-${clave}" value="${valor}">
                  </div>`;
                }).join('')
            ).join('');
    },

    async saveScenario() {
        const cambios = {};
        for (const [, campos] of this.SCENARIO_FIELDS) {
            for (const [clave] of campos) {
                const valor = parseFloat(document.getElementById('sc-' + clave).value);
                if (!Number.isNaN(valor)) cambios[clave] = valor;
            }
        }
        try {
            await this.swarmFetch(
                `/api/admin/scenarios/${encodeURIComponent(this.scenarioName)}`,
                'PUT', cambios);
            document.getElementById('scenario-status').textContent = 'Parámetros guardados.';
        } catch (e) {
            document.getElementById('scenario-status').textContent = e.message;
        }
        this.loadScenarios();
    },

    async activateScenario() {
        try {
            await this.swarmFetch(
                `/api/admin/scenarios/${encodeURIComponent(this.scenarioName)}/activate`,
                'POST');
            document.getElementById('scenario-status').textContent =
                'Escenario activado. Reinicia el portal para reconectar la flota.';
        } catch (e) {
            document.getElementById('scenario-status').textContent = e.message;
        }
        await this.loadScenarios();
        this.drawScenario();   // el activo pasa a pintarse solido
    },

    // ── Diagnostico de enlace ────────────────────────────────────────────
    async probeFleet() {
        const caja = document.getElementById('swarm-probe');
        caja.innerHTML = '<div class="probe-row">probando enlaces...</div>';
        try {
            const data = await this.swarmFetch('/api/admin/swarm/probe', 'POST');
            caja.innerHTML = data.results.map(r => `
              <div class="probe-row ${r.ok ? 'ok' : 'ko'}">
                <b>${r.drone_id}</b>
                <input type="text" value="${r.connection}"
                       id="conn-${r.drone_id}" title="Puerto MAVLink">
                <span>${r.ok ? 'SYSID ' + r.sysid : (r.error || 'sin respuesta')}</span>
                <button class="secondary small"
                        onclick="admin.saveConnection('${r.drone_id}')">Guardar</button>
              </div>`).join('');
        } catch (e) {
            caja.innerHTML = `<div class="probe-row ko">${e.message}</div>`;
        }
    },

    async scanPorts() {
        const caja = document.getElementById('swarm-probe');
        caja.innerHTML = '<div class="probe-row">buscando en 5760-5800...</div>';
        try {
            const data = await this.swarmFetch('/api/admin/swarm/scan', 'POST');
            caja.innerHTML = data.found.length
                ? data.found.map(r => `
                    <div class="probe-row ok">
                      <b>SYSID ${r.sysid}</b>
                      <span>${r.connection}</span>
                      <span>${r.serial || ''}</span>
                      <span></span>
                    </div>`).join('')
                : '<div class="probe-row ko">Ningún autopiloto responde. '
                  + '¿Está arrancada la simulación?</div>';
        } catch (e) {
            caja.innerHTML = `<div class="probe-row ko">${e.message}</div>`;
        }
    },

    async reseatFleet() {
        try {
            await this.swarmFetch('/api/admin/swarm/reseat', 'POST');
            document.getElementById('swarm-status').textContent =
                'Puertos y pads recalculados. Reinicia el portal para reconectar.';
        } catch (e) {
            document.getElementById('swarm-status').textContent = e.message;
        }
        this.probeFleet();
    },

    async saveConnection(droneId) {
        const conexion = document.getElementById('conn-' + droneId).value.trim();
        try {
            await this.swarmFetch(
                `/api/admin/swarm/drones/${encodeURIComponent(droneId)}/connection`,
                'PUT', { connection: conexion });
            document.getElementById('swarm-status').textContent =
                `${droneId}: puerto guardado. Reinicia el portal para reconectar.`;
        } catch (e) {
            document.getElementById('swarm-status').textContent = e.message;
        }
    },

    async loadEvents() {
        try {
            const data = await this.swarmFetch('/api/admin/swarm/events');
            document.getElementById('swarm-events').innerHTML = data.events.map(e => `
              <div class="swarm-event ${e.kind}">
                <span>${e.at.slice(11, 19)}</span>
                <span class="kind">${e.kind}</span>
                <span>${e.drone_id}: ${e.reason}</span>
              </div>`).join('')
              || '<div class="swarm-event"><span></span><span></span><span>sin eventos</span></div>';
        } catch (e) {
            /* la pestaña ya muestra el error de la flota */
        }
    },

    // Origen de los drones con SITL: el de la nube o el del PC por el puente.
    // Solo aparece si el despliegue ofrece más de uno.
    renderSource(data) {
        const fila = document.getElementById('swarm-source-row');
        const sel = document.getElementById('swarm-source');
        const info = document.getElementById('swarm-pasarela');
        const origenes = data.sources || [];
        fila.classList.toggle('hidden', origenes.length < 2);
        if (document.activeElement !== sel && data.source) sel.value = data.source;
        const p = data.pasarela;
        info.textContent = !p ? '' :
            'Pasarela MAVLink: puerto ' + p.port
            + (p.agents.length ? ' — puente con ' + p.agents.length + ' dron(es)' : ' — sin puente')
            + (p.gcs_enabled ? ', Mission Planner ' + (p.gcs_clients ? 'conectado' : 'permitido') : '');
    },

    async setSource(origen) {
        const status = document.getElementById('swarm-status');
        status.textContent = origen === 'nube'
            ? 'Arrancando el SITL de la nube…' : 'Esperando al puente del PC…';
        try {
            await this.swarmFetch('/api/admin/swarm/source', 'POST', { source: origen });
            status.textContent = origen === 'nube'
                ? 'Drones: SITL en la nube.'
                : 'Drones: SITL del PC. Arranca el puente en el PC si no lo está.';
        } catch (e) {
            status.textContent = e.message;
        }
        await this.loadSwarm();
    },

    async loadSwarm() {
        try {
            const data = await this.swarmFetch('/api/admin/swarm/fleet');
            document.getElementById('swarm-backend').textContent =
                'Backend: ' + data.backend +
                (data.auto_running ? ' — despacho autónomo activo' : '') +
                (data.drones.length ? '' : ' — sin drones (arranca con DRONE_BACKEND=sitl)');
            this.renderSource(data);
            const sel = document.getElementById('swarm-algorithm');
            // Solo se pisa el selector si el usuario no lo tiene desplegado,
            // para no cambiarle la opcion bajo el raton en cada refresco.
            if (sel && data.algorithm && document.activeElement !== sel) {
                sel.value = data.algorithm;
            }
            this.renderSwarm(data.drones);
            this.renderFleetOnMap(data.drones);
        } catch (e) {
            document.getElementById('swarm-status').textContent = e.message;
        }
    },

    // Icono: dron (quadcopter visto desde arriba) con una etiqueta pegada al
    // lado que lleva el identificador y la altura viva. La etiqueta va dentro
    // del mismo divIcon en vez de como tooltip de Leaflet para que se mueva
    // pegada al dron sin un segundo elemento que reposicionar.
    droneIcon(droneId, alt, color) {
        const svg = '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" '
            + 'stroke="#fff" stroke-width="2" stroke-linecap="round">'
            + '<line x1="7" y1="7" x2="17" y2="17"/><line x1="17" y1="7" x2="7" y2="17"/>'
            + '<circle cx="6" cy="6" r="2.6"/><circle cx="18" cy="6" r="2.6"/>'
            + '<circle cx="6" cy="18" r="2.6"/><circle cx="18" cy="18" r="2.6"/>'
            + '<rect x="9.5" y="9.5" width="5" height="5" rx="1"/></svg>';
        return L.divIcon({
            className: '',
            iconSize: [32, 32],
            iconAnchor: [16, 16],
            html: `<div style="position:relative;width:32px;height:32px">`
                + `<div style="width:32px;height:32px;border-radius:50%;background:${color};`
                + `border:3px solid #fff;box-shadow:0 2px 5px rgba(0,0,0,.55);`
                + `display:flex;align-items:center;justify-content:center">${svg}</div>`
                + `<div style="position:absolute;left:38px;top:50%;transform:translateY(-50%);`
                + `background:rgba(0,0,0,.72);color:#fff;border-radius:4px;padding:2px 6px;`
                + `font:600 11px/1.35 sans-serif;white-space:nowrap">`
                + `${droneId}<br><span style="font-weight:400">${alt}</span></div>`
                + `</div>`,
        });
    },

    // Marcadores de toda la flota. El mapa solo pintaba el dron abierto en el
    // detalle, asi que durante un reparto no habia forma de ver donde estaba
    // el enjambre: justo lo que se quiere mirar cuando vuelan cuatro a la vez.
    renderFleetOnMap(drones) {
        if (!this.map) return;
        if (!this.fleetLayer) this.fleetLayer = L.layerGroup().addTo(this.map);
        this.fleetLayer.clearLayers();

        for (const d of drones) {
            const r = d.runtime;
            if (r.lat == null || r.lon == null) continue;
            // Sin fix, SITL reporta 0,0 y el marcador se iria al golfo de
            // Guinea arrastrando el encuadre del mapa con el.
            if (Math.abs(r.lat) < 0.001 && Math.abs(r.lon) < 0.001) continue;

            const id = d.record.drone_id;
            const volando = r.state && r.state !== 'idle' && r.state !== 'offline';
            const seguido = this.trackedDroneId === id;
            const color = seguido ? '#00bcd4'
                : (r.state === 'offline' ? '#9e9e9e' : (volando ? '#1e88e5' : '#43a047'));
            const alt = r.alt == null ? '—' : r.alt.toFixed(1) + ' m';

            L.marker([r.lat, r.lon], {
                icon: this.droneIcon(id, alt, color),
                zIndexOffset: seguido ? 1200 : 1000,
            }).on('click', () => this.trackDrone(id))
              .addTo(this.fleetLayer);

            if (seguido && this.followingDrone) {
                this.map.panTo([r.lat, r.lon], { animate: true });
            }
        }
        this.renderTrackedDetail(drones);
    },

    // Indicador fijo del volumen operacional. Sustituye al tooltip que seguia
    // al raton: lo que interesa es saber en todo momento dentro de que
    // geovalla se esta trabajando, no etiquetar una linea concreta.
    renderGeofenceBadge(s, radio, activo) {
        const badge = document.getElementById('geofence-badge');
        if (!badge) return;
        if (!s || !radio) { badge.classList.add('hidden'); return; }
        badge.classList.remove('hidden');
        badge.classList.toggle('inactive', !activo);
        badge.innerHTML = `<b>${s.route_profile_name || s.name}</b>`
            + `<span>geovalla ${radio.toFixed(0)} m</span>`
            + (activo ? '<span class="gb-on">activo</span>'
                      : '<span class="gb-off">solo vista previa</span>');
    },

    // Seguir un dron: centra el mapa y lo mantiene encuadrado. Se cancela en
    // cuanto el usuario arrastra el mapa, porque si el encuadre volviera solo
    // al dron no habria forma de mirar alrededor.
    trackDrone(droneId) {
        this.trackedDroneId = this.trackedDroneId === droneId ? null : droneId;
        this.followingDrone = this.trackedDroneId != null;
        if (!this._dragHooked) {
            this.map.on('dragstart', () => { this.followingDrone = false; });
            this._dragHooked = true;
        }
        this.loadSwarm();
    },

    renderTrackedDetail(drones) {
        const box = document.getElementById('tracked-drone');
        if (!box) return;
        const d = drones.find(x => x.record.drone_id === this.trackedDroneId);
        if (!d) { box.innerHTML = ''; box.classList.add('hidden'); return; }

        const r = d.runtime, rec = d.record;
        const f = (v, dec, u) => (v == null ? '—' : Number(v).toFixed(dec) + (u || ''));
        box.classList.remove('hidden');
        box.innerHTML = `
          <div class="tracked-head">
            <b>${rec.drone_id}</b>
            <span class="badge ${r.state}">${r.state}</span>
            <button class="secondary small" onclick="admin.trackDrone('${rec.drone_id}')">
              Dejar de seguir</button>
          </div>
          <div class="swarm-meta">
            <span>Categoría: ${rec.category}</span>
            <span>SYSID: ${rec.sysid}</span>
            <span>Batería: ${f(r.battery_pct, 0, '%')}</span>
            <span>Altitud: ${f(r.alt, 1, ' m')}</span>
            <span>Crucero asignado: ${f(r.cruise_alt_m, 0, ' m')}</span>
            <span>Velocidad: ${f(r.ground_speed, 1, ' m/s')}</span>
            <span>Rumbo: ${f(r.heading, 0, '°')}</span>
            <span>Latitud: ${f(r.lat, 6)}</span>
            <span>Longitud: ${f(r.lon, 6)}</span>
            <span>Pedido: ${r.current_order_id ?? '—'}</span>
            <span>Conexión: ${rec.connection}</span>
          </div>
          <div style="font-size:11px;margin-top:6px;">${r.detail || ''}</div>`;
    },

    renderSwarm(drones) {
        const box = document.getElementById('swarm-list');
        if (!drones.length) { box.innerHTML = ''; return; }
        box.innerHTML = drones.map(d => {
            const r = d.runtime, rec = d.record;
            const low = r.battery_pct < 25 ? ' low' : '';
            const pos = (r.lat != null && r.lon != null)
                ? r.lat.toFixed(5) + ', ' + r.lon.toFixed(5) : '—';
            const seguido = this.trackedDroneId === rec.drone_id;
            // El clic en la tarjeta sigue al dron; los botones de control
            // llevan stopPropagation para que pulsar RTL no cambie ademas el
            // encuadre del mapa.
            return `
              <div class="swarm-card${seguido ? ' tracking' : ''}"
                   style="cursor:pointer"
                   onclick="admin.trackDrone('${rec.drone_id}')">
                <div class="swarm-card-head">
                  <b>${rec.drone_id}</b>
                  <span class="badge ${r.state}">${r.state}</span>
                  ${seguido ? '<span class="badge">siguiendo</span>' : ''}
                </div>
                <div class="swarm-battery${low}"><span style="width:${r.battery_pct}%"></span></div>
                <div class="swarm-task">
                  <span class="st-order">${r.current_order_id != null
                      ? 'Pedido #' + r.current_order_id : 'Sin pedido'}</span>
                  <span class="st-detail">${r.detail || (r.state === 'idle'
                      ? 'en el pad, libre' : r.state)}</span>
                </div>
                <div class="swarm-meta">
                  <span>Categoría: ${rec.category}</span>
                  <span>Batería: ${r.battery_pct}%</span>
                  <span>Crucero: ${r.cruise_alt_m == null ? '—' : r.cruise_alt_m + ' m'}</span>
                  <span>Altitud: ${r.alt == null ? '—' : r.alt.toFixed(1) + ' m'}</span>
                  <span>Posición: ${pos}</span>
                </div>
                <div class="swarm-card-actions">
                  <button class="secondary small" onclick="event.stopPropagation();admin.swarmControl('${rec.drone_id}','hold')">Hold</button>
                  <button class="secondary small" onclick="event.stopPropagation();admin.swarmControl('${rec.drone_id}','rtl')">RTL</button>
                  <button class="secondary small" onclick="event.stopPropagation();admin.swarmControl('${rec.drone_id}','land')">Land</button>
                </div>
              </div>`;
        }).join('');
    },

    async loadMetrics() {
        const box = document.getElementById('swarm-metrics');
        try {
            const d = await this.swarmFetch('/api/admin/swarm/metrics');
            if (!d.summary.length) {
                box.innerHTML = '<p class="status-line">Aún no hay entregas medidas.</p>';
                return;
            }
            const n = (v, u) => (v == null ? '—' : v + (u || ''));
            box.innerHTML = `
              <table class="metrics-table">
                <tr><th>Algoritmo</th><th>Entregas</th><th>Fallos</th>
                    <th>Wh/entrega</th><th>Wh/km</th><th>s/entrega</th>
                    <th>Espera/entrega</th></tr>
                ${d.summary.map(f => `
                  <tr>
                    <td>${f.algorithm}</td>
                    <td>${f.delivered}</td>
                    <td>${f.failed}</td>
                    <td>${n(f.energy_wh_per_delivery)}</td>
                    <td>${n(f.energy_wh_per_km)}</td>
                    <td>${n(f.duration_s_per_delivery)}</td>
                    <td>${n(f.wait_s_per_delivery, ' s')}</td>
                  </tr>`).join('')}
              </table>
              <p class="status-line">Solo se promedian las entregas completadas:
                 mezclar los abortos abarataría al algoritmo que más falla.</p>`;
        } catch (e) {
            box.innerHTML = `<p class="status-line">${e.message}</p>`;
        }
    },

    async downloadMetrics() {
        // Se descarga con fetch y no con un enlace directo porque la ruta
        // exige el token de admin en la cabecera.
        try {
            const res = await fetch('/api/admin/swarm/metrics.csv',
                { headers: { 'Authorization': 'Bearer ' + this.token } });
            if (!res.ok) throw new Error('No se pudo descargar el CSV');
            const url = URL.createObjectURL(await res.blob());
            const a = document.createElement('a');
            a.href = url;
            a.download = 'airdrop-metrics.csv';
            a.click();
            URL.revokeObjectURL(url);
        } catch (e) {
            document.getElementById('swarm-metrics').innerHTML =
                `<p class="status-line">${e.message}</p>`;
        }
    },

    async clearMetrics() {
        try {
            await this.swarmFetch('/api/admin/swarm/metrics/clear', 'POST');
            this.loadMetrics();
        } catch (e) {
            document.getElementById('swarm-metrics').innerHTML =
                `<p class="status-line">${e.message}</p>`;
        }
    },

    async setAlgorithm(algorithm) {
        try {
            const r = await this.swarmFetch('/api/admin/swarm/algorithm', 'POST',
                { algorithm });
            document.getElementById('swarm-status').textContent =
                'Asignación: ' + r.algorithm;
        } catch (e) {
            document.getElementById('swarm-status').textContent = e.message;
            this.loadSwarm();   // devuelve el selector al valor real
        }
    },

    async swarmStart() {
        try {
            const r = await this.swarmFetch('/api/admin/swarm/start', 'POST');
            let texto = (r.dispatched.length
                ? 'Lanzados: ' + r.dispatched.map(d => d.drone_id + '→#' + d.order_id).join(', ')
                : 'Sin drones libres ahora mismo.')
                + ' Despacho autónomo activo: la cola se irá vaciando sola.';
            document.getElementById('swarm-status').textContent = texto;

            // Los pedidos que nadie va a poder llevar se avisan de inmediato:
            // callados se quedan en la cola para siempre y parece que el
            // enjambre ha dejado de repartir.
            const box = document.getElementById('swarm-blocked');
            const bloqueados = r.undispatchable || [];
            if (!bloqueados.length) {
                box.classList.add('hidden');
                box.innerHTML = '';
            } else {
                box.classList.remove('hidden');
                box.innerHTML =
                    `<b>${bloqueados.length} pedido(s) que ningún dron puede llevar:</b>`
                    + '<ul>' + bloqueados.map(b =>
                        `<li>#${b.order_id} (${b.weight_kg} kg): ${b.reason}</li>`).join('')
                    + '</ul>';
            }
        } catch (e) {
            document.getElementById('swarm-status').textContent = e.message;
        }
        this.loadSwarm();
    },

    // Demostración: siembra la oleada de ocho pedidos (python -m airdrop.demo
    // seed oleada --seed 42) sin dar de alta clientes delante del público.
    async demoSeed() {
        const status = document.getElementById('swarm-status');
        try {
            await this.swarmFetch('/api/admin/demo/oleada?semilla=42', 'POST');
            status.textContent = 'Oleada de demostración sembrada. Pulsa «Iniciar repartos».';
        } catch (e) {
            status.textContent = e.message;
        }
    },

    async demoClear() {
        const status = document.getElementById('swarm-status');
        try {
            await this.swarmFetch('/api/admin/demo/clear', 'POST');
            status.textContent = 'Pedidos de demostración borrados.';
        } catch (e) {
            status.textContent = e.message;
        }
    },

    async swarmStop() {
        try {
            await this.swarmFetch('/api/admin/swarm/stop', 'POST');
            document.getElementById('swarm-status').textContent = 'Abortando entregas...';
        } catch (e) {
            document.getElementById('swarm-status').textContent = e.message;
        }
        this.loadSwarm();
    },

    async swarmControl(droneId, action) {
        try {
            await this.swarmFetch(`/api/admin/swarm/drones/${droneId}/${action}`, 'POST');
            document.getElementById('swarm-status').textContent = droneId + ': ' + action;
        } catch (e) {
            document.getElementById('swarm-status').textContent = e.message;
        }
        this.loadSwarm();
    },

    startSwarmPolling() {
        this.stopSwarmPolling();
        this.loadScenarios();
        this.loadSwarm();
        this.loadEvents();
        // El formulario de escenario NO se refresca en el sondeo: sobrescribiria
        // lo que estas escribiendo mientras editas.
        this.swarmTimer = setInterval(() => {
            this.loadSwarm();
            this.loadEvents();
        }, 1000);
    },

    stopSwarmPolling() {
        if (this.swarmTimer) { clearInterval(this.swarmTimer); this.swarmTimer = null; }
    },

    // Los drones tienen que verse en el mapa desde cualquier pestaña: mirar
    // pedidos o perfiles mientras vuelan es justo cuando mas falta hace. El
    // sondeo de la pestaña Enjambre sigue siendo aparte porque ademas trae
    // eventos y escenario, que solo se ven alli.
    startFleetMapPolling() {
        this.stopFleetMapPolling();
        this.refreshFleetMap();
        this.fleetMapTimer = setInterval(() => this.refreshFleetMap(), 1500);
    },

    stopFleetMapPolling() {
        if (this.fleetMapTimer) {
            clearInterval(this.fleetMapTimer);
            this.fleetMapTimer = null;
        }
    },

    async refreshFleetMap() {
        // En la pestaña Enjambre ya lo hace loadSwarm; repetirlo aqui seria
        // pedir la flota dos veces por segundo para nada.
        if (this.swarmTimer) return;
        try {
            const data = await this.swarmFetch('/api/admin/swarm/fleet');
            this.renderFleetOnMap(data.drones);
        } catch (e) { /* sin enjambre: no hay nada que pintar */ }
    },

    async loadAccounts() {
        const res = await fetch('/api/admin/clients', { headers: this.authHeaders() });
        if (res.status === 401) return this.logout();
        const d = await res.json();
        const list = document.getElementById('accounts-list');
        if (!d.clients || !d.clients.length) { list.innerHTML = '<li class="muted">Sin cuentas.</li>'; return; }
        list.innerHTML = d.clients.map(c =>
            `<li><span>${c.name}<br><small class="muted">${c.address}</small></span>`
            + `<button class="x" title="Editar" onclick='admin.editClient(${c.id}, ${JSON.stringify(c.name)}, ${JSON.stringify(c.address)})'>✎</button></li>`).join('');
    },

    async editClient(id, name, address) {
        const r = await UI.form({
            title: 'Editar cuenta',
            fields: [
                { name: 'name', label: 'Nombre', value: name },
                { name: 'address', label: 'Dirección', value: address },
            ],
            submitLabel: 'Guardar',
        });
        if (!r) return;
        const res = await fetch(`/api/admin/clients/${id}`, {
            method: 'PUT', headers: this.authHeaders(),
            body: JSON.stringify({ name: r.name, address: r.address }),
        });
        const d = await res.json();
        if (d.error) return UI.alert(d.error, 'Error');
        this.loadAccounts();
    },

    async loadFleet() {
        const res = await fetch('/api/admin/fleet', { headers: this.authHeaders() });
        if (!res.ok) return;
        const d = await res.json();
        document.getElementById('fleet-box').innerHTML = d.fleet.map(f => {
            const c = d.categories[f.category];
            return `<div class="fleet-item"><b>${f.id}</b> <span class="muted">${f.category} · ${c.max_payload_kg}kg · ${c.battery_capacity_wh}Wh</span></div>`;
        }).join('');
    },

    async loadOrders() {
        const res = await fetch('/api/admin/orders', { headers: this.authHeaders() });
        if (res.status === 401) return this.logout();
        const d = await res.json();
        this.orders = d.orders || [];
        const list = document.getElementById('admin-orders-list');
        if (!this.orders.length) { list.innerHTML = '<p class="muted">No hay pedidos.</p>'; return; }
        list.innerHTML = this.orders.map(o => `
            <div class="order-card admin-order" onclick="admin.showOrderRoute(${o.id})">
                <div class="order-info">
                    <span class="order-id">#${o.id} · ${o.client_name || ''}</span>
                    <span class="order-meta">${o.weight_kg}kg · ${o.assigned_destination_name || '—'}
                        · <span class="badge ${o.status}">${o.status}</span></span>
                </div>
                <div class="order-actions" onclick="event.stopPropagation()">
                    ${this.hasDrone
                        ? `<button class="mini" title="Empezar misión" onclick="admin.dispatch(${o.id})">▶ Misión</button>`
                        : `<button class="mini" title="Marcar en reparto" onclick="admin.setState(${o.id},'en_reparto','en reparto')">▶</button>`
                          + `<button class="mini" title="Marcar entregado" onclick="admin.setState(${o.id},'entregado','entregado')">✓</button>`}
                    <button class="mini danger" title="Borrar" onclick="admin.deleteOrder(${o.id})">✕</button>
                </div>
            </div>`).join('');
    },

    async setState(id, status, op) {
        await fetch(`/api/admin/orders/${id}/state`, {
            method: 'POST', headers: this.authHeaders(),
            body: JSON.stringify({ status, operational_state: op }),
        });
        this.loadOrders();
    },

    // Vuelve al encuadre general (todas las rutas del perfil). El foco en un
    // pedido se quedaba pegado hasta refrescar la pagina: pintaba su ruta en
    // la misma capa que el perfil y nadie la restauraba.
    clearOrderFocus() {
        if (this.focusedOrderId == null) return;
        this.focusedOrderId = null;
        this.drawProfile();
    },

    showOrderRoute(id) {
        // Volver a pulsar el mismo pedido devuelve la vista general, que es
        // lo que uno espera de un foco.
        if (this.focusedOrderId === id) return this.clearOrderFocus();
        const o = this.orders.find(x => x.id === id);
        if (!o || !o.route_waypoints || !o.route_waypoints.length) return;
        this.focusedOrderId = id;
        this.layer.clearLayers();
        const ll = o.route_waypoints.map(w => [w.lat, w.lon]);
        L.polyline(ll, { color: '#ffffff', weight: 7, opacity: 0.85 }).addTo(this.layer);
        L.polyline(ll.slice(0, -1), { color: '#00bcd4', weight: 4 }).addTo(this.layer);
        L.polyline(ll.slice(-2), { color: '#ff7043', weight: 4, dashArray: '6, 8' }).addTo(this.layer);
        this.marker(ll[0], '#43a047', 'P', 'Parking');
        this.marker(ll[ll.length - 1], '#ff7043', '⌂', o.client_name || 'Cliente');
        this.map.fitBounds(ll, { padding: [50, 50], maxZoom: 16 });
    },

    async deleteOrder(id) {
        if (!(await UI.confirm('¿Borrar el pedido #' + id + '?'))) return;
        await fetch(`/api/admin/orders/${id}`, { method: 'DELETE', headers: this.authHeaders() });
        this.loadOrders();
    },

    async dispatch(id) {
        const res = await fetch(`/api/admin/orders/${id}/dispatch`, { method: 'POST', headers: this.authHeaders() });
        const d = await res.json();
        if (d.error) return UI.alert(d.error, 'Error');
        await UI.alert('Misión iniciada. El estado del pedido se actualizará solo '
            + 'mientras el dron vuela.', 'Misión');
        this.loadOrders();
    },

    async droneControl(action) {
        const labels = { cancel: 'Cancelar misión', hold: 'Mantener posición',
            rtl: 'Volver a base (RTL)', land: 'Aterrizar' };
        if (!(await UI.confirm(labels[action] + '?', 'Operación del dron'))) return;
        const res = await fetch(`/api/admin/drone/${action}`, { method: 'POST', headers: this.authHeaders() });
        const d = await res.json();
        if (d.error) return UI.alert(d.error, 'Error');
        await UI.alert('Orden enviada: ' + labels[action] + '.', 'Operación');
    },
};

window.addEventListener('load', () => {
    if (document.getElementById('admin-map')) admin.init();
});
