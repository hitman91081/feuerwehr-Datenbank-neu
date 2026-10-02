// === State ===
let token = localStorage.getItem('token') || '';
let currentUser = null;
let masterData = { types: [], manufacturers: [], suppliers: [], locations: [], documentLabels: [] };
let scanner = null;
let currentView = 'dashboard';
let currentDetailObject = null;
let navigationReady = false;
const APP_HISTORY_KEY = 'feuerwehr-inventar';
const APP_HISTORY_VERSION = 2;

// === API Helper ===
async function api(url, opts = {}) {
    const headers = { 'Content-Type': 'application/json', ...opts.headers };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(url, { ...opts, headers });
    if (res.status === 401) { logout(); throw new Error('Nicht autorisiert'); }
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Fehler ${res.status}`);
    }
    if (res.status === 204) return null;
    return res.json();
}

async function uploadFile(url, formData) {
    const response = await fetch(url, {
        method: 'POST',
        headers: token ? { 'Authorization': `Bearer ${token}` } : {},
        body: formData
    });
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || `Upload fehlgeschlagen (${response.status})`);
    }
    return response.json();
}

// === Auth ===
async function handleLogin(e) {
    e.preventDefault();
    const user = document.getElementById('login-user').value;
    const pass = document.getElementById('login-pass').value;
    try {
        const data = await api('/api/auth/login', {
            method: 'POST',
            body: JSON.stringify({ username: user, password: pass })
        });
        token = data.access_token;
        localStorage.setItem('token', token);
        await initApp();
    } catch (err) {
        alert('Anmeldung fehlgeschlagen: ' + err.message);
    }
}

async function handleQrLogin() {
    try {
        const data = await api('/api/auth/qr-login', { method: 'POST' });
        token = data.access_token;
        localStorage.setItem('token', token);
        await initApp();
    } catch (err) {
        alert('QR-Login fehlgeschlagen: ' + err.message);
    }
}

async function initApp() {
    try {
        currentUser = await api('/api/auth/me');
    } catch { return logout(); }

    document.getElementById('login-screen').classList.add('hidden');
    document.getElementById('app-screen').classList.remove('hidden');
    document.getElementById('user-name').textContent = currentUser.full_name;

    const isAdmin = currentUser.role === 'admin';
    const isVerwaltung = currentUser.role === 'verwaltung';
    const isErweitert = currentUser.role === 'erweitert';
    const canEdit = isAdmin || isVerwaltung || isErweitert;

    if (canEdit) {
        document.getElementById('nav-new-object').classList.remove('hidden');
        document.getElementById('dash-new').classList.remove('hidden');
        document.getElementById('nav-bulk-create').classList.remove('hidden');
        document.getElementById('dash-bulk-create').classList.remove('hidden');
        document.getElementById('nav-message-archive').classList.remove('hidden');
        document.getElementById('dash-message-archive').classList.remove('hidden');
    }
    if (isAdmin) {
        document.getElementById('nav-admin').classList.remove('hidden');
    }
    if (isAdmin || isVerwaltung) {
        document.getElementById('nav-inspection-center').classList.remove('hidden');
        document.getElementById('dash-inspection-center').classList.remove('hidden');
        initializeInspectionCenterDates();
    }

    await loadMasterData();
    await initNavigation();
    loadDashboardAlerts();
    loadDashboardMessages();
    startDashboardAutoRefresh();
}

function logout() {
    token = '';
    localStorage.removeItem('token');
    currentUser = null;
    location.reload();
}

// === Views ===
let dashboardRefreshInterval = null;

function showView(name, options = {}) {
    if (name === 'inspection-center' && !canAccessInspectionCenter()) {
        alert('Die Prüfzentrale ist nur für Verwaltung und Administratoren verfügbar.');
        name = 'dashboard';
    }
    if (name === 'admin' && (!currentUser || currentUser.role !== 'admin')) {
        alert('Die Benutzer- und Systemverwaltung ist nur für Administratoren verfügbar.');
        name = 'dashboard';
    }
    if (name === 'message-archive' && (!currentUser || currentUser.role === 'standard')) {
        alert('Das Meldungsarchiv ist nur für erweiterte Nutzer, Verwaltung und Administratoren verfügbar.');
        name = 'dashboard';
    }
    if (name === 'bulk-create' && (!currentUser || currentUser.role === 'standard')) {
        alert('Die Sammelanlage ist nur für erweiterte Nutzer, Verwaltung und Administratoren verfügbar.');
        name = 'dashboard';
    }
    if (currentView === 'scanner' && name !== 'scanner') {
        cleanupScannerSession();
    }
    if (currentView === 'document' && name !== 'document') {
        closeDocumentPreview();
    }

    currentView = name;
    document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
    document.getElementById('view-' + name).classList.remove('hidden');
    closeMenu();
    window.scrollTo(0, 0);
    // Auto-load all objects when switching to search view
    if (name === 'search') {
        applyFilters();
    }
    if (name === 'admin') {
        refreshAdminTab();
    }
    if (name === 'inspection-center') {
        initializeInspectionCenterDates();
        loadInspectionCenter();
    }
    if (name === 'message-archive') {
        loadMessageArchive();
    }
    if (name === 'documents') {
        initializeDocumentCollection();
    }
    // Dashboard-Meldungen aktualisieren, wenn wir zurück zum Dashboard wechseln
    if (name === 'dashboard') {
        loadDashboardMessages();
        loadDashboardAlerts();
    }

    if (navigationReady && !options.skipHistory) {
        updateBrowserHistory(name, options.historyData || {}, options.replaceHistory === true);
    } else {
        updateBackButton();
    }
}

function routeHash(name, data = {}) {
    if (name === 'detail' && data.objectId) return '#object/' + data.objectId;
    if (name === 'location-objects' && data.locationId) return '#location/' + data.locationId;
    if (name === 'edit-object' && data.objectId) return '#object/' + data.objectId + '/edit';
    if (name === 'edit-object') return '#new-object';
    if (name === 'document') return '#document';
    return '#' + name;
}

function updateBrowserHistory(name, data = {}, replace = false) {
    const currentState = history.state;
    const sameRoute = currentState && currentState.app === APP_HISTORY_KEY &&
        currentState.view === name && JSON.stringify(currentState.data || {}) === JSON.stringify(data || {});
    const navigationIndex = replace || sameRoute
        ? (currentState && currentState.app === APP_HISTORY_KEY ? currentState.navigationIndex || 0 : 0)
        : (currentState && currentState.app === APP_HISTORY_KEY ? (currentState.navigationIndex || 0) + 1 : 1);
    const state = { app: APP_HISTORY_KEY, version: APP_HISTORY_VERSION, view: name, data, navigationIndex };
    const url = new URL(window.location.href);
    url.searchParams.delete('qrlogin');
    url.hash = routeHash(name, data);

    if (replace || sameRoute || !currentState || currentState.app !== APP_HISTORY_KEY) {
        history.replaceState(state, '', url);
    } else {
        history.pushState(state, '', url);
    }
    updateBackButton();
}

function routeFromLocation() {
    if (history.state && history.state.app === APP_HISTORY_KEY) return history.state;

    const hash = window.location.hash.replace(/^#/, '');
    let match = hash.match(/^object\/(\d+)\/edit$/);
    if (match) return { view: 'edit-object', data: { objectId: Number(match[1]) } };
    match = hash.match(/^object\/(\d+)$/);
    if (match) return { view: 'detail', data: { objectId: Number(match[1]) } };
    match = hash.match(/^location\/(\d+)$/);
    if (match) return { view: 'location-objects', data: { locationId: Number(match[1]), locationName: 'Standort' } };

    const knownViews = ['dashboard', 'search', 'admin', 'inspection-center', 'message-archive', 'documents', 'new-object', 'bulk-create'];
    if (knownViews.includes(hash)) {
        return { view: hash === 'new-object' ? 'edit-object' : hash, data: {} };
    }
    return { view: 'dashboard', data: {} };
}

async function initNavigation() {
    let route = routeFromLocation();
    const query = new URLSearchParams(window.location.search).get('q');
    route = installHistoryBoundary(route);
    navigationReady = true;

    if (query) {
        document.getElementById('search-input').value = query;
        showView('search', { replaceHistory: true });
        return;
    }

    await restoreRoute(route, true);
}

function installHistoryBoundary(initialRoute) {
    const currentState = history.state;
    if (currentState && currentState.app === APP_HISTORY_KEY && currentState.version === APP_HISTORY_VERSION) {
        return currentState.boundary ? { view: 'dashboard', data: {} } : currentState;
    }

    const cleanUrl = new URL(window.location.href);
    cleanUrl.searchParams.delete('qrlogin');
    cleanUrl.hash = '#dashboard';
    history.replaceState({
        app: APP_HISTORY_KEY,
        version: APP_HISTORY_VERSION,
        boundary: true,
        view: 'dashboard',
        data: {},
        navigationIndex: 0
    }, '', cleanUrl);

    const route = initialRoute && initialRoute.view ? initialRoute : { view: 'dashboard', data: {} };
    const routeUrl = new URL(cleanUrl);
    routeUrl.hash = routeHash(route.view, route.data || {});
    const visibleState = {
        app: APP_HISTORY_KEY,
        version: APP_HISTORY_VERSION,
        view: route.view,
        data: route.data || {},
        navigationIndex: 1
    };
    history.pushState(visibleState, '', routeUrl);
    return visibleState;
}

async function restoreRoute(route, replaceHistory = false) {
    const view = route && route.view ? route.view : 'dashboard';
    const data = route && route.data ? route.data : {};

    if (view === 'detail' && data.objectId) {
        await openObject(data.objectId, { replaceHistory });
        return;
    }
    if (view === 'location-objects' && data.locationId) {
        await showObjectsByLocation(data.locationId, data.locationName || 'Standort', { replaceHistory });
        return;
    }
    if (view === 'edit-object' && data.objectId) {
        await editObject(data.objectId, { replaceHistory });
        return;
    }
    if (view === 'edit-object') {
        openNewObjectForm({ replaceHistory });
        return;
    }
    if (view === 'bulk-create') {
        openBulkCreateForm({ replaceHistory });
        return;
    }
    if (view === 'document' && data.url) {
        openDocumentPreview(data.url, data.name || 'Dokument', { replaceHistory });
        return;
    }
    // Den Scanner nach einem Reload nicht ungefragt erneut auf die Kamera zugreifen lassen.
    showView(view === 'scanner' ? 'dashboard' : view, { replaceHistory });
}

function navigateBack(fallbackView = 'dashboard') {
    const state = history.state;
    if (state && state.app === APP_HISTORY_KEY && state.navigationIndex > 1) {
        history.back();
        return;
    }
    showView(fallbackView, { replaceHistory: true });
}

function updateBackButton() {
    const button = document.getElementById('header-back');
    if (!button) return;
    button.classList.toggle('hidden', currentView === 'dashboard');
}

window.addEventListener('popstate', async (event) => {
    if (!currentUser) return;
    if (event.state && event.state.app === APP_HISTORY_KEY && event.state.boundary) {
        history.forward();
        return;
    }
    cleanupScannerSession();
    const route = event.state && event.state.app === APP_HISTORY_KEY
        ? event.state
        : routeFromLocation();
    try {
        await restoreRoute(route, true);
    } catch (error) {
        console.error('Navigation konnte nicht wiederhergestellt werden:', error);
        showView('dashboard', { replaceHistory: true });
    }
});

function startDashboardAutoRefresh() {
    if (dashboardRefreshInterval) return;
    dashboardRefreshInterval = setInterval(() => {
        if (currentView === 'dashboard') {
            loadDashboardMessages();
            loadDashboardAlerts();
        }
    }, 30000); // Alle 30 Sekunden aktualisieren
}

function toggleMenu() {
    const menu = document.getElementById('mobile-menu');
    const toggle = document.getElementById('menu-toggle');
    const willOpen = menu.classList.contains('hidden');
    if (!willOpen) {
        closeMenu();
        return;
    }
    const headerBottom = Math.max(0, Math.round(document.querySelector('.app-header').getBoundingClientRect().bottom));
    menu.style.top = `${headerBottom}px`;
    menu.style.maxHeight = `calc(100dvh - ${headerBottom}px)`;
    menu.classList.remove('hidden');
    toggle.setAttribute('aria-expanded', 'true');
}

function closeMenu() {
    const menu = document.getElementById('mobile-menu');
    const toggle = document.getElementById('menu-toggle');
    if (menu) menu.classList.add('hidden');
    if (toggle) toggle.setAttribute('aria-expanded', 'false');
}

// === Master Data ===
async function loadMasterData() {
    masterData.types = await api('/api/object-types');
    masterData.manufacturers = await api('/api/manufacturers');
    masterData.suppliers = await api('/api/suppliers');
    masterData.documentLabels = await api('/api/document-labels');
    // Wichtig: /api/locations/all gibt ALLE Standorte als flache Liste zurück
    const allLocations = await api('/api/locations/all');
    masterData.locations = buildLocationTree(allLocations);
    masterData.locationsFlat = allLocations;

    fillSelect('obj-type', masterData.types, 'name');
    fillSelect('obj-manufacturer', masterData.manufacturers, 'name');
    fillSelect('obj-supplier', masterData.suppliers, 'name');
    fillSelect('obj-document-label', masterData.documentLabels, 'name');
    fillSelect('obj-location', allLocations.map(l => ({ id: l.id, name: getLocationPath(allLocations, l.id) })), 'name');
    renderObjectLocationSelector(document.getElementById('obj-location')?.value || null);
    fillSelect('new-location-parent', allLocations.map(l => ({ id: l.id, name: getLocationPath(allLocations, l.id) })), 'name');

    // Filter-Dropdowns füllen
    fillFilterSelect('filter-type', masterData.types, 'name');
    fillFilterSelect('filter-location', allLocations.map(l => ({ id: l.id, name: getLocationPath(allLocations, l.id) })), 'name');
    fillFilterSelect('filter-manufacturer', masterData.manufacturers, 'name');

    // Typ-Änderung: Zeige "Als Standort anlegen" nur bei Fahrzeugen
    const typeSel = document.getElementById('obj-type');
    if (typeSel) {
        typeSel.onchange = () => {
            const selected = masterData.types.find(t => t.id == typeSel.value);
            const box = document.getElementById('vehicle-location-box');
            if (selected && selected.name === 'Fahrzeug') {
                box.classList.remove('hidden');
            } else {
                box.classList.add('hidden');
            }
        };
    }
}

function buildLocationTree(locations) {
    // Baut Baumstruktur aus flacher Liste
    const locMap = {};
    locations.forEach(l => {
        locMap[l.id] = { ...l, children: [] };
    });
    const roots = [];
    locations.forEach(l => {
        if (l.parent_id && locMap[l.parent_id]) {
            locMap[l.parent_id].children.push(locMap[l.id]);
        } else {
            roots.push(locMap[l.id]);
        }
    });
    return roots;
}

function getLocationPath(allLocations, locationId) {
    if (!locationId || !allLocations) return '';
    const locMap = {};
    allLocations.forEach(l => locMap[l.id] = l);
    
    const parts = [];
    let current = locMap[locationId];
    while (current) {
        parts.unshift(current.name);
        current = current.parent_id ? locMap[current.parent_id] : null;
    }
    return parts.join(' > ');
}

function getLocationChain(locationId) {
    const allLocations = masterData.locationsFlat || [];
    const locationMap = new Map(allLocations.map(location => [Number(location.id), location]));
    const chain = [];
    const visited = new Set();
    let current = locationMap.get(Number(locationId));

    while (current && !visited.has(Number(current.id))) {
        visited.add(Number(current.id));
        chain.unshift(current);
        current = current.parent_id ? locationMap.get(Number(current.parent_id)) : null;
    }
    return chain;
}

function setObjectLocation(locationId) {
    const hiddenSelect = document.getElementById('obj-location');
    if (!hiddenSelect) return;
    hiddenSelect.value = locationId ? String(locationId) : '';
    renderObjectLocationSelector(locationId || null);
}

function renderObjectLocationSelector(selectedLocationId = null) {
    const levelsContainer = document.getElementById('obj-location-levels');
    const summary = document.getElementById('obj-location-summary');
    const hiddenSelect = document.getElementById('obj-location');
    if (!levelsContainer || !summary || !hiddenSelect) return;

    const allLocations = masterData.locationsFlat || [];
    const selectedId = selectedLocationId ? Number(selectedLocationId) : null;
    hiddenSelect.value = selectedId ? String(selectedId) : '';
    const chain = getLocationChain(selectedId);
    levelsContainer.innerHTML = '';

    let parentId = null;
    let level = 0;
    while (true) {
        const choices = allLocations
            .filter(location => Number(location.parent_id || 0) === Number(parentId || 0))
            .sort((a, b) => a.name.localeCompare(b.name, 'de', { sensitivity: 'base' }));
        if (!choices.length) break;

        const selectedAtLevel = chain[level] && Number(chain[level].parent_id || 0) === Number(parentId || 0)
            ? Number(chain[level].id)
            : null;
        const parentLocation = parentId
            ? allLocations.find(location => Number(location.id) === Number(parentId))
            : null;
        const wrapper = document.createElement('div');
        wrapper.className = 'location-cascade-level';

        const label = document.createElement('label');
        label.htmlFor = `obj-location-level-${level}`;
        label.textContent = level === 0
            ? '1. Hauptstandort'
            : `${level + 1}. Auswahl in „${parentLocation ? parentLocation.name : 'Unterbereich'}“`;

        const select = document.createElement('select');
        select.id = `obj-location-level-${level}`;
        select.dataset.level = String(level);
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = level === 0
            ? '-- Hauptstandort wählen --'
            : `-- Direkt in „${parentLocation ? parentLocation.name : 'diesem Bereich'}“ ablegen --`;
        select.appendChild(placeholder);

        choices.forEach(location => {
            const option = document.createElement('option');
            option.value = String(location.id);
            option.textContent = location.name;
            option.selected = Number(location.id) === selectedAtLevel;
            select.appendChild(option);
        });

        select.addEventListener('change', () => {
            const nextId = select.value ? Number(select.value) : parentId;
            setObjectLocation(nextId || null);
        });
        wrapper.append(label, select);
        levelsContainer.appendChild(wrapper);

        if (!selectedAtLevel) break;
        parentId = selectedAtLevel;
        level += 1;
    }

    summary.innerHTML = '';
    if (!selectedId) {
        summary.textContent = 'Noch kein Lagerplatz ausgewählt.';
        summary.classList.remove('has-selection');
        return;
    }

    const summaryText = document.createElement('span');
    summaryText.innerHTML = `<strong>Gewählt:</strong> ${escapeHtml(getLocationPath(allLocations, selectedId)).replaceAll(' &gt; ', ' › ')}`;
    const clearButton = document.createElement('button');
    clearButton.type = 'button';
    clearButton.className = 'location-clear-button';
    clearButton.textContent = 'Auswahl löschen';
    clearButton.addEventListener('click', () => setObjectLocation(null));
    summary.append(summaryText, clearButton);
    summary.classList.add('has-selection');
}

function fillFilterSelect(id, items, labelKey) {
    const sel = document.getElementById(id);
    if (!sel) return;
    const currentVal = sel.value;
    const firstOpt = sel.options[0];
    sel.innerHTML = '';
    if (firstOpt) sel.appendChild(firstOpt);
    items.forEach(item => {
        const opt = document.createElement('option');
        opt.value = item.id;
        opt.textContent = item[labelKey];
        sel.appendChild(opt);
    });
    sel.value = currentVal;
}

function fillSelect(id, items, labelKey) {
    const sel = document.getElementById(id);
    if (!sel) return;
    const currentVal = sel.value;
    sel.innerHTML = '<option value="">-- Auswählen --</option>';
    items.forEach(item => {
        const opt = document.createElement('option');
        opt.value = item.id;
        opt.textContent = item[labelKey];
        sel.appendChild(opt);
    });
    sel.value = currentVal;
}

function flattenLocations(locations, prefix = '') {
    let flat = [];
    locations.forEach(loc => {
        flat.push({ id: loc.id, name: prefix + loc.name });
        if (loc.children) {
            flat = flat.concat(flattenLocations(loc.children, prefix + loc.name + ' > '));
        }
    });
    return flat;
}

// === Inline Add Functions ===
function namesEqual(a, b) {
    return String(a || '').trim().localeCompare(String(b || '').trim(), 'de', { sensitivity: 'base' }) === 0;
}

function showInlineFeedback(id, message, type = 'error') {
    const element = document.getElementById(id);
    if (!element) return;
    element.textContent = message;
    element.className = 'inline-feedback ' + type;
}

function clearInlineFeedback(id) {
    const element = document.getElementById(id);
    if (!element) return;
    element.textContent = '';
    element.className = 'inline-feedback hidden';
}

function showFormMessage(message, type = 'error') {
    const element = document.getElementById('object-form-message');
    if (!element) return;
    element.textContent = message;
    element.className = 'form-message ' + type;
    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function clearFormMessage() {
    const element = document.getElementById('object-form-message');
    if (!element) return;
    element.textContent = '';
    element.className = 'form-message hidden';
}

function hideInlineAdd(type) {
    const box = document.getElementById('add-' + type + '-box');
    const toggle = document.getElementById('toggle-' + type);
    if (box) box.classList.add('hidden');
    if (toggle) toggle.setAttribute('aria-expanded', 'false');
    clearInlineFeedback(type + '-feedback');
}

function showAddManufacturer() {
    const box = document.getElementById('add-manufacturer-box');
    box.classList.toggle('hidden');
    const isOpen = !box.classList.contains('hidden');
    document.getElementById('toggle-manufacturer').setAttribute('aria-expanded', String(isOpen));
    clearInlineFeedback('manufacturer-feedback');
    if (isOpen) {
        document.getElementById('new-manufacturer').focus();
    }
}

async function saveNewManufacturer() {
    const name = document.getElementById('new-manufacturer').value.trim();
    if (!name) {
        showInlineFeedback('manufacturer-feedback', 'Bitte einen Herstellernamen eingeben.');
        return;
    }

    const existing = masterData.manufacturers.find(m => namesEqual(m.name, name));
    if (existing) {
        document.getElementById('obj-manufacturer').value = existing.id;
        showInlineFeedback('manufacturer-feedback', `„${existing.name}“ ist bereits vorhanden und wurde ausgewählt.`, 'info');
        return;
    }

    try {
        const m = await api('/api/manufacturers', { method: 'POST', body: JSON.stringify({ name }) });
        masterData.manufacturers.push(m);
        fillSelect('obj-manufacturer', masterData.manufacturers, 'name');
        fillFilterSelect('filter-manufacturer', masterData.manufacturers, 'name');
        document.getElementById('obj-manufacturer').value = m.id;
        document.getElementById('new-manufacturer').value = '';
        hideInlineAdd('manufacturer');
        showFormMessage(`Hersteller „${m.name}“ wurde angelegt und ausgewählt.`, 'info');
    } catch (e) {
        showInlineFeedback('manufacturer-feedback', e.message);
    }
}

function showAddSupplier() {
    const box = document.getElementById('add-supplier-box');
    box.classList.toggle('hidden');
    const isOpen = !box.classList.contains('hidden');
    document.getElementById('toggle-supplier').setAttribute('aria-expanded', String(isOpen));
    clearInlineFeedback('supplier-feedback');
    if (isOpen) {
        document.getElementById('new-supplier').focus();
    }
}

async function saveNewSupplier() {
    const name = document.getElementById('new-supplier').value.trim();
    if (!name) {
        showInlineFeedback('supplier-feedback', 'Bitte einen Lieferantennamen eingeben.');
        return;
    }

    const existing = masterData.suppliers.find(supplier => namesEqual(supplier.name, name));
    if (existing) {
        document.getElementById('obj-supplier').value = existing.id;
        showInlineFeedback('supplier-feedback', `„${existing.name}“ ist bereits vorhanden und wurde ausgewählt.`, 'info');
        return;
    }

    try {
        const supplier = await api('/api/suppliers', { method: 'POST', body: JSON.stringify({ name }) });
        masterData.suppliers.push(supplier);
        fillSelect('obj-supplier', masterData.suppliers, 'name');
        document.getElementById('obj-supplier').value = supplier.id;
        document.getElementById('new-supplier').value = '';
        hideInlineAdd('supplier');
        showFormMessage(`Lieferant „${supplier.name}“ wurde angelegt und ausgewählt.`, 'info');
    } catch (error) {
        showInlineFeedback('supplier-feedback', error.message);
    }
}

function showAddLocation() {
    const box = document.getElementById('add-location-box');
    box.classList.toggle('hidden');
    const isOpen = !box.classList.contains('hidden');
    document.getElementById('toggle-location').setAttribute('aria-expanded', String(isOpen));
    clearInlineFeedback('location-feedback');
    fillSelect('new-location-parent', flattenLocations(masterData.locations), 'name');
    const selectedLocationId = document.getElementById('obj-location').value;
    if (selectedLocationId) document.getElementById('new-location-parent').value = selectedLocationId;
    if (isOpen) {
        document.getElementById('new-location').focus();
    }
}

async function saveNewLocation() {
    const name = document.getElementById('new-location').value.trim();
    const type = document.getElementById('new-location-type').value.trim() || 'Standort';
    const parentId = document.getElementById('new-location-parent').value || null;
    if (!name) {
        showInlineFeedback('location-feedback', 'Bitte einen Standortnamen eingeben.');
        return;
    }

    const existing = (masterData.locationsFlat || []).find(l =>
        namesEqual(l.name, name) && String(l.parent_id || '') === String(parentId || '')
    );
    if (existing) {
        setObjectLocation(existing.id);
        showInlineFeedback('location-feedback', `„${getLocationPath(masterData.locationsFlat, existing.id)}“ ist bereits vorhanden und wurde ausgewählt.`, 'info');
        return;
    }

    try {
        const loc = await api('/api/locations', { method: 'POST', body: JSON.stringify({ name, location_type: type, parent_id: parentId ? parseInt(parentId) : null }) });
        // Alle Standorte neu laden
        const allLocations = await api('/api/locations/all');
        masterData.locationsFlat = allLocations;
        masterData.locations = buildLocationTree(allLocations);
        
        // Dropdowns aktualisieren (Objekt-Formular + Filter + Admin)
        const locationOptions = allLocations.map(l => ({ id: l.id, name: getLocationPath(allLocations, l.id) }));
        fillSelect('obj-location', locationOptions, 'name');
        fillSelect('new-location-parent', locationOptions, 'name');
        fillFilterSelect('filter-location', locationOptions, 'name');
        
        setObjectLocation(loc.id);
        document.getElementById('new-location').value = '';
        document.getElementById('new-location-type').value = 'Standort';
        hideInlineAdd('location');
        showFormMessage(`Standort „${loc.name}“ wurde angelegt und ausgewählt.`, 'info');
    } catch (e) {
        showInlineFeedback('location-feedback', e.message);
    }
}

// === Dashboard ===
async function loadDashboardAlerts() {
    if (currentUser.role === 'standard') return;
    const container = document.getElementById('maintenance-alerts');
    if (container) container.innerHTML = '';
}

// === Prüfzentrale (Verwaltung & Admin) ===
let inspectionCenterData = null;
let inspectionCenterExactSearch = false;

function canAccessInspectionCenter() {
    return currentUser && (currentUser.role === 'verwaltung' || currentUser.role === 'admin');
}

function formatDateInput(dateValue) {
    const year = dateValue.getFullYear();
    const month = String(dateValue.getMonth() + 1).padStart(2, '0');
    const day = String(dateValue.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function initializeInspectionCenterDates() {
    const from = document.getElementById('inspection-center-from');
    const to = document.getElementById('inspection-center-to');
    if (!from || !to || (from.value && to.value)) return;
    const today = new Date();
    const end = new Date(today);
    end.setDate(end.getDate() + 90);
    from.value = formatDateInput(today);
    to.value = formatDateInput(end);
}

function setInspectionCenterRange(days) {
    const today = new Date();
    const end = new Date(today);
    end.setDate(end.getDate() + days);
    document.getElementById('inspection-center-from').value = formatDateInput(today);
    document.getElementById('inspection-center-to').value = formatDateInput(end);
    loadInspectionCenter();
}

async function loadInspectionCenter(event) {
    if (event) event.preventDefault();
    if (!canAccessInspectionCenter()) return;
    initializeInspectionCenterDates();
    const from = document.getElementById('inspection-center-from').value;
    const to = document.getElementById('inspection-center-to').value;
    const includeOverdue = document.getElementById('inspection-center-overdue').checked;
    const summary = document.getElementById('inspection-center-summary');
    const results = document.getElementById('inspection-center-results');
    if (!from || !to) return;
    if (to < from) {
        results.innerHTML = '<div class="empty-state error-state">Das Enddatum muss nach dem Startdatum liegen.</div>';
        return;
    }
    summary.innerHTML = '';
    results.innerHTML = '<div class="empty-state">Prüftermine werden geladen …</div>';
    try {
        const params = new URLSearchParams({
            start_date: from,
            end_date: to,
            include_overdue: String(includeOverdue)
        });
        const data = await api('/api/inspection-center?' + params.toString());
        inspectionCenterData = data;
        renderInspectionCenter(data);
    } catch (error) {
        inspectionCenterData = null;
        results.innerHTML = `<div class="empty-state error-state">Prüfzentrale konnte nicht geladen werden: ${escapeHtml(error.message)}</div>`;
    }
}

function renderInspectionCenter(data) {
    const summary = document.getElementById('inspection-center-summary');
    const results = document.getElementById('inspection-center-results');
    const resultMeta = document.getElementById('inspection-center-result-meta');
    const searchValue = document.getElementById('inspection-center-search').value.trim();
    const query = normalizeInspectionSearch(searchValue);
    const allItems = data.items || [];
    const items = query
        ? allItems.filter(item => inspectionItemMatches(item, query))
        : allItems;
    const counts = {
        total: items.length,
        overdue: items.filter(item => item.days_until < 0).length,
        next_7_days: items.filter(item => item.days_until >= 0 && item.days_until <= 7).length,
        next_30_days: items.filter(item => item.days_until >= 0 && item.days_until <= 30).length
    };
    summary.innerHTML = `
        <div class="inspection-summary-card"><strong>${counts.total || 0}</strong><span>Termine gesamt</span></div>
        <div class="inspection-summary-card danger"><strong>${counts.overdue || 0}</strong><span>Überfällig</span></div>
        <div class="inspection-summary-card warning"><strong>${counts.next_7_days || 0}</strong><span>In den nächsten 7 Tagen</span></div>
        <div class="inspection-summary-card info"><strong>${counts.next_30_days || 0}</strong><span>In den nächsten 30 Tagen</span></div>
    `;
    if (!allItems.length) {
        resultMeta.textContent = '';
        results.innerHTML = '<div class="empty-state">In diesem Zeitraum stehen keine Prüfungen an.</div>';
        return;
    }
    if (!items.length) {
        resultMeta.textContent = `0 von ${allItems.length} Terminen gefunden`;
        results.innerHTML = '<div class="empty-state">Kein anstehendes Gerät passt zu dieser Suche.</div>';
        return;
    }

    const grouped = document.getElementById('inspection-center-grouped').checked;
    const groups = groupInspectionCenterItems(items);
    const combinedGroups = groups.filter(group => group.items.length > 1).length;
    const groupResultLabel = combinedGroups === 1 ? '1 passende Gruppe' : `${combinedGroups} passende Gruppen`;
    const groupedLabel = combinedGroups === 1 ? '1 zusammengefasste Gruppe' : `${combinedGroups} zusammengefasste Gruppen`;
    resultMeta.textContent = query
        ? `${items.length} von ${allItems.length} Terminen gefunden${combinedGroups ? ` · ${groupResultLabel}` : ''}`
        : `${items.length} Termine${grouped && combinedGroups ? ` · ${groupedLabel}` : ''}`;

    if (!grouped) {
        results.innerHTML = items.map(item => renderInspectionDueItem(item)).join('');
        return;
    }
    results.innerHTML = groups.map(group =>
        group.items.length > 1
            ? renderInspectionDueGroup(group, Boolean(query))
            : renderInspectionDueItem(group.items[0])
    ).join('');
}

function normalizeInspectionSearch(value) {
    const text = String(value || '').trim();
    const objectNumber = text.match(/FFW-\d+/i);
    return (objectNumber ? objectNumber[0] : text).toLocaleLowerCase('de-DE');
}

function inspectionItemMatches(item, query) {
    if (inspectionCenterExactSearch) {
        return [item.object_number, item.serial_number]
            .filter(Boolean)
            .some(value => String(value).trim().toLocaleLowerCase('de-DE') === query);
    }
    const searchable = [
        item.designation,
        item.object_number,
        item.serial_number,
        item.object_type,
        item.inspection_name,
        item.location_name
    ].filter(Boolean).join(' ').toLocaleLowerCase('de-DE');
    return searchable.includes(query);
}

function filterInspectionCenter() {
    if (inspectionCenterData) renderInspectionCenter(inspectionCenterData);
}

function inspectionCenterSearchChanged() {
    inspectionCenterExactSearch = false;
    filterInspectionCenter();
}

function clearInspectionCenterSearch() {
    const input = document.getElementById('inspection-center-search');
    input.value = '';
    inspectionCenterExactSearch = false;
    input.focus();
    filterInspectionCenter();
}

function scanInspectionCenterSearch() {
    startQrScan(decodedText => {
        const value = String(decodedText || '').trim();
        const objectNumber = value.match(/FFW-\d+/i);
        const input = document.getElementById('inspection-center-search');
        input.value = objectNumber ? objectNumber[0].toUpperCase() : value;
        inspectionCenterExactSearch = true;
        filterInspectionCenter();
    }, null, {
        title: 'Gerät in der Prüfzentrale finden',
        hint: 'Inventar-QR-Code oder Barcode der Seriennummer scannen.',
        formatsToSupport: getSerialScannerFormats(),
        wideFrame: true,
        normalizeUpcAAsEan13: true
    });
}

function groupInspectionCenterItems(items) {
    const groups = new Map();
    items.forEach(item => {
        const key = `${item.due_date}\u0000${item.object_type || 'Ohne Kategorie'}`;
        if (!groups.has(key)) {
            groups.set(key, {
                due_date: item.due_date,
                days_until: item.days_until,
                object_type: item.object_type || 'Ohne Kategorie',
                items: []
            });
        }
        groups.get(key).items.push(item);
    });
    return Array.from(groups.values());
}

function inspectionDateInfo(item) {
    const dueDate = new Date(item.due_date + 'T00:00:00');
    return {
        dateLabel: dueDate.toLocaleDateString('de-DE'),
        dueClass: item.days_until < 0 ? 'overdue' : (item.days_until <= 7 ? 'soon' : 'planned'),
        relativeLabel: item.days_until < 0
            ? `${Math.abs(item.days_until)} Tage überfällig`
            : (item.days_until === 0 ? 'Heute fällig' : `In ${item.days_until} Tagen`)
    };
}

function renderInspectionSerial(serialNumber) {
    if (!serialNumber) return '';
    const serial = String(serialNumber);
    const shortSerial = serial.length > 4 ? `…${serial.slice(-4)}` : serial;
    return `
        <span class="inspection-serial" title="Seriennummer ${escapeHtml(serial)}">
            <span class="inspection-serial-full">SN ${escapeHtml(serial)}</span>
            <span class="inspection-serial-short">SN ${escapeHtml(shortSerial)}</span>
        </span>
    `;
}

function renderInspectionDueItem(item, compact = false) {
    const info = inspectionDateInfo(item);
    return `
        <article class="inspection-due-card ${info.dueClass}${compact ? ' grouped-item' : ''}">
            ${compact ? '' : `
                <div class="inspection-due-date">
                    <span>${info.dateLabel}</span>
                    <strong>${info.relativeLabel}</strong>
                </div>
            `}
            <div class="inspection-due-main">
                <div class="inspection-due-title">
                    <span class="badge ${item.source === 'maintenance' ? 'badge-reserve' : 'badge-in_benutzung'}">${item.source === 'maintenance' ? 'Wartung' : 'Prüfkarte'}</span>
                    <h3>${escapeHtml(item.inspection_name)}</h3>
                </div>
                <button type="button" class="inspection-object-link" onclick="openObject(${item.object_id})">
                    <span class="inspection-object-designation">${escapeHtml(item.designation)}</span>
                    <span class="inspection-object-number">${escapeHtml(item.object_number)}</span>
                    ${renderInspectionSerial(item.serial_number)}
                </button>
                <p class="inspection-due-meta">
                    ${item.object_type ? escapeHtml(item.object_type) : 'Ohne Kategorie'}
                    ${item.location_name ? ` · 📍 ${escapeHtml(item.location_name)}` : ''}
                </p>
                ${item.last_inspection_date ? `<small>Letzte Prüfung: ${new Date(item.last_inspection_date).toLocaleDateString('de-DE')}${item.last_inspected_by ? ` durch ${escapeHtml(item.last_inspected_by)}` : ''}</small>` : ''}
            </div>
            <div class="inspection-due-actions">
                <button type="button" class="btn-secondary btn-small" onclick="openObject(${item.object_id})">Details</button>
                <button type="button" class="btn-primary btn-small" onclick="openInspectionModal(${item.object_id}, ${item.template_id || 'null'}, ${item.maintenance_id || 'null'})">Prüfung starten</button>
            </div>
        </article>
    `;
}

function renderInspectionDueGroup(group, openForSearch) {
    const representative = group.items[0];
    const info = inspectionDateInfo(representative);
    const inspectionNames = [...new Set(group.items.map(item => item.inspection_name))];
    const inspectionLabel = inspectionNames.length === 1
        ? inspectionNames[0]
        : `${inspectionNames.length} verschiedene Prüfarten`;
    return `
        <details class="inspection-due-group ${info.dueClass}" ${openForSearch ? 'open' : ''}>
            <summary>
                <div class="inspection-group-date"><strong>${info.dateLabel}</strong><span>${info.relativeLabel}</span></div>
                <div class="inspection-group-title">
                    <strong>${escapeHtml(group.object_type)}</strong>
                    <span>${escapeHtml(inspectionLabel)}</span>
                </div>
                <span class="inspection-group-count">${group.items.length} Geräte</span>
                <span class="inspection-group-chevron" aria-hidden="true">⌄</span>
            </summary>
            <div class="inspection-group-items">
                ${group.items.map(item => renderInspectionDueItem(item, true)).join('')}
            </div>
        </details>
    `;
}

// === Search ===
let searchTimeout;
function debouncedSearch() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(applyFilters, 300);
}

async function applyFilters() {
    const q = document.getElementById('search-input').value.trim();
    const typeId = document.getElementById('filter-type').value;
    const locId = document.getElementById('filter-location').value;
    const manuId = document.getElementById('filter-manufacturer').value;
    const status = document.getElementById('filter-status').value;

    let url = '/api/objects/browse?';
    const params = [];
    if (q) params.push('q=' + encodeURIComponent(q));
    if (typeId) params.push('object_type_id=' + encodeURIComponent(typeId));
    if (locId) params.push('location_id=' + encodeURIComponent(locId));
    if (manuId) params.push('manufacturer_id=' + encodeURIComponent(manuId));
    if (status) params.push('status=' + encodeURIComponent(status));
    url += params.join('&');

    try {
        const results = await api(url);
        renderSearchResults(results);
    } catch (e) { console.error(e); }
}

function resetFilters() {
    document.getElementById('search-input').value = '';
    document.getElementById('filter-type').value = '';
    document.getElementById('filter-location').value = '';
    document.getElementById('filter-manufacturer').value = '';
    document.getElementById('filter-status').value = '';
    applyFilters();
}

function renderSearchResults(results) {
    const container = document.getElementById('search-results');
    if (!results.length) { container.innerHTML = '<p>Keine Ergebnisse</p>'; return; }
    container.innerHTML = results.map(r => `
        <div class="card" onclick="openObject(${r.id})">
            <img class="card-image" src="${r.title_image ? '/uploads/images/' + r.title_image : ''}" alt="" onerror="this.style.display='none'">
            <div class="card-body">
                <h4>${escapeHtml(r.designation)}</h4>
                <div class="card-meta">
                    <span class="badge badge-${r.status}">${formatStatus(r.status)}</span>
                    <strong>${r.object_number}</strong>
                    ${r.object_type ? '· ' + r.object_type : ''}
                    ${r.location_name ? '· ' + escapeHtml(r.location_name) : ''}
                </div>
            </div>
        </div>
    `).join('');
}

// === QR Scanner ===
let qrScanCallback = null;
let previousViewBeforeScan = null;
let modalToRestoreAfterScan = null;
let activeScannerOptions = {};
let availableScannerCameras = [];
let activeScannerCameraId = null;
let scannerIsRunning = false;
let scannerTorchEnabled = false;
let nativeScannerStream = null;
let nativeBarcodeDetector = null;
let nativeScanTimer = null;
let wasmScannerCanvas = null;
let wasmScannerBusy = false;
let scannerCandidateValue = '';
let scannerCandidateHits = 0;
let scannerCandidateFirstAt = 0;
let scannerCandidateAt = 0;
let scannerResultCompleted = false;

function showScannerStatus(message, type = 'info') {
    const statusElement = document.getElementById('scanner-status');
    if (!statusElement) return;
    statusElement.textContent = message;
    statusElement.className = 'scanner-status ' + type;
}

function ensureScannerLibrary() {
    if (window.Html5Qrcode) return Promise.resolve(true);
    return new Promise(resolve => {
        let settled = false;
        const finish = value => {
            if (settled) return;
            settled = true;
            resolve(value);
        };
        const fallback = document.createElement('script');
        fallback.src = 'https://cdn.jsdelivr.net/npm/html5-qrcode@2.3.8/html5-qrcode.min.js';
        fallback.onload = () => finish(Boolean(window.Html5Qrcode));
        fallback.onerror = () => finish(false);
        document.head.appendChild(fallback);
        setTimeout(() => finish(Boolean(window.Html5Qrcode)), 5000);
    });
}

function ensureWasmScannerLibrary() {
    if (window.ZXingWASM && typeof window.ZXingWASM.readBarcodes === 'function') {
        return Promise.resolve(true);
    }
    return new Promise(resolve => {
        let settled = false;
        const finish = value => {
            if (settled) return;
            settled = true;
            resolve(value);
        };
        const fallback = document.createElement('script');
        fallback.src = 'https://cdn.jsdelivr.net/npm/zxing-wasm@3.1.4/dist/iife/reader/index.js';
        fallback.onload = () => finish(Boolean(window.ZXingWASM));
        fallback.onerror = () => finish(false);
        document.head.appendChild(fallback);
        setTimeout(() => finish(Boolean(window.ZXingWASM)), 8000);
    });
}

function startQrScan(onScanCallback, modalId, options = {}) {
    previousViewBeforeScan = currentView;
    qrScanCallback = onScanCallback || null;
    modalToRestoreAfterScan = modalId || null;
    activeScannerOptions = options;
    availableScannerCameras = [];
    activeScannerCameraId = null;
    scannerTorchEnabled = false;
    resetScannerCandidate();
    scannerResultCompleted = false;
    document.getElementById('scanner-title').textContent = options.title || 'QR-Code scannen';
    document.getElementById('scanner-hint').textContent = options.hint || 'Code in den markierten Bereich halten.';
    document.getElementById('scanner-manual-value').value = '';
    document.getElementById('scanner-image-input').value = '';
    document.getElementById('scanner-camera').classList.add('hidden');
    document.getElementById('scanner-focus').classList.add('hidden');
    document.getElementById('scanner-torch').classList.add('hidden');
    document.getElementById('scanner-start-camera').classList.remove('hidden');
    document.getElementById('scanner-start-camera').disabled = false;
    document.getElementById('scanner-video').classList.add('hidden');
    document.getElementById('qr-reader').classList.remove('hidden');
    showScannerStatus('Kamera live starten, ein Foto aufnehmen oder den Code manuell eingeben.');
    // Wenn ein Modal offen ist, ausblenden damit der Scanner sichtbar ist
    if (modalId) {
        const modal = document.getElementById(modalId);
        if (modal) modal.style.display = 'none';
    }
    showView('scanner');
}

async function startScannerCameraAccess() {
    const startButton = document.getElementById('scanner-start-camera');
    startButton.disabled = true;
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        try {
            const hasNativeDetector = 'BarcodeDetector' in window;
            const hasWasmDetector = hasNativeDetector || await ensureWasmScannerLibrary();
            if (!hasWasmDetector) throw new Error('Optimierte Scanner-Engine konnte nicht geladen werden');
            await startNativeScanner();
            startButton.classList.add('hidden');
            return;
        } catch (error) {
            stopNativeScanner();
            console.warn('Nativer Scanner nicht verfügbar:', error);
        }
    }
    const libraryReady = await ensureScannerLibrary();
    if (!libraryReady) {
        showScannerStatus('Der Scanner konnte nicht geladen werden. Du kannst ein Foto auswählen oder den Code manuell eingeben.', 'error');
        startButton.disabled = false;
        return;
    }
    if (!window.isSecureContext) {
        showScannerStatus('Live-Kamera ist über diese unverschlüsselte Adresse eventuell gesperrt. Nutze die HTTPS-Adresse oder wähle ein Foto aus.', 'warning');
    }
    const scannerOptions = activeScannerOptions.formatsToSupport && activeScannerOptions.formatsToSupport.length
        ? { formatsToSupport: activeScannerOptions.formatsToSupport, verbose: false }
        : { verbose: false };
    scanner = new Html5Qrcode('qr-reader', scannerOptions);
    try {
        availableScannerCameras = await Html5Qrcode.getCameras();
        if (!availableScannerCameras.length) throw new Error('Keine Kamera gefunden');
        const preferredCamera = availableScannerCameras.find(camera => /back|rear|environment|rück/i.test(camera.label))
            || availableScannerCameras[availableScannerCameras.length - 1];
        populateScannerCameras(preferredCamera.id);
        await startScannerCamera(preferredCamera.id);
        startButton.classList.add('hidden');
    } catch (error) {
        const message = String(error && error.message ? error.message : error);
        const denied = /NotAllowed|Permission|denied|berechtigung/i.test(message);
        showScannerStatus(
            denied
                ? 'Kein Kamerazugriff. Bitte erlaube die Kamera in den Browser-Einstellungen oder nutze ein Foto.'
                : `Kamera konnte nicht gestartet werden. Nutze ein Foto oder die manuelle Eingabe. (${message})`,
            'error'
        );
        startButton.disabled = false;
    }
}

async function startNativeScanner(cameraId = null) {
    nativeBarcodeDetector = 'BarcodeDetector' in window ? new BarcodeDetector() : null;
    const videoConstraints = cameraId
        ? { deviceId: { exact: cameraId }, width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 30, max: 30 } }
        : { facingMode: { exact: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 30, max: 30 } };
    showScannerStatus('Bitte den Kamerazugriff im Browser erlauben. Falls keine Abfrage erscheint, nutze „Foto aufnehmen/auswählen“.', 'warning');
    try {
        nativeScannerStream = await navigator.mediaDevices.getUserMedia({ video: videoConstraints, audio: false });
    } catch (error) {
        if (cameraId) throw error;
        nativeScannerStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } },
            audio: false
        });
    }
    const activeTrack = nativeScannerStream.getVideoTracks()[0];
    await tuneScannerCamera(activeTrack);
    const video = document.getElementById('scanner-video');
    document.getElementById('qr-reader').classList.add('hidden');
    video.classList.remove('hidden');
    video.srcObject = nativeScannerStream;
    video.onclick = refocusScannerCamera;
    await video.play();
    scannerIsRunning = true;

    let devices = [];
    try {
        devices = await navigator.mediaDevices.enumerateDevices();
    } catch (_) {}
    availableScannerCameras = devices
        .filter(device => device.kind === 'videoinput')
        .map((device, index) => ({ id: device.deviceId, label: device.label || `Kamera ${index + 1}` }));
    activeScannerCameraId = activeTrack && activeTrack.getSettings ? activeTrack.getSettings().deviceId : cameraId;
    if (availableScannerCameras.length) populateScannerCameras(activeScannerCameraId || availableScannerCameras[0].id);
    document.getElementById('scanner-focus').classList.remove('hidden');
    showScannerStatus(
        nativeBarcodeDetector
            ? 'Kamera aktiv – schnelle Geräteerkennung und Autofokus sind eingeschaltet.'
            : 'Kamera aktiv – iPhone-Scanner mit Drehungserkennung und Autofokus ist eingeschaltet.',
        'success'
    );
    updateScannerTorchAvailability();
    runNativeDetection();
}

async function runNativeDetection() {
    if (!nativeScannerStream || currentView !== 'scanner') return;
    const video = document.getElementById('scanner-video');
    try {
        if (video.readyState >= 2 && !wasmScannerBusy) {
            wasmScannerBusy = true;
            if (nativeBarcodeDetector) {
                const codes = await nativeBarcodeDetector.detect(video);
                if (codes && codes.length && codes[0].rawValue) {
                    if (handleScannerDetection(codes[0].rawValue, codes[0].format, true)) return;
                }
            } else {
                const result = await detectWithWasm(video);
                if (result && result.text) {
                    if (handleScannerDetection(result.text, result.format, true)) return;
                }
            }
        }
    } catch (error) {
        console.debug('Scannerbild noch nicht lesbar:', error);
    } finally {
        wasmScannerBusy = false;
    }
    nativeScanTimer = setTimeout(runNativeDetection, nativeBarcodeDetector ? 110 : 170);
}

async function detectWithWasm(video) {
    if (!window.ZXingWASM || !video.videoWidth || !video.videoHeight) return null;
    if (!wasmScannerCanvas) wasmScannerCanvas = document.createElement('canvas');
    const maxEdge = 1280;
    const scale = Math.min(1, maxEdge / Math.max(video.videoWidth, video.videoHeight));
    wasmScannerCanvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    wasmScannerCanvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    const context = wasmScannerCanvas.getContext('2d', { willReadFrequently: true });
    context.drawImage(video, 0, 0, wasmScannerCanvas.width, wasmScannerCanvas.height);
    const imageData = context.getImageData(0, 0, wasmScannerCanvas.width, wasmScannerCanvas.height);
    const formats = ['QRCode', 'DataMatrix', 'Code39', 'Code93', 'Code128', 'Codabar', 'ITF', 'EAN8', 'EAN13', 'UPCA', 'UPCE'];
    const results = await window.ZXingWASM.readBarcodes(imageData, {
        formats,
        tryHarder: true,
        tryRotate: true,
        tryInvert: true,
        tryDownscale: true,
        maxNumberOfSymbols: 1
    });
    return results && results.length ? results[0] : null;
}

async function tuneScannerCamera(track, forceRefocus = false) {
    if (!track || !track.applyConstraints) return false;
    let capabilities = {};
    try {
        capabilities = track.getCapabilities ? track.getCapabilities() : {};
    } catch (_) {}
    const focusModes = Array.isArray(capabilities.focusMode) ? capabilities.focusMode : [];
    try {
        if (forceRefocus && focusModes.includes('single-shot')) {
            await track.applyConstraints({ advanced: [{ focusMode: 'single-shot' }] });
        }
        if (focusModes.includes('continuous')) {
            await track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] });
            return true;
        }
    } catch (_) {}
    return false;
}

async function refocusScannerCamera() {
    let track = null;
    if (nativeScannerStream) track = nativeScannerStream.getVideoTracks()[0];
    if (!track && scanner && typeof scanner.getRunningTrackCapabilities === 'function') {
        showScannerStatus('Die Kamera fokussiert automatisch. Code kurz aus dem Bild nehmen und erneut zeigen.', 'info');
        return;
    }
    const explicitlyFocused = await tuneScannerCamera(track, true);
    showScannerStatus(
        explicitlyFocused
            ? 'Autofokus wurde neu angestoßen.'
            : 'Das Gerät steuert den Fokus selbst. Etwas mehr Abstand hilft bei sehr kleinen Codes.',
        explicitlyFocused ? 'success' : 'info'
    );
}

function stopNativeScanner() {
    if (nativeScanTimer) clearTimeout(nativeScanTimer);
    nativeScanTimer = null;
    if (nativeScannerStream) {
        nativeScannerStream.getTracks().forEach(track => track.stop());
    }
    nativeScannerStream = null;
    nativeBarcodeDetector = null;
    wasmScannerBusy = false;
    wasmScannerCanvas = null;
    const video = document.getElementById('scanner-video');
    if (video) {
        video.pause();
        video.srcObject = null;
        video.onclick = null;
        video.classList.add('hidden');
    }
}

function populateScannerCameras(selectedId) {
    const select = document.getElementById('scanner-camera');
    select.innerHTML = availableScannerCameras.map((camera, index) =>
        `<option value="${escapeHtml(camera.id)}">${escapeHtml(camera.label || `Kamera ${index + 1}`)}</option>`
    ).join('');
    select.value = selectedId;
    select.classList.toggle('hidden', availableScannerCameras.length < 2);
}

async function startScannerCamera(cameraId) {
    if (!scanner) return;
    activeScannerCameraId = cameraId;
    const qrbox = activeScannerOptions.wideFrame
        ? (viewfinderWidth, viewfinderHeight) => {
            const width = Math.max(120, Math.floor(Math.min(viewfinderWidth * 0.94, 440)));
            const availableHeight = Math.max(70, Math.floor(viewfinderHeight * 0.55));
            const height = Math.max(70, Math.min(Math.floor(width * 0.4), availableHeight));
            return { width, height };
        }
        : { width: 250, height: 250 };
    await scanner.start(
        cameraId,
        { fps: 18, qrbox },
        (decodedText, decodedResult) => handleScannerDetection(
            decodedText,
            getScannerFormatName(decodedResult)
        ),
        () => {}
    );
    scannerIsRunning = true;
    if (typeof scanner.applyVideoConstraints === 'function') {
        try {
            const capabilities = scanner.getRunningTrackCapabilities ? scanner.getRunningTrackCapabilities() : {};
            const focusModes = Array.isArray(capabilities.focusMode) ? capabilities.focusMode : [];
            if (focusModes.includes('continuous')) {
                await scanner.applyVideoConstraints({ advanced: [{ focusMode: 'continuous' }] });
            }
        } catch (_) {}
    }
    document.getElementById('scanner-focus').classList.remove('hidden');
    showScannerStatus('Kamera aktiv – Barcode vollständig mit beiden freien Rändern zeigen.', 'success');
    updateScannerTorchAvailability();
}

async function switchScannerCamera(cameraId) {
    if (!cameraId || cameraId === activeScannerCameraId) return;
    showScannerStatus('Kamera wird gewechselt …');
    resetScannerCandidate();
    try {
        if (nativeScannerStream) {
            stopNativeScanner();
            scannerIsRunning = false;
            scannerTorchEnabled = false;
            await startNativeScanner(cameraId);
            return;
        }
        if (!scanner) return;
        if (scannerIsRunning) await scanner.stop();
        scannerIsRunning = false;
        scannerTorchEnabled = false;
        await startScannerCamera(cameraId);
    } catch (error) {
        showScannerStatus('Die ausgewählte Kamera konnte nicht gestartet werden.', 'error');
    }
}

function updateScannerTorchAvailability() {
    const button = document.getElementById('scanner-torch');
    button.classList.add('hidden');
    if (nativeScannerStream) {
        const track = nativeScannerStream.getVideoTracks()[0];
        const capabilities = track && track.getCapabilities ? track.getCapabilities() : {};
        if (capabilities.torch) button.classList.remove('hidden');
        return;
    }
    if (!scanner || typeof scanner.getRunningTrackCapabilities !== 'function') return;
    try {
        const capabilities = scanner.getRunningTrackCapabilities();
        if (capabilities && capabilities.torch) button.classList.remove('hidden');
    } catch (_) {}
}

async function toggleScannerTorch() {
    if (!scannerIsRunning) return;
    try {
        scannerTorchEnabled = !scannerTorchEnabled;
        if (nativeScannerStream) {
            const track = nativeScannerStream.getVideoTracks()[0];
            await track.applyConstraints({ advanced: [{ torch: scannerTorchEnabled }] });
        } else {
            if (!scanner || typeof scanner.applyVideoConstraints !== 'function') return;
            await scanner.applyVideoConstraints({ advanced: [{ torch: scannerTorchEnabled }] });
        }
        document.getElementById('scanner-torch').textContent = scannerTorchEnabled ? '🔦 Licht ausschalten' : '🔦 Licht einschalten';
    } catch (_) {
        scannerTorchEnabled = false;
        showScannerStatus('Das Kameralicht wird von diesem Gerät nicht unterstützt.', 'warning');
    }
}

async function scanCodeFromImage(input) {
    const file = input.files && input.files[0];
    if (!file) return;
    showScannerStatus('Foto wird nach einem QR- oder Barcode durchsucht …');
    try {
        if ('BarcodeDetector' in window) {
            const detector = nativeBarcodeDetector || new BarcodeDetector();
            const bitmap = await createImageBitmap(file);
            const codes = await detector.detect(bitmap);
            bitmap.close();
            if (codes && codes.length && codes[0].rawValue) {
                handleScannerDetection(codes[0].rawValue, codes[0].format, true);
                return;
            }
            throw new Error('Kein Code gefunden');
        }
        const wasmReady = await ensureWasmScannerLibrary();
        if (wasmReady) {
            const formats = ['QRCode', 'DataMatrix', 'Code39', 'Code93', 'Code128', 'Codabar', 'ITF', 'EAN8', 'EAN13', 'UPCA', 'UPCE'];
            const results = await window.ZXingWASM.readBarcodes(file, {
                formats,
                tryHarder: true,
                tryRotate: true,
                tryInvert: true,
                maxNumberOfSymbols: 1
            });
            if (results && results.length && results[0].text) {
                handleScannerDetection(results[0].text, results[0].format, true);
                return;
            }
        }
        const libraryReady = await ensureScannerLibrary();
        if (!libraryReady) throw new Error('Scannerbibliothek nicht verfügbar');
        if (!scanner) {
            const scannerOptions = activeScannerOptions.formatsToSupport && activeScannerOptions.formatsToSupport.length
                ? { formatsToSupport: activeScannerOptions.formatsToSupport, verbose: false }
                : { verbose: false };
            scanner = new Html5Qrcode('qr-reader', scannerOptions);
        }
        if (scannerIsRunning && scanner) {
            await scanner.stop();
            scannerIsRunning = false;
        }
        if (typeof scanner.scanFileV2 === 'function') {
            const decodedResult = await scanner.scanFileV2(file, true);
            handleScannerDetection(decodedResult.decodedText, getScannerFormatName(decodedResult), true);
        } else {
            const decodedText = await scanner.scanFile(file, true);
            handleScannerDetection(decodedText, '', true);
        }
    } catch (_) {
        showScannerStatus('Auf dem Foto wurde kein lesbarer Code gefunden. Bitte näher und schärfer fotografieren.', 'error');
        if (scanner && activeScannerCameraId) {
            startScannerCamera(activeScannerCameraId).catch(() => {});
        }
    } finally {
        input.value = '';
    }
}

function submitManualScan() {
    const value = document.getElementById('scanner-manual-value').value.trim();
    if (!value) {
        showScannerStatus('Bitte zuerst einen Wert eingeben.', 'warning');
        return;
    }
    completeScannerResult(value);
}

function resetScannerCandidate() {
    scannerCandidateValue = '';
    scannerCandidateHits = 0;
    scannerCandidateFirstAt = 0;
    scannerCandidateAt = 0;
}

function getScannerFormatName(decodedResult) {
    if (!decodedResult) return '';
    return String(
        decodedResult.format
        || decodedResult.formatName
        || (decodedResult.result && decodedResult.result.format && decodedResult.result.format.formatName)
        || (decodedResult.decodedResult && decodedResult.decodedResult.formatName)
        || ''
    );
}

function normalizeScannerValue(decodedText, formatName = '') {
    let cleanValue = String(decodedText || '').replace(/[\u0000-\u001F\u007F]/g, '').trim();
    const normalizedFormat = String(formatName || '').toLowerCase().replace(/[\s-]+/g, '_');

    // Manche iPhones liefern EAN-13-Codes mit führender 0 als zwölfstelligen UPC-A.
    if (
        activeScannerOptions.normalizeUpcAAsEan13
        && (normalizedFormat === 'upc_a' || normalizedFormat === 'upca')
        && /^\d{12}$/.test(cleanValue)
    ) {
        cleanValue = '0' + cleanValue;
    }
    return cleanValue;
}

function handleScannerDetection(decodedText, formatName = '', immediate = false) {
    if (scannerResultCompleted) return true;
    const cleanValue = normalizeScannerValue(decodedText, formatName);
    if (!cleanValue) return false;
    if (immediate) return completeScannerResult(cleanValue);

    const now = Date.now();
    if (cleanValue === scannerCandidateValue && now - scannerCandidateAt <= 2500) {
        scannerCandidateHits += 1;
    } else {
        scannerCandidateValue = cleanValue;
        scannerCandidateHits = 1;
        scannerCandidateFirstAt = now;
    }
    scannerCandidateAt = now;

    if (scannerCandidateHits >= 2 && now - scannerCandidateFirstAt >= 180) {
        return completeScannerResult(cleanValue);
    }
    showScannerStatus('Code erkannt – bitte noch kurz ruhig und vollständig halten …', 'warning');
    return false;
}

function completeScannerResult(decodedText) {
    const cleanValue = String(decodedText || '').replace(/[\u0000-\u001F\u007F]/g, '').trim();
    if (!cleanValue || scannerResultCompleted) return false;
    scannerResultCompleted = true;
    const cb = qrScanCallback;
    const returnView = previousViewBeforeScan || 'search';
    if (navigator.vibrate) navigator.vibrate(120);
    playScannerBeep();
    cleanupScannerSession();
    if (cb) {
        showView(returnView, { replaceHistory: true });
        cb(cleanValue);
    } else {
        showView('search', { replaceHistory: true });
        handleQrResult(cleanValue);
    }
    return true;
}

function playScannerBeep() {
    try {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) return;
        const audioContext = new AudioContextClass();
        const oscillator = audioContext.createOscillator();
        const gain = audioContext.createGain();
        oscillator.frequency.value = 880;
        gain.gain.value = 0.06;
        oscillator.connect(gain);
        gain.connect(audioContext.destination);
        oscillator.start();
        oscillator.stop(audioContext.currentTime + 0.09);
    } catch (_) {}
}

function stopQrScan() {
    const fallbackView = previousViewBeforeScan || 'search';
    cleanupScannerSession();
    navigateBack(fallbackView);
}

function cleanupScannerSession() {
    stopNativeScanner();
    const scannerToClose = scanner;
    scanner = null;
    scannerIsRunning = false;
    scannerTorchEnabled = false;
    if (scannerToClose) {
        scannerToClose.stop()
            .catch(() => {})
            .finally(() => Promise.resolve(scannerToClose.clear()).catch(() => {}));
    }
    document.getElementById('scanner-torch').classList.add('hidden');
    document.getElementById('scanner-focus').classList.add('hidden');
    document.getElementById('scanner-camera').classList.add('hidden');
    document.getElementById('scanner-start-camera').classList.remove('hidden');
    document.getElementById('scanner-start-camera').disabled = false;
    document.getElementById('qr-reader').classList.remove('hidden');
    if (modalToRestoreAfterScan) {
        const modal = document.getElementById(modalToRestoreAfterScan);
        if (modal) modal.style.display = 'block';
        modalToRestoreAfterScan = null;
    }
    qrScanCallback = null;
    previousViewBeforeScan = null;
    activeScannerOptions = {};
    availableScannerCameras = [];
    activeScannerCameraId = null;
    resetScannerCandidate();
}

function getSerialScannerFormats() {
    const formats = window.Html5QrcodeSupportedFormats;
    if (!formats) return [];
    return [
        formats.QR_CODE,
        formats.DATA_MATRIX,
        formats.CODE_39,
        formats.CODE_93,
        formats.CODE_128,
        formats.CODABAR,
        formats.ITF,
        formats.EAN_8,
        formats.EAN_13,
        formats.UPC_A,
        formats.UPC_E
    ].filter(format => format !== undefined);
}

function scanSerialNumber() {
    clearInlineFeedback('serial-scan-feedback');
    startQrScan((decodedText) => {
        const serialNumber = String(decodedText || '')
            .replace(/[\u0000-\u001F\u007F]/g, '')
            .trim();
        if (!serialNumber) {
            showInlineFeedback('serial-scan-feedback', 'Der gelesene Code enthält keinen Wert.');
            return;
        }
        document.getElementById('obj-serial').value = serialNumber;
        showInlineFeedback('serial-scan-feedback', `Seriennummer „${serialNumber}“ wurde übernommen.`, 'info');
    }, null, {
        title: 'Seriennummer scannen',
        hint: 'Barcode mit etwas Abstand vollständig inklusive der freien Ränder zeigen.',
        formatsToSupport: getSerialScannerFormats(),
        wideFrame: true,
        normalizeUpcAAsEan13: true
    });
}

async function handleQrResult(text) {
    const value = String(text || '').trim();
    const match = value.match(/FFW-\d+/i);
    const exactCode = match ? match[0].toUpperCase() : value;
    document.getElementById('search-input').value = exactCode;
    try {
        const object = await api('/api/objects/resolve-code?q=' + encodeURIComponent(value));
        await openObject(object.id, { replaceHistory: true });
    } catch (_) {
        await applyFilters();
    }
}

// === Object Detail ===
async function openObject(id, options = {}) {
    try {
        const obj = await api('/api/objects/' + id);
        renderObjectDetail(obj);
        showView('detail', {
            historyData: { objectId: Number(id) },
            replaceHistory: options.replaceHistory === true,
            skipHistory: options.skipHistory === true
        });
    } catch (e) { alert('Fehler: ' + e.message); }
}

function renderObjectDetail(obj) {
    currentDetailObject = obj;
    const isStandard = currentUser.role === 'standard';
    const isFull = !isStandard;
    const isAdmin = currentUser.role === 'admin';
    const inspectionRequired = obj.inspection_required !== false;
    const canUseInspections = inspectionRequired && (isFull || (
        obj.standard_inspection_enabled && obj.standard_inspection_template_id
    ));
    const standardInspectionTemplate = isStandard ? obj.standard_inspection_template_id : null;

    // Infobox - Standortpfad mit flacher Liste auflösen
    const locationPath = obj.location ? getLocationPath(masterData.locationsFlat || [], obj.location.id) : '';
    let infoboxHtml = `
        <h3>${escapeHtml(obj.designation)}</h3>
        ${obj.title_image ? `<img src="/uploads/images/${obj.title_image}" alt="Titelbild">` : ''}
        <table>
            <tr><td>ID</td><td><strong>${obj.object_number}</strong></td></tr>
            <tr><td>Typ</td><td>${obj.object_type ? obj.object_type.name : '-'}</td></tr>
            <tr><td>Hersteller</td><td>${obj.manufacturer ? obj.manufacturer.name : '-'}</td></tr>
            <tr><td>Lieferant</td><td>${obj.supplier ? escapeHtml(obj.supplier.name) : '-'}</td></tr>
            <tr><td>Unterbringung</td><td>${obj.location ? `<a href="#" onclick="event.preventDefault(); showObjectsByLocation(${obj.location.id}, '${escapeHtml(locationPath)}')">${escapeHtml(locationPath)}</a>` : '-'}</td></tr>
            ${isFull ? `<tr><td>Seriennummer</td><td>${escapeHtml(obj.serial_number || '-')}</td></tr>` : ''}
            ${isFull ? `<tr><td>Anschaffung</td><td>${obj.acquisition_date || '-'}</td></tr>` : ''}
            <tr><td>Prüfung</td><td>${inspectionRequired ? 'Erforderlich' : '<strong>Nicht erforderlich</strong>'}</td></tr>
            <tr><td>Status</td><td><span class="badge badge-${obj.status}">${formatStatus(obj.status)}</span></td></tr>
        </table>
        ${obj.qr_code ? `<div style="text-align:center;margin-top:1rem;"><img src="/uploads/qrcodes/${obj.qr_code.filename}" style="width:120px;"><br><small>${obj.object_number}</small></div>` : ''}
        ${isFull ? `
            <div style="margin-top:1rem;text-align:center;">
                <a href="/api/objects/${obj.id}/sticker/print?t=${Date.now()}" class="btn-primary btn-small">🖨️ Aufkleber</a>
            </div>
        ` : ''}
    `;
    document.getElementById('detail-infobox').innerHTML = infoboxHtml;

    // Content
    const mobileSummaryImage = obj.title_image
        ? `<img src="/uploads/images/${escapeHtml(obj.title_image)}" alt="${escapeHtml(obj.designation)}" onclick="window.open(this.src)" loading="eager">`
        : `<div class="mobile-object-summary-placeholder" aria-hidden="true">🧰</div>`;
    let contentHtml = `
        <section class="mobile-object-summary" aria-label="Geräteübersicht">
            <div class="mobile-object-summary-image">${mobileSummaryImage}</div>
            <div class="mobile-object-summary-main">
                <span class="mobile-object-summary-number">${escapeHtml(obj.object_number)}</span>
                <h1>${escapeHtml(obj.designation)}</h1>
                <p>${escapeHtml(obj.object_type ? obj.object_type.name : 'Ohne Kategorie')}</p>
                <div class="mobile-object-summary-meta">
                    <span class="badge badge-${obj.status}">${formatStatus(obj.status)}</span>
                    ${isFull && obj.serial_number ? `<span class="mobile-object-summary-serial">SN ${escapeHtml(obj.serial_number)}</span>` : ''}
                </div>
            </div>
        </section>
        <div class="wiki-actions">
            <button class="btn-secondary btn-small" onclick="navigateBack('search')">← Zurück</button>
            ${isFull ? `<button class="btn-primary btn-small" onclick="editObject(${obj.id})">✏️ Bearbeiten</button>` : ''}
            ${isAdmin ? `<button class="btn-primary btn-small btn-delete" onclick="deleteObjectWithConfirm(${obj.id}, ${obj.inspections && obj.inspections.length > 0 ? 'true' : 'false'})">🗑️ Löschen</button>` : ''}
        </div>
        <section class="object-quick-actions" aria-label="Schnellaktionen">
            <div class="quick-actions-heading">
                <span>⚡</span>
                <div><h2>Schnellaktionen</h2><p>Häufige Aufgaben direkt ausführen.</p></div>
            </div>
            <div class="quick-actions-grid">
                ${canUseInspections ? `<button type="button" class="quick-action-button primary" onclick="openInspectionModal(${obj.id}, ${standardInspectionTemplate || 'null'})"><span>✅</span><strong>Prüfung starten</strong></button>` : ''}
                <button type="button" class="quick-action-button" onclick="openMessageForObject(${obj.id})"><span>📝</span><strong>Schaden melden</strong></button>
                ${isFull ? `<button type="button" class="quick-action-button" onclick="openQuickUpdate(${obj.id})"><span>📍</span><strong>Standort / Status</strong></button>` : ''}
                ${isFull ? `<button type="button" class="quick-action-button" onclick="editObject(${obj.id})"><span>✏️</span><strong>Daten bearbeiten</strong></button>` : ''}
            </div>
        </section>
    `;

    if (obj.info_text) {
        contentHtml += `<h2>Information</h2><p>${escapeHtml(obj.info_text).replace(/\n/g, '<br>')}</p>`;
    }
    if (obj.usage_hints) {
        contentHtml += `<h2>Hinweise zur Benutzung</h2><p>${escapeHtml(obj.usage_hints).replace(/\n/g, '<br>')}</p>`;
    }

    // Dokumente (nur öffentliche für Standard)
    let docs = obj.documents || [];
    if (isStandard) docs = docs.filter(d => d.is_public);
    if (docs.length) {
        contentHtml += `<h2>Dokumente</h2><div class="doc-list">`;
        contentHtml += docs.map(renderDocumentEntry).join('');
        contentHtml += `</div>`;
    }

    // Upload-Bereich für berechtigte Nutzer
    if (isFull) {
        const documentLabelOptions = (masterData.documentLabels || []).map(label =>
            `<option value="${label.id}">${escapeHtml(label.name)}</option>`
        ).join('');
        contentHtml += `
            <h2>Dokumente hochladen</h2>
            <div class="detail-document-upload">
                <label for="detail-doc-label">Label</label>
                <select id="detail-doc-label"><option value="">-- Label auswählen --</option>${documentLabelOptions}</select>
                <label for="detail-doc-upload">Datei auswählen</label>
                <input type="file" id="detail-doc-upload" multiple accept=".pdf,.txt,.md,image/*" onchange="uploadDetailDocs(${obj.id})">
                <small>PDF, Bilder oder Textdateien. Das gewählte Label gilt für alle ausgewählten Dateien.</small>
            </div>
        `;
    }

    if (isFull) {
        if (obj.images && obj.images.length) {
            contentHtml += `<h2>Bilder</h2><div class="gallery">`;
            contentHtml += obj.images.map(img => `
                <img src="/uploads/images/${img.filename}" title="${escapeHtml(img.caption || '')}" onclick="window.open(this.src)">
            `).join('');
            contentHtml += `</div>`;
        }

        // Alle hinterlegten Prüffristen sowie Folgetermine aus Prüfkarten anzeigen.
        const deadlineEntries = [];
        (obj.maintenances || []).forEach(maintenance => deadlineEntries.push({
            name: maintenance.description || 'Allgemeine Prüfung / Wartung',
            nextDate: maintenance.next_maintenance_date,
            intervalDays: maintenance.interval_days,
            notes: maintenance.notes,
            lastDate: maintenance.last_maintenance_date,
            source: 'schedule'
        }));
        const seenInspectionTemplates = new Set();
        (obj.inspections || []).forEach(inspection => {
            if (inspection.maintenance_id || !inspection.next_inspection_date || seenInspectionTemplates.has(inspection.template_id)) return;
            seenInspectionTemplates.add(inspection.template_id);
            deadlineEntries.push({
                name: inspection.template_name || 'Prüfung',
                nextDate: inspection.next_inspection_date,
                notes: inspection.notes,
                lastDate: inspection.inspected_at,
                inspector: inspection.inspector_name || inspection.inspected_by_name,
                source: 'inspection'
            });
        });
        deadlineEntries.sort((a, b) => {
            if (!a.nextDate) return 1;
            if (!b.nextDate) return -1;
            return new Date(a.nextDate) - new Date(b.nextDate);
        });
        if (inspectionRequired && deadlineEntries.length) {
            contentHtml += `<h2>📝 Prüffristen</h2><div class="object-deadline-list">`;
            contentHtml += deadlineEntries.map(entry => {
                const daysLeft = entry.nextDate ? daysUntil(entry.nextDate) : null;
                const dateLabel = entry.nextDate
                    ? new Date(entry.nextDate + 'T00:00:00').toLocaleDateString('de-DE')
                    : 'Noch nicht festgelegt';
                return `
                    <article class="alert object-deadline-card ${daysLeft !== null && daysLeft < 0 ? 'alert-danger' : (daysLeft !== null && daysLeft <= 7 ? 'alert-warning' : '')}">
                        <strong class="object-deadline-name">${escapeHtml(entry.name)}</strong>
                        <span><strong>Nächster Termin:</strong> ${dateLabel}</span>
                        ${daysLeft !== null ? `<span><strong>Restzeit:</strong> ${daysLeft < 0 ? `${Math.abs(daysLeft)} Tage überfällig` : `${daysLeft} Tage`}</span>` : ''}
                        ${entry.intervalDays ? `<span><strong>Intervall:</strong> ${entry.intervalDays} Tage</span>` : ''}
                        ${entry.source === 'inspection' && entry.lastDate ? `<span><strong>Letzte Prüfung:</strong> ${new Date(entry.lastDate).toLocaleDateString('de-DE')}${entry.inspector ? ` · ${escapeHtml(entry.inspector)}` : ''}</span>` : ''}
                        ${entry.notes && entry.notes.trim() !== entry.name.trim() ? `<small>${escapeHtml(entry.notes)}</small>` : ''}
                    </article>
                `;
            }).join('');
            contentHtml += `</div>`;
        }

        if (obj.repairs && obj.repairs.length) {
            contentHtml += `<h2>Reparaturverlauf</h2><table><thead><tr><th>Datum</th><th>Beschreibung</th><th>Kosten</th></tr></thead><tbody>`;
            contentHtml += obj.repairs.map(r => `
                <tr><td>${r.date}</td><td>${escapeHtml(r.description)}</td><td>${r.cost ? r.cost.toFixed(2) + ' €' : '-'}</td></tr>
            `).join('');
            contentHtml += `</tbody></table>`;
        }

        contentHtml += `
            <section id="object-message-history" class="object-message-history-section" aria-live="polite">
                <h2>🧾 Meldungs- und Reparaturhistorie</h2>
                <p>Verknüpfte Meldungen und ihre vollständigen Verläufe werden geladen …</p>
            </section>
        `;
    }

    // Für Standardnutzer ist der gesamte Prüfbereich nur bei aktivierter Objektfreigabe sichtbar.
    if (canUseInspections) {
        contentHtml += `<h2>Prüfungen</h2>`;
        contentHtml += `<button class="btn-primary btn-small" onclick="openInspectionModal(${obj.id}, ${standardInspectionTemplate || 'null'})">+ Neue Prüfung</button>`;
    }
    if (canUseInspections && obj.inspections && obj.inspections.length) {
        contentHtml += `<div style="margin-top:0.5rem;">`;
        obj.inspections.forEach(i => {
            const results = JSON.parse(i.results || '{}');
            // Kurze Zusammenfassung: Anzahl OK / Nicht OK
            let okCount = 0, failCount = 0;
            Object.entries(results).forEach(([k, v]) => {
                if (v === true) okCount++;
                else if (v === false) failCount++;
            });
            const statusBadge = failCount > 0
                ? `<span class="badge badge-in_reparatur">${failCount} Mängel</span>`
                : `<span class="badge badge-in_benutzung">OK</span>`;

            // Prüfe ob Prüfung noch innerhalb von 2 Stunden bearbeitbar ist
            // WICHTIG: 'Z' anhängen damit JavaScript es als UTC interpretiert (Server speichert UTC)
            const inspectedDate = new Date(i.inspected_at + 'Z');
            const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000);
            const canEdit = inspectedDate > twoHoursAgo;

            contentHtml += `
                <div class="alert" style="margin-bottom:0.5rem;">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:0.5rem;">
                        <div>
                            <strong>${i.template_name || 'Prüfung'}</strong> ${statusBadge}<br>
                            <small>📅 ${new Date(i.inspected_at).toLocaleDateString('de-DE')} | 👤 ${escapeHtml(i.inspector_name || i.inspected_by_name || '-')} ${i.images && i.images.length ? `| 📷 ${i.images.length}` : ''}</small>
                        </div>
                        <div style="display:flex; gap:0.3rem;">
                            ${canEdit ? `<button class="btn-primary btn-small" onclick="editInspection(${i.id})">✏️ Bearbeiten</button>` : ''}
                            <button class="btn-primary btn-small" onclick="viewInspection(${i.id})">👁️ Ansehen</button>
                        </div>
                    </div>
                    ${i.maintenance_description ? `<small style="display:block; margin-top:0.3rem; color:#2e7d32;">✓ Prüffrist zurückgesetzt: ${escapeHtml(i.maintenance_description)}</small>` : ''}
                    ${i.next_inspection_date ? `<small style="display:block; margin-top:0.3rem;">Nächste Prüfung: ${i.next_inspection_date}</small>` : ''}
                    ${canEdit ? '<small style="color:#1976d2;">✎ Noch bearbeitbar (innerhalb 2h)</small>' : ''}
                </div>
            `;
        });
        contentHtml += `</div>`;
    } else if (canUseInspections) {
        contentHtml += `<p>Keine Prüfungen vorhanden.</p>`;
    }

    document.getElementById('detail-content').innerHTML = contentHtml;
    if (isFull) loadObjectMessageHistory(obj.id);
}

async function loadObjectMessageHistory(objectId) {
    const container = document.getElementById('object-message-history');
    if (!container) return;
    try {
        const objectMessages = await api(`/api/objects/${objectId}/message-history`);
        renderObjectMessageHistory(container, objectMessages);
    } catch (error) {
        container.innerHTML = `
            <h2>🧾 Meldungs- und Reparaturhistorie</h2>
            <p class="form-message error">Historie konnte nicht geladen werden: ${escapeHtml(error.message)}</p>
        `;
    }
}

function renderObjectMessageHistory(container, objectMessages, context = 'object') {
    const archiveContext = context === 'archive' || context === 'archive-results';
    const showHeading = context !== 'archive-results';
    const statusLabels = {
        offen: 'Offen',
        in_bearbeitung: 'In Bearbeitung',
        in_klaerung: 'In Klärung',
        zur_reparatur: 'Zur Reparatur',
        bedienungsfehler: 'Bedienungsfehler',
        nicht_mehr_aufgetreten: 'Fehler nicht mehr aufgetreten',
        geprueft_ok: 'Gerät geprüft u. in Ordnung',
        entsorgt: 'Entsorgt',
        abgeschlossen: 'Abgeschlossen',
        wieder_geoeffnet: 'Wieder geöffnet',
        geloescht: 'Früher entfernt'
    };
    const archiveLabels = {
        abgeschlossen: 'Abgeschlossen',
        entsorgt: 'Entsorgt',
        weiter_in_klaerung: 'Weiter in Klärung'
    };

    if (!objectMessages.length) {
        container.innerHTML = `
            ${showHeading ? `<h2>${archiveContext ? '🗄️ Meldungsarchiv' : '🧾 Meldungs- und Reparaturhistorie'}</h2>` : ''}
            <p>${archiveContext ? 'Keine archivierten Vorgänge passen zu den gewählten Filtern.' : 'Für diesen Inventarartikel sind noch keine Meldungen hinterlegt.'}</p>
        `;
        return;
    }

    container.innerHTML = `
        ${showHeading ? `<h2>${archiveContext ? '🗄️ Meldungsarchiv' : '🧾 Meldungs- und Reparaturhistorie'}</h2>` : ''}
        ${showHeading ? `<p>${archiveContext
            ? 'Nur für berechtigte Nutzer. Hier bleiben alle aus der aktuellen Liste entfernten Vorgänge dauerhaft abrufbar.'
            : 'Auch entfernte und abgeschlossene Vorgänge bleiben hier mit Bildern und Verlauf erhalten.'}</p>` : ''}
        ${objectMessages.map(message => {
            const isArchived = message.is_archived || message.status === 'geloescht';
            const archiveText = message.is_archived
                ? `Archiviert: ${archiveLabels[message.archive_reason] || message.archive_reason || statusLabels[message.status] || message.status}`
                : message.status === 'geloescht'
                    ? 'Früher aus den aktuellen Meldungen entfernt'
                    : `Aktuell: ${statusLabels[message.status] || message.status}`;
            const history = Array.isArray(message.history) ? message.history : [];
            return `
                <details class="object-message-history-card ${isArchived ? 'archived' : ''}">
                    <summary>${new Date(message.created_at).toLocaleDateString('de-DE')} · ${escapeHtml(message.subject)} · ${escapeHtml(archiveText)}</summary>
                    <div class="object-message-history-card-meta">
                        Erstellt von ${escapeHtml(message.reported_by_name || message.created_by_name)}
                        ${archiveContext && (message.device_name || message.device_id) ? ` · Artikel: ${escapeHtml(message.device_name || '-')}${message.device_id ? ` (${escapeHtml(message.device_id)})` : ''}` : ''}
                        ${message.archived_at ? ` · Archiviert am ${new Date(message.archived_at).toLocaleString('de-DE')} von ${escapeHtml(message.archived_by_name || '-')}` : ''}
                    </div>
                    <div class="object-message-history-card-body">
                        ${message.description ? `<p>${escapeHtml(message.description)}</p>` : ''}
                        ${message.action ? `<p><strong>Maßnahme:</strong> ${escapeHtml(message.action)}${message.action_comment ? ` · ${escapeHtml(message.action_comment)}` : ''}</p>` : ''}
                        ${message.images && message.images.length ? `
                            <div class="message-image-gallery object-message-history-images">
                                ${message.images.map((image, index) => `
                                    <figure>
                                        <img src="/uploads/message_images/${encodeURIComponent(image.filename)}" alt="Schadensbild ${index + 1}" onclick="window.open(this.src, '_blank')">
                                        <figcaption>${escapeHtml(image.comment)}</figcaption>
                                    </figure>
                                `).join('')}
                            </div>
                        ` : ''}
                        ${history.length ? `
                            <ol class="message-history-list">
                                ${history.map(entry => {
                                    const label = entry.entry_type === 'comment'
                                        ? 'Kommentar'
                                        : entry.entry_type === 'archive'
                                            ? 'Archiviert'
                                            : entry.entry_type === 'visibility'
                                                ? 'Sichtbarkeit'
                                                : (statusLabels[entry.status] || entry.status || 'Status geändert');
                                    const expected = entry.expected_end_date
                                        ? ` · vsl. ${new Date(entry.expected_end_date).toLocaleDateString('de-DE')}`
                                        : '';
                                    return `
                                        <li class="${entry.entry_type === 'archive' ? 'message-history-archive' : ''}">
                                            <div class="message-history-meta">${new Date(entry.created_at).toLocaleString('de-DE')} · ${escapeHtml(entry.author_name)}</div>
                                            <div class="message-history-text"><strong>${escapeHtml(label)}</strong>${entry.details ? ` · ${escapeHtml(entry.details)}` : ''}${escapeHtml(expected)}</div>
                                        </li>
                                    `;
                                }).join('')}
                            </ol>
                        ` : '<p>Kein Verlauf vorhanden.</p>'}
                    </div>
                </details>
            `;
        }).join('')}
    `;
}

async function openMessageForObject(objectId) {
    try {
        const obj = currentDetailObject && currentDetailObject.id === objectId
            ? currentDetailObject
            : await api('/api/objects/' + objectId);
        openMessageModal();
        document.getElementById('msg-type').value = 'beschaedigung';
        document.getElementById('msg-priority').value = 'hoch';
        document.getElementById('msg-device-name').value = obj.designation || '';
        document.getElementById('msg-device-id').value = obj.object_number || '';
        document.getElementById('msg-object-id').value = obj.id;
        document.getElementById('msg-subject').focus();
    } catch (error) {
        alert('Objekt konnte nicht für die Meldung übernommen werden: ' + error.message);
    }
}

async function openQuickUpdate(objectId) {
    if (!currentUser || currentUser.role === 'standard') return;
    try {
        const obj = currentDetailObject && currentDetailObject.id === objectId
            ? currentDetailObject
            : await api('/api/objects/' + objectId);
        const locationOptions = (masterData.locationsFlat || []).map(location => ({
            id: location.id,
            name: getLocationPath(masterData.locationsFlat, location.id)
        }));
        fillSelect('quick-update-location', locationOptions, 'name');
        document.getElementById('quick-update-object-id').value = obj.id;
        document.getElementById('quick-update-object').textContent = `${obj.designation} · ${obj.object_number}`;
        document.getElementById('quick-update-location').value = obj.location ? obj.location.id : '';
        document.getElementById('quick-update-status').value = obj.status || 'in_benutzung';
        document.getElementById('quick-update-message').className = 'form-message hidden';
        document.getElementById('quick-update-modal').style.display = 'block';
    } catch (error) {
        alert('Schnellaktion konnte nicht geöffnet werden: ' + error.message);
    }
}

function closeQuickUpdate() {
    document.getElementById('quick-update-modal').style.display = 'none';
}

async function saveQuickUpdate(event) {
    event.preventDefault();
    const objectId = Number(document.getElementById('quick-update-object-id').value);
    const locationValue = document.getElementById('quick-update-location').value;
    const message = document.getElementById('quick-update-message');
    const submitButton = event.submitter;
    if (submitButton) submitButton.disabled = true;
    try {
        await api('/api/objects/' + objectId, {
            method: 'PUT',
            body: JSON.stringify({
                location_id: locationValue ? Number(locationValue) : null,
                status: document.getElementById('quick-update-status').value
            })
        });
        closeQuickUpdate();
        await openObject(objectId, { replaceHistory: true });
    } catch (error) {
        message.textContent = error.message;
        message.className = 'form-message error';
    } finally {
        if (submitButton) submitButton.disabled = false;
    }
}

function renderDocumentEntry(documentInfo) {
    const originalName = documentInfo.original_name || 'Dokument';
    const url = '/uploads/documents/' + encodeURIComponent(documentInfo.filename);
    const isPdf = /\.pdf$/i.test(originalName) || String(documentInfo.file_type || '').toLowerCase().includes('pdf');
    const label = documentInfo.label_name
        ? `<span class="document-label-badge">${escapeHtml(documentInfo.label_name)}</span>`
        : '<span class="document-label-badge unlabeled">Ohne Label</span>';
    if (isPdf) {
        return `<div class="object-document-entry">${label}<button type="button" class="doc-preview-link" onclick="openDocumentPreview('${url}', decodeURIComponent('${encodeURIComponent(originalName)}'))">📄 ${escapeHtml(originalName)}<span>Vorschau öffnen ›</span></button></div>`;
    }
    return `<div class="object-document-entry">${label}<a href="${url}" target="_blank" rel="noopener">📄 ${escapeHtml(originalName)}</a></div>`;
}

// === Dokumentensammlung ===
let documentSearchTimer = null;
let requestedDocumentLabel = null;

function canManageDocuments() {
    return currentUser && currentUser.role !== 'standard';
}

function fillDocumentLabelSelect(selectId, firstLabel, selectedValue = '') {
    const select = document.getElementById(selectId);
    if (!select) return;
    const previous = selectedValue || select.value;
    select.innerHTML = `<option value="">${escapeHtml(firstLabel)}</option>`;
    (masterData.documentLabels || []).forEach(label => {
        const option = document.createElement('option');
        option.value = label.id;
        option.textContent = label.name;
        select.appendChild(option);
    });
    if ([...select.options].some(option => option.value === String(previous))) {
        select.value = String(previous);
    }
}

function refreshDocumentLabelSelects() {
    fillDocumentLabelSelect('document-label-filter', 'Alle Labels');
    fillDocumentLabelSelect('standalone-document-label', '-- Label auswählen --');
    fillDocumentLabelSelect('obj-document-label', '-- Label auswählen --');
    fillDocumentLabelSelect('detail-doc-label', '-- Label auswählen --');
}

function openDocumentCollection(labelName = null) {
    requestedDocumentLabel = labelName || '';
    showView('documents');
}

function filterDocumentCollectionByLabel(labelName) {
    const label = (masterData.documentLabels || []).find(item => namesEqual(item.name, labelName));
    document.getElementById('document-search').value = '';
    document.getElementById('document-label-filter').value = label ? String(label.id) : '';
    document.getElementById('document-assignment-filter').value = 'all';
    loadDocumentCollection();
}

async function initializeDocumentCollection() {
    try {
        if (!masterData.documentLabels || !masterData.documentLabels.length) {
            masterData.documentLabels = await api('/api/document-labels');
        }
        refreshDocumentLabelSelects();
        const canManage = canManageDocuments();
        document.getElementById('document-upload-toggle').classList.toggle('hidden', !canManage);
        toggleDocumentUploadPanel(false);
        if (requestedDocumentLabel !== null) {
            const label = requestedDocumentLabel
                ? masterData.documentLabels.find(item => namesEqual(item.name, requestedDocumentLabel))
                : null;
            document.getElementById('document-label-filter').value = label ? String(label.id) : '';
            requestedDocumentLabel = null;
        }
        await loadDocumentCollection();
    } catch (error) {
        document.getElementById('document-library-results').innerHTML = `<div class="form-message error">${escapeHtml(error.message)}</div>`;
    }
}

function toggleDocumentUploadPanel(forceOpen = null) {
    const panel = document.getElementById('document-upload-panel');
    const button = document.getElementById('document-upload-toggle');
    if (!panel || !button || !canManageDocuments()) {
        if (panel) panel.classList.add('hidden');
        return;
    }
    const shouldOpen = forceOpen === null ? panel.classList.contains('hidden') : Boolean(forceOpen);
    panel.classList.toggle('hidden', !shouldOpen);
    button.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
    button.innerHTML = shouldOpen ? '× <span>Schließen</span>' : '＋ <span>Dokument</span>';
    if (shouldOpen) {
        panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        setTimeout(() => document.getElementById('standalone-document-file')?.focus(), 150);
    }
}

function debouncedDocumentSearch() {
    clearTimeout(documentSearchTimer);
    documentSearchTimer = setTimeout(loadDocumentCollection, 250);
}

function resetDocumentFilters() {
    document.getElementById('document-search').value = '';
    document.getElementById('document-label-filter').value = '';
    document.getElementById('document-assignment-filter').value = 'all';
    loadDocumentCollection();
}

function documentFileAction(documentInfo) {
    const name = documentInfo.original_name || 'Dokument';
    const url = '/uploads/documents/' + encodeURIComponent(documentInfo.filename);
    const isPdf = /\.pdf$/i.test(name) || String(documentInfo.file_type || '').toLowerCase().includes('pdf');
    if (isPdf) {
        return `<button type="button" class="btn-primary btn-small" onclick="openDocumentPreview('${url}', decodeURIComponent('${encodeURIComponent(name)}'))">Vorschau</button>`;
    }
    return `<a class="btn-primary btn-small" href="${url}" target="_blank" rel="noopener">Öffnen</a>`;
}

function renderDocumentLibraryItem(documentInfo) {
    const labelOptions = (masterData.documentLabels || []).map(label =>
        `<option value="${label.id}" ${documentInfo.label_id == label.id ? 'selected' : ''}>${escapeHtml(label.name)}</option>`
    ).join('');
    const association = documentInfo.object_id
        ? `<button type="button" class="document-object-link" onclick="openObject(${documentInfo.object_id})">${escapeHtml(documentInfo.object_number || '')} · ${escapeHtml(documentInfo.object_designation || 'Inventarartikel')}</button>`
        : '<span class="document-unassigned">Allgemeine Ablage · ohne Inventarartikel</span>';
    const management = canManageDocuments() ? `
        <div class="document-card-management">
            <label>Label ändern
                <select onchange="updateDocumentLabel(${documentInfo.id}, this.value)">
                    <option value="">Ohne Label</option>${labelOptions}
                </select>
            </label>
            <label class="document-public-toggle compact"><input type="checkbox" ${documentInfo.is_public ? 'checked' : ''} onchange="updateDocumentVisibility(${documentInfo.id}, this.checked)"> Für Standardnutzer sichtbar</label>
        </div>` : '';
    return `
        <article class="document-library-card">
            <div class="document-library-icon">${documentInfo.file_type === 'image' ? '🖼️' : '📄'}</div>
            <div class="document-library-card-main">
                <div class="document-library-card-labels">
                    <span class="document-label-badge ${documentInfo.label_name ? '' : 'unlabeled'}">${escapeHtml(documentInfo.label_name || 'Ohne Label')}</span>
                    ${documentInfo.is_public ? '<span class="document-visibility-badge">Standard sichtbar</span>' : '<span class="document-visibility-badge private">Nur berechtigte Nutzer</span>'}
                </div>
                <h3>${escapeHtml(documentInfo.original_name)}</h3>
                <div class="document-library-association">${association}</div>
                <small>Hochgeladen ${documentInfo.uploaded_at ? new Date(documentInfo.uploaded_at).toLocaleString('de-DE') : ''}${documentInfo.uploaded_by_name ? ` · ${escapeHtml(documentInfo.uploaded_by_name)}` : ''}</small>
                ${management}
            </div>
            <div class="document-library-card-action">${documentFileAction(documentInfo)}</div>
        </article>`;
}

async function loadDocumentCollection() {
    const results = document.getElementById('document-library-results');
    if (!results) return;
    results.innerHTML = '<p>Dokumente werden geladen …</p>';
    const params = new URLSearchParams();
    const query = document.getElementById('document-search').value.trim();
    const labelId = document.getElementById('document-label-filter').value;
    const assignment = document.getElementById('document-assignment-filter').value;
    if (query) params.set('q', query);
    if (labelId) params.set('label_id', labelId);
    params.set('assignment', assignment);
    try {
        const documents = await api('/api/documents?' + params.toString());
        document.getElementById('document-library-summary').textContent = `${documents.length} ${documents.length === 1 ? 'Dokument' : 'Dokumente'} gefunden`;
        results.innerHTML = documents.length
            ? documents.map(renderDocumentLibraryItem).join('')
            : '<div class="empty-state"><span>📭</span><h3>Keine Dokumente gefunden</h3><p>Filter ändern oder ein neues Dokument hochladen.</p></div>';
    } catch (error) {
        results.innerHTML = `<div class="form-message error">${escapeHtml(error.message)}</div>`;
    }
}

async function uploadStandaloneDocument(event) {
    event.preventDefault();
    const fileInput = document.getElementById('standalone-document-file');
    const labelId = document.getElementById('standalone-document-label').value;
    if (!fileInput.files.length || !labelId) return alert('Bitte Datei und Label auswählen.');
    const button = event.submitter;
    if (button) button.disabled = true;
    const files = [...fileInput.files];
    const isPublic = document.getElementById('standalone-document-public').checked;
    try {
        for (const file of files) {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('label_id', labelId);
            formData.append('is_public', isPublic ? 'true' : 'false');
            await uploadFile('/api/documents', formData);
        }
        document.getElementById('standalone-document-form').reset();
        document.getElementById('standalone-document-public').checked = true;
        await loadDocumentCollection();
        toggleDocumentUploadPanel(false);
        alert(`${files.length} ${files.length === 1 ? 'Dokument wurde' : 'Dokumente wurden'} in der Sammlung abgelegt.`);
    } catch (error) {
        alert('Dokument konnte nicht hochgeladen werden: ' + error.message);
    } finally {
        if (button) button.disabled = false;
    }
}

async function createDocumentLabel() {
    const input = document.getElementById('new-document-label');
    const name = input.value.trim();
    if (!name) return alert('Bitte einen Namen für das neue Label eingeben.');
    try {
        const label = await api('/api/document-labels', { method: 'POST', body: JSON.stringify({ name }) });
        masterData.documentLabels.push(label);
        masterData.documentLabels.sort((a, b) => a.name.localeCompare(b.name, 'de'));
        input.value = '';
        refreshDocumentLabelSelects();
        document.getElementById('standalone-document-label').value = String(label.id);
    } catch (error) {
        alert('Label konnte nicht angelegt werden: ' + error.message);
    }
}

async function updateDocumentLabel(documentId, labelId) {
    try {
        await api('/api/documents/' + documentId, {
            method: 'PUT',
            body: JSON.stringify({ label_id: labelId ? Number(labelId) : null })
        });
        await loadDocumentCollection();
    } catch (error) {
        alert('Label konnte nicht geändert werden: ' + error.message);
        await loadDocumentCollection();
    }
}

async function updateDocumentVisibility(documentId, isPublic) {
    try {
        await api('/api/documents/' + documentId, {
            method: 'PUT',
            body: JSON.stringify({ is_public: isPublic })
        });
        await loadDocumentCollection();
    } catch (error) {
        alert('Sichtbarkeit konnte nicht geändert werden: ' + error.message);
        await loadDocumentCollection();
    }
}

function openDocumentPreview(url, name, options = {}) {
    if (!String(url).startsWith('/uploads/documents/')) {
        alert('Ungültiger Dokumentpfad.');
        return;
    }
    const documentName = name || 'PDF-Dokument';
    document.getElementById('document-preview-name').textContent = documentName;
    document.getElementById('document-preview-frame').data = url;
    document.getElementById('document-preview-external').href = url;
    document.getElementById('document-preview-fallback-link').href = url;
    showView('document', {
        historyData: { url, name: documentName },
        replaceHistory: options.replaceHistory === true,
        skipHistory: options.skipHistory === true
    });
}

function closeDocumentPreview() {
    const frame = document.getElementById('document-preview-frame');
    if (frame) frame.removeAttribute('data');
}

async function uploadDetailDocs(objectId) {
    const input = document.getElementById('detail-doc-upload');
    if (!input.files.length) return;
    const labelId = document.getElementById('detail-doc-label').value;
    if (!labelId) return alert('Bitte vor dem Hochladen ein Dokumentenlabel auswählen.');
    for (const file of input.files) {
        const fd = new FormData();
        fd.append('file', file);
        fd.append('label_id', labelId);
        fd.append('is_public', 'true');
        try {
            await uploadFile('/api/objects/' + objectId + '/documents', fd);
        } catch (e) { alert('Fehler beim Upload: ' + e.message); }
    }
    alert('Dokumente hochgeladen!');
    openObject(objectId);
}

function daysUntil(dateStr) {
    const today = new Date(); today.setHours(0,0,0,0);
    const target = new Date(dateStr);
    return Math.ceil((target - today) / (1000 * 60 * 60 * 24));
}

// === Object Form ===
let objectInspectionTemplates = [];

async function loadObjectInspectionTemplates(selectedId = null) {
    const select = document.getElementById('obj-standard-inspection-template');
    select.innerHTML = '<option value="">-- Prüfkarte auswählen --</option>';
    select.disabled = true;
    try {
        objectInspectionTemplates = await api('/api/inspection-templates');
        objectInspectionTemplates.forEach(template => {
            const option = document.createElement('option');
            option.value = template.id;
            const typeName = template.object_type_id
                ? masterData.types.find(type => type.id == template.object_type_id)?.name
                : null;
            option.textContent = typeName ? `${template.name} · ${typeName}` : template.name;
            select.appendChild(option);
        });
        if (selectedId) select.value = String(selectedId);
    } catch (error) {
        showFormMessage('Prüfkarten konnten nicht geladen werden: ' + error.message);
    } finally {
        toggleStandardInspectionSettings();
    }
}

function toggleStandardInspectionSettings() {
    const inspectionRequired = document.getElementById('obj-inspection-required').checked;
    const checkbox = document.getElementById('obj-standard-inspection-enabled');
    checkbox.disabled = !inspectionRequired;
    if (!inspectionRequired) checkbox.checked = false;
    const enabled = inspectionRequired && checkbox.checked;
    const box = document.getElementById('obj-standard-inspection-template-box');
    const select = document.getElementById('obj-standard-inspection-template');
    box.classList.toggle('hidden', !enabled);
    select.required = enabled;
    select.disabled = !enabled;
    if (!enabled) select.value = '';
}

let maintenanceScheduleCounter = 0;

function refreshMaintenanceScheduleControls() {
    const rows = [...document.querySelectorAll('#obj-maintenance-schedules .maintenance-schedule-card')];
    rows.forEach((row, index) => {
        const title = row.querySelector('.maintenance-schedule-title');
        if (title) title.textContent = `Prüffrist ${index + 1}`;
        const removeButton = row.querySelector('.maintenance-schedule-remove');
        if (removeButton) removeButton.setAttribute('aria-label', `Prüffrist ${index + 1} entfernen`);
    });
    const addButton = document.getElementById('add-maintenance-schedule');
    const limit = document.getElementById('maintenance-schedule-limit');
    const remaining = Math.max(0, 3 - rows.length);
    addButton.disabled = remaining === 0 || !document.getElementById('obj-inspection-required').checked;
    limit.textContent = remaining === 0
        ? 'Maximal drei Prüffristen erreicht.'
        : `${remaining} weitere ${remaining === 1 ? 'Prüffrist' : 'Prüffristen'} möglich.`;
}

function addMaintenanceSchedule(schedule = {}) {
    const container = document.getElementById('obj-maintenance-schedules');
    if (container.children.length >= 3) {
        showFormMessage('Pro Artikel können höchstens drei Prüffristen angelegt werden.');
        return;
    }
    const rowId = ++maintenanceScheduleCounter;
    const article = document.createElement('article');
    article.className = 'maintenance-schedule-card';
    article.dataset.maintenanceRow = String(rowId);
    article.innerHTML = `
        <input type="hidden" class="maintenance-id" value="${schedule.id || ''}">
        <div class="maintenance-schedule-card-heading">
            <strong class="maintenance-schedule-title">Prüffrist</strong>
            <button type="button" class="maintenance-schedule-remove btn-secondary btn-small" onclick="removeMaintenanceSchedule(this)">Entfernen</button>
        </div>
        <div class="maintenance-schedule-grid">
            <div class="form-field maintenance-description-field">
                <label for="maintenance-description-${rowId}">Bezeichnung <span class="required-mark">*</span></label>
                <input type="text" id="maintenance-description-${rowId}" class="maintenance-description" maxlength="120" required
                    placeholder="z. B. TÜV oder Herstellerprüfung" value="${escapeHtml(schedule.description || '')}">
            </div>
            <div class="form-field">
                <label for="maintenance-interval-${rowId}">Intervall <span class="required-mark">*</span></label>
                <div class="input-with-suffix"><input type="number" id="maintenance-interval-${rowId}" class="maintenance-interval" min="1" max="36500" inputmode="numeric" required placeholder="z. B. 365" value="${schedule.interval_days || ''}"><span>Tage</span></div>
            </div>
            <div class="form-field">
                <label for="maintenance-next-date-${rowId}">Nächster Termin</label>
                <input type="date" id="maintenance-next-date-${rowId}" class="maintenance-next-date" value="${escapeHtml(schedule.next_maintenance_date || '')}">
                <small class="field-help">Leer lassen: wird aus Anschaffungsdatum + Intervall berechnet.</small>
            </div>
            <div class="form-field maintenance-notes-field">
                <label for="maintenance-notes-${rowId}">Hinweise</label>
                <textarea id="maintenance-notes-${rowId}" class="maintenance-notes" rows="2" placeholder="Besonderheiten oder Prüfvorgaben">${escapeHtml(schedule.notes || '')}</textarea>
            </div>
        </div>
    `;
    container.appendChild(article);
    refreshMaintenanceScheduleControls();
}

function removeMaintenanceSchedule(button) {
    button.closest('.maintenance-schedule-card')?.remove();
    refreshMaintenanceScheduleControls();
}

function resetMaintenanceSchedules(schedules = []) {
    const container = document.getElementById('obj-maintenance-schedules');
    container.innerHTML = '';
    maintenanceScheduleCounter = 0;
    schedules.slice(0, 3).forEach(schedule => addMaintenanceSchedule(schedule));
    refreshMaintenanceScheduleControls();
}

function collectMaintenanceSchedules() {
    return [...document.querySelectorAll('#obj-maintenance-schedules .maintenance-schedule-card')].map(row => ({
        id: parseInt(row.querySelector('.maintenance-id').value) || null,
        description: row.querySelector('.maintenance-description').value.trim(),
        interval_days: parseInt(row.querySelector('.maintenance-interval').value),
        next_maintenance_date: row.querySelector('.maintenance-next-date').value || null,
        notes: row.querySelector('.maintenance-notes').value.trim() || null
    }));
}

function toggleInspectionRequiredSettings() {
    const required = document.getElementById('obj-inspection-required').checked;
    document.querySelectorAll('#object-form .inspection-dependent-setting').forEach(field => {
        field.classList.toggle('hidden', !required);
    });
    document.querySelectorAll('#obj-maintenance-schedules input, #obj-maintenance-schedules textarea, #obj-maintenance-schedules button').forEach(control => {
        control.disabled = !required;
    });
    document.getElementById('add-maintenance-schedule').disabled = !required;
    refreshMaintenanceScheduleControls();
    toggleStandardInspectionSettings();
}

function openNewObjectForm(options = {}) {
    const form = document.getElementById('object-form');
    form.reset();
    document.getElementById('edit-object-id').value = '';
    document.getElementById('form-title').textContent = 'Objekt anlegen';
    document.getElementById('obj-status').value = 'in_benutzung';
    document.getElementById('new-location-type').value = 'Standort';
    document.getElementById('vehicle-location-box').classList.add('hidden');
    document.getElementById('obj-inspection-required').checked = true;
    document.getElementById('obj-standard-inspection-enabled').checked = false;
    resetMaintenanceSchedules([{}]);
    toggleInspectionRequiredSettings();
    loadObjectInspectionTemplates();
    setObjectLocation(null);
    hideInlineAdd('manufacturer');
    hideInlineAdd('supplier');
    hideInlineAdd('location');
    clearInlineFeedback('serial-scan-feedback');
    clearFormMessage();
    showView('edit-object', {
        replaceHistory: options.replaceHistory === true,
        skipHistory: options.skipHistory === true
    });
    setTimeout(() => document.getElementById('obj-designation').focus(), 0);
}

async function saveObject(e) {
    e.preventDefault();
    clearFormMessage();
    const id = document.getElementById('edit-object-id').value;
    const pendingDocuments = document.getElementById('obj-documents').files;
    const pendingDocumentLabelId = document.getElementById('obj-document-label').value;
    if (pendingDocuments.length && !pendingDocumentLabelId) {
        showFormMessage('Bitte für die ausgewählten Dokumente ein Label festlegen.');
        document.getElementById('obj-document-label').focus();
        return;
    }
    const inspectionRequired = document.getElementById('obj-inspection-required').checked;
    const standardInspectionEnabled = inspectionRequired && document.getElementById('obj-standard-inspection-enabled').checked;
    const standardInspectionTemplateId = parseInt(document.getElementById('obj-standard-inspection-template').value) || null;
    if (standardInspectionEnabled && !standardInspectionTemplateId) {
        showFormMessage('Bitte eine Prüfkarte für Standardnutzer auswählen.');
        document.getElementById('obj-standard-inspection-template').focus();
        return;
    }
    const maintenanceSchedules = inspectionRequired ? collectMaintenanceSchedules() : [];
    const invalidSchedule = maintenanceSchedules.find(schedule =>
        !schedule.description || !Number.isInteger(schedule.interval_days) || schedule.interval_days < 1 || schedule.interval_days > 36500
    );
    if (invalidSchedule) {
        showFormMessage('Bitte für jede Prüffrist eine Bezeichnung und ein gültiges Intervall eintragen.');
        return;
    }
    const data = {
        object_type_id: parseInt(document.getElementById('obj-type').value) || null,
        designation: document.getElementById('obj-designation').value,
        serial_number: document.getElementById('obj-serial').value || null,
        manufacturer_id: parseInt(document.getElementById('obj-manufacturer').value) || null,
        supplier_id: parseInt(document.getElementById('obj-supplier').value) || null,
        location_id: parseInt(document.getElementById('obj-location').value) || null,
        info_text: document.getElementById('obj-info').value || null,
        usage_hints: document.getElementById('obj-hints').value || null,
        acquisition_date: document.getElementById('obj-acquisition').value || null,
        status: document.getElementById('obj-status').value,
        inspection_required: inspectionRequired,
        standard_inspection_enabled: standardInspectionEnabled,
        standard_inspection_template_id: standardInspectionEnabled ? standardInspectionTemplateId : null,
        maintenance_schedules: maintenanceSchedules
    };

    // Neuer Hersteller?
    const newManu = document.getElementById('new-manufacturer').value.trim();
    if (newManu && !data.manufacturer_id) {
        const existing = masterData.manufacturers.find(m => namesEqual(m.name, newManu));
        if (existing) {
            data.manufacturer_id = existing.id;
            document.getElementById('obj-manufacturer').value = existing.id;
        } else {
            try {
                const m = await api('/api/manufacturers', { method: 'POST', body: JSON.stringify({ name: newManu }) });
                data.manufacturer_id = m.id;
                masterData.manufacturers.push(m);
                fillSelect('obj-manufacturer', masterData.manufacturers, 'name');
                document.getElementById('obj-manufacturer').value = m.id;
            } catch (e) {
                showFormMessage('Hersteller konnte nicht angelegt werden: ' + e.message);
                return;
            }
        }
    }

    // Neuer Lieferant?
    const newSupplier = document.getElementById('new-supplier').value.trim();
    if (newSupplier && !data.supplier_id) {
        const existing = masterData.suppliers.find(supplier => namesEqual(supplier.name, newSupplier));
        if (existing) {
            data.supplier_id = existing.id;
            document.getElementById('obj-supplier').value = existing.id;
        } else {
            try {
                const supplier = await api('/api/suppliers', { method: 'POST', body: JSON.stringify({ name: newSupplier }) });
                data.supplier_id = supplier.id;
                masterData.suppliers.push(supplier);
                fillSelect('obj-supplier', masterData.suppliers, 'name');
                document.getElementById('obj-supplier').value = supplier.id;
            } catch (error) {
                showFormMessage('Lieferant konnte nicht angelegt werden: ' + error.message);
                return;
            }
        }
    }

    // Neuer Standort?
    const newLoc = document.getElementById('new-location').value.trim();
    const newLocType = document.getElementById('new-location-type').value.trim();
    if (newLoc && !data.location_id) {
        const parentValue = document.getElementById('new-location-parent').value || null;
        const existing = (masterData.locationsFlat || []).find(l =>
            namesEqual(l.name, newLoc) && String(l.parent_id || '') === String(parentValue || '')
        );
        if (existing) {
            data.location_id = existing.id;
            setObjectLocation(existing.id);
        } else {
            try {
                const loc = await api('/api/locations', {
                    method: 'POST',
                    body: JSON.stringify({
                        name: newLoc,
                        location_type: newLocType || 'Standort',
                        parent_id: parentValue ? parseInt(parentValue) : null
                    })
                });
                data.location_id = loc.id;
                const allLocations = await api('/api/locations/all');
                masterData.locationsFlat = allLocations;
                masterData.locations = buildLocationTree(allLocations);
                fillSelect('obj-location', allLocations.map(l => ({ id: l.id, name: getLocationPath(allLocations, l.id) })), 'name');
                setObjectLocation(loc.id);
            } catch (e) {
                showFormMessage('Standort konnte nicht angelegt werden: ' + e.message);
                return;
            }
        }
    }

    try {
        const url = id ? '/api/objects/' + id : '/api/objects';
        const method = id ? 'PUT' : 'POST';
        const obj = await api(url, { method, body: JSON.stringify(data) });

        // Titelbild upload
        const titleInput = document.getElementById('obj-title-image');
        if (titleInput && titleInput.files.length) {
            const fd = new FormData();
            fd.append('file', titleInput.files[0]);
            await uploadFile('/api/objects/' + obj.id + '/title-image', fd);
        }

        // Dokumente upload
        const docInput = document.getElementById('obj-documents');
        if (docInput && docInput.files.length) {
            for (const file of docInput.files) {
                const fd = new FormData();
                fd.append('file', file);
                fd.append('label_id', pendingDocumentLabelId);
                fd.append('is_public', 'true');
                await uploadFile('/api/objects/' + obj.id + '/documents', fd);
            }
        }

        // Fahrzeuge werden automatisch im Backend als Standort angelegt
        // (keine manuelle Aktion mehr nötig)
        // Stammdaten sofort aktualisieren, damit ein automatisch erzeugter
        // Fahrzeugstandort ohne weiteren Zwischenschritt überall sichtbar ist.
        try {
            await loadMasterData();
        } catch (refreshError) {
            console.warn('Stammdaten konnten nach dem Speichern nicht sofort aktualisiert werden:', refreshError);
        }

        alert('Gespeichert!');
        // Formular zurücksetzen
        document.getElementById('object-form').reset();
        document.getElementById('edit-object-id').value = '';
        document.getElementById('new-manufacturer').value = '';
        document.getElementById('new-supplier').value = '';
        document.getElementById('new-location').value = '';
        document.getElementById('new-location-type').value = '';
        document.getElementById('vehicle-location-box').classList.add('hidden');
        document.getElementById('add-manufacturer-box').classList.add('hidden');
        document.getElementById('add-supplier-box').classList.add('hidden');
        document.getElementById('add-location-box').classList.add('hidden');
        document.getElementById('obj-standard-inspection-enabled').checked = false;
        resetMaintenanceSchedules([{}]);
        toggleStandardInspectionSettings();

        showView('search', { replaceHistory: true });
        document.getElementById('search-input').value = obj.object_number;
        applyFilters();
    } catch (e) {
        showFormMessage('Objekt konnte nicht gespeichert werden: ' + e.message);
    }
}

// === Sammelanlage ===
let bulkMaintenanceCounter = 0;
let bulkPreviewPayload = null;

function showBulkMessage(message, type = 'error') {
    const element = document.getElementById('bulk-form-message');
    element.textContent = message;
    element.className = `form-message ${type}`;
}

function clearBulkMessage() {
    const element = document.getElementById('bulk-form-message');
    element.textContent = '';
    element.className = 'form-message hidden';
}

function invalidateBulkPreview() {
    bulkPreviewPayload = null;
    document.getElementById('bulk-preview-section')?.classList.add('hidden');
}

function toggleBulkSerialSettings() {
    const enabled = document.getElementById('bulk-generate-serials').checked;
    document.getElementById('bulk-serial-settings').classList.toggle('hidden', !enabled);
    document.querySelectorAll('#bulk-serial-settings input').forEach(input => input.disabled = !enabled);
    invalidateBulkPreview();
}

function refreshBulkMaintenanceControls() {
    const rows = [...document.querySelectorAll('#bulk-maintenance-schedules .maintenance-schedule-card')];
    rows.forEach((row, index) => {
        row.querySelector('.maintenance-schedule-title').textContent = `Prüffrist ${index + 1}`;
    });
    const enabled = document.getElementById('bulk-inspection-required').checked;
    const remaining = Math.max(0, 3 - rows.length);
    document.getElementById('bulk-add-maintenance').disabled = !enabled || remaining === 0;
    document.getElementById('bulk-maintenance-limit').textContent = remaining === 0
        ? 'Maximal drei Prüffristen erreicht.'
        : `${remaining} weitere ${remaining === 1 ? 'Prüffrist' : 'Prüffristen'} möglich.`;
}

function addBulkMaintenanceSchedule(schedule = {}) {
    const container = document.getElementById('bulk-maintenance-schedules');
    if (container.children.length >= 3) return;
    const rowId = ++bulkMaintenanceCounter;
    const article = document.createElement('article');
    article.className = 'maintenance-schedule-card';
    article.innerHTML = `
        <div class="maintenance-schedule-card-heading">
            <strong class="maintenance-schedule-title">Prüffrist</strong>
            <button type="button" class="btn-secondary btn-small" onclick="removeBulkMaintenanceSchedule(this)">Entfernen</button>
        </div>
        <div class="maintenance-schedule-grid">
            <div class="form-field maintenance-description-field">
                <label for="bulk-maintenance-description-${rowId}">Bezeichnung <span class="required-mark">*</span></label>
                <input id="bulk-maintenance-description-${rowId}" class="maintenance-description" type="text" maxlength="120" required placeholder="z. B. jährliche Prüfung" value="${escapeHtml(schedule.description || '')}">
            </div>
            <div class="form-field">
                <label for="bulk-maintenance-interval-${rowId}">Intervall <span class="required-mark">*</span></label>
                <div class="input-with-suffix"><input id="bulk-maintenance-interval-${rowId}" class="maintenance-interval" type="number" min="1" max="36500" inputmode="numeric" required value="${schedule.interval_days || ''}"><span>Tage</span></div>
            </div>
            <div class="form-field">
                <label for="bulk-maintenance-next-${rowId}">Nächster Termin</label>
                <input id="bulk-maintenance-next-${rowId}" class="maintenance-next-date" type="date" value="${escapeHtml(schedule.next_maintenance_date || '')}">
                <small>Leer lassen: Anschaffungsdatum plus Intervall.</small>
            </div>
            <div class="form-field maintenance-notes-field">
                <label for="bulk-maintenance-notes-${rowId}">Hinweise</label>
                <textarea id="bulk-maintenance-notes-${rowId}" class="maintenance-notes" rows="2">${escapeHtml(schedule.notes || '')}</textarea>
            </div>
        </div>`;
    container.appendChild(article);
    refreshBulkMaintenanceControls();
    invalidateBulkPreview();
}

function removeBulkMaintenanceSchedule(button) {
    button.closest('.maintenance-schedule-card')?.remove();
    refreshBulkMaintenanceControls();
    invalidateBulkPreview();
}

function toggleBulkInspectionSettings() {
    const enabled = document.getElementById('bulk-inspection-required').checked;
    document.getElementById('bulk-inspection-settings').classList.toggle('hidden', !enabled);
    document.querySelectorAll('#bulk-inspection-settings input, #bulk-inspection-settings textarea, #bulk-inspection-settings button')
        .forEach(control => control.disabled = !enabled);
    refreshBulkMaintenanceControls();
    invalidateBulkPreview();
}

function openBulkCreateForm(options = {}) {
    document.getElementById('bulk-object-form').reset();
    document.getElementById('bulk-quantity').value = '30';
    document.getElementById('bulk-status').value = 'in_benutzung';
    document.getElementById('bulk-generate-serials').checked = true;
    document.getElementById('bulk-serial-start').value = '1';
    document.getElementById('bulk-serial-padding').value = '3';
    document.getElementById('bulk-inspection-required').checked = true;
    fillSelect('bulk-type', masterData.types, 'name');
    fillSelect('bulk-manufacturer', masterData.manufacturers, 'name');
    fillSelect('bulk-supplier', masterData.suppliers, 'name');
    const locations = (masterData.locationsFlat || []).map(location => ({
        id: location.id,
        name: getLocationPath(masterData.locationsFlat, location.id)
    }));
    fillSelect('bulk-location', locations, 'name');
    document.getElementById('bulk-maintenance-schedules').innerHTML = '';
    bulkMaintenanceCounter = 0;
    addBulkMaintenanceSchedule();
    toggleBulkSerialSettings();
    toggleBulkInspectionSettings();
    clearBulkMessage();
    invalidateBulkPreview();
    showView('bulk-create', {
        replaceHistory: options.replaceHistory === true,
        skipHistory: options.skipHistory === true
    });
    setTimeout(() => document.getElementById('bulk-designation').focus(), 0);
}

function collectBulkMaintenanceSchedules() {
    return [...document.querySelectorAll('#bulk-maintenance-schedules .maintenance-schedule-card')].map(row => ({
        description: row.querySelector('.maintenance-description').value.trim(),
        interval_days: Number(row.querySelector('.maintenance-interval').value),
        next_maintenance_date: row.querySelector('.maintenance-next-date').value || null,
        notes: row.querySelector('.maintenance-notes').value.trim() || null
    }));
}

function collectBulkObjectPayload() {
    const inspectionRequired = document.getElementById('bulk-inspection-required').checked;
    const payload = {
        quantity: Number(document.getElementById('bulk-quantity').value),
        designation: document.getElementById('bulk-designation').value.trim(),
        object_type_id: Number(document.getElementById('bulk-type').value),
        manufacturer_id: Number(document.getElementById('bulk-manufacturer').value) || null,
        supplier_id: Number(document.getElementById('bulk-supplier').value) || null,
        location_id: Number(document.getElementById('bulk-location').value) || null,
        acquisition_date: document.getElementById('bulk-acquisition').value || null,
        status: document.getElementById('bulk-status').value,
        info_text: document.getElementById('bulk-info').value.trim() || null,
        usage_hints: document.getElementById('bulk-hints').value.trim() || null,
        inspection_required: inspectionRequired,
        maintenance_schedules: inspectionRequired ? collectBulkMaintenanceSchedules() : [],
        generate_serial_numbers: document.getElementById('bulk-generate-serials').checked,
        serial_prefix: document.getElementById('bulk-serial-prefix').value,
        serial_start: Number(document.getElementById('bulk-serial-start').value || 0),
        serial_padding: Number(document.getElementById('bulk-serial-padding').value || 0),
        serial_suffix: document.getElementById('bulk-serial-suffix').value
    };
    if (!payload.quantity || payload.quantity < 1 || payload.quantity > 100) throw new Error('Bitte eine Anzahl zwischen 1 und 100 eingeben.');
    if (!payload.designation) throw new Error('Bitte eine Bezeichnung eingeben.');
    if (!payload.object_type_id) throw new Error('Bitte eine Kategorie auswählen.');
    if (payload.maintenance_schedules.some(schedule => !schedule.description || !schedule.interval_days)) {
        throw new Error('Bitte jede angelegte Prüffrist vollständig ausfüllen oder entfernen.');
    }
    return payload;
}

async function previewBulkObjects(event) {
    event.preventDefault();
    clearBulkMessage();
    try {
        const payload = collectBulkObjectPayload();
        const preview = await api('/api/objects/bulk/preview', {
            method: 'POST',
            body: JSON.stringify(payload)
        });
        bulkPreviewPayload = payload;
        document.getElementById('bulk-preview-summary').textContent = `${preview.count} Objekte werden mit den folgenden Angaben angelegt.`;
        const warnings = preview.warnings || [];
        document.getElementById('bulk-preview-warnings').innerHTML = warnings.map(warning =>
            `<div class="form-message ${warning.includes('bereits vergeben') ? 'error' : 'warning'}">${escapeHtml(warning)}</div>`
        ).join('');
        document.getElementById('bulk-preview-list').innerHTML = `
            <table><thead><tr><th>Nr.</th><th>Bezeichnung</th><th>Seriennummer</th></tr></thead>
            <tbody>${preview.items.map(item => `<tr><td>${item.position}</td><td>${escapeHtml(item.designation)}</td><td>${escapeHtml(item.serial_number || '—')}</td></tr>`).join('')}</tbody></table>`;
        document.getElementById('bulk-create-button').disabled = warnings.some(warning => warning.includes('bereits vergeben'));
        const previewSection = document.getElementById('bulk-preview-section');
        previewSection.classList.remove('hidden');
        previewSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
        showBulkMessage(error.message);
    }
}

async function createBulkObjects() {
    if (!bulkPreviewPayload) {
        showBulkMessage('Die Angaben wurden geändert. Bitte zuerst eine neue Voransicht erzeugen.');
        return;
    }
    const button = document.getElementById('bulk-create-button');
    button.disabled = true;
    button.textContent = 'Objekte werden angelegt …';
    try {
        const result = await api('/api/objects/bulk', {
            method: 'POST',
            body: JSON.stringify(bulkPreviewPayload)
        });
        const designation = bulkPreviewPayload.designation;
        let imageWarning = '';
        const imageInput = document.getElementById('bulk-title-image');
        if (imageInput.files.length) {
            const imageData = new FormData();
            imageData.append('file', imageInput.files[0]);
            imageData.append('object_ids', JSON.stringify(result.objects.map(item => item.id)));
            try {
                await uploadFile('/api/objects/bulk/title-image', imageData);
            } catch (imageError) {
                imageWarning = `\n\nDie Objekte wurden angelegt, das gemeinsame Bild konnte aber nicht übernommen werden: ${imageError.message}`;
            }
        }
        bulkPreviewPayload = null;
        alert(`${result.created_count} Objekte wurden erfolgreich angelegt.${imageWarning}`);
        showView('search', { replaceHistory: true });
        document.getElementById('search-input').value = designation;
        applyFilters();
    } catch (error) {
        showBulkMessage('Sammelanlage fehlgeschlagen: ' + error.message);
        document.getElementById('bulk-preview-section').classList.add('hidden');
    } finally {
        button.disabled = false;
        button.textContent = 'Objekte jetzt anlegen';
    }
}

async function showObjectsByLocation(locationId, locationName, options = {}) {
    try {
        const objects = await api('/api/locations/' + locationId + '/objects');
        document.getElementById('location-objects-title').textContent = 'Objekte: ' + locationName;
        const container = document.getElementById('location-objects-list');
        if (!objects.length) {
            container.innerHTML = '<p>Keine Objekte an diesem Standort.</p>';
        } else {
            container.innerHTML = objects.map(r => `
                <div class="card" onclick="openObject(${r.id})">
                    <img class="card-image" src="${r.title_image ? '/uploads/images/' + r.title_image : ''}" alt="" onerror="this.style.display='none'">
                    <div class="card-body">
                        <h4>${escapeHtml(r.designation)}</h4>
                        <div class="card-meta">
                            <span class="badge badge-${r.status}">${formatStatus(r.status)}</span>
                            <strong>${r.object_number}</strong>
                            ${r.object_type ? '· ' + r.object_type : ''}
                            ${r.location_name ? '· ' + escapeHtml(r.location_name) : ''}
                        </div>
                    </div>
                </div>
            `).join('');
        }
        showView('location-objects', {
            historyData: { locationId: Number(locationId), locationName },
            replaceHistory: options.replaceHistory === true,
            skipHistory: options.skipHistory === true
        });
    } catch (e) { alert('Fehler: ' + e.message); }
}

// === Delete Object with Security ===
let deleteObjectId = null;
let deleteRequiresCode = false;

function deleteObjectWithConfirm(objectId, hasInspections) {
    deleteObjectId = objectId;
    deleteRequiresCode = hasInspections;
    document.getElementById('delete-modal').style.display = 'block';
    document.getElementById('delete-code-input').value = '';
    
    if (hasInspections) {
        document.getElementById('delete-code-box').classList.remove('hidden');
        document.getElementById('delete-msg').innerHTML = '<strong style="color:#b71c1c;">Achtung!</strong> Dieses Objekt hat bereits durchgeführte Prüfungen. Zum Löschen ist ein Sicherheitscode erforderlich.';
    } else {
        document.getElementById('delete-code-box').classList.add('hidden');
        document.getElementById('delete-msg').textContent = 'Sind Sie sicher, dass Sie dieses Objekt löschen möchten?';
    }
}

function closeDeleteModal() {
    document.getElementById('delete-modal').style.display = 'none';
    deleteObjectId = null;
    deleteRequiresCode = false;
}

async function confirmDelete() {
    if (!deleteObjectId) return;
    
    if (deleteRequiresCode) {
        const code = document.getElementById('delete-code-input').value.trim();
        if (code !== '6699') {
            alert('Falscher Sicherheitscode! Löschen abgebrochen.');
            return;
        }
    }
    
    try {
        await api('/api/objects/' + deleteObjectId, { method: 'DELETE' });
        closeDeleteModal();
        alert('Objekt gelöscht!');
        showView('search', { replaceHistory: true });
        applyFilters();
    } catch (e) { alert('Fehler beim Löschen: ' + e.message); }
}

async function editObject(id, options = {}) {
    try {
        const obj = await api('/api/objects/' + id);
        await loadMasterData(); // Stellt sicher, dass alle Dropdowns aktuell sind

        document.getElementById('edit-object-id').value = obj.id;
        document.getElementById('obj-designation').value = obj.designation;
        document.getElementById('obj-type').value = obj.object_type ? obj.object_type.id : '';
        document.getElementById('obj-serial').value = obj.serial_number || '';
        clearInlineFeedback('serial-scan-feedback');
        document.getElementById('obj-manufacturer').value = obj.manufacturer ? obj.manufacturer.id : '';
        document.getElementById('obj-supplier').value = obj.supplier ? obj.supplier.id : '';
        setObjectLocation(obj.location ? obj.location.id : null);
        document.getElementById('obj-status').value = obj.status;
        document.getElementById('obj-acquisition').value = obj.acquisition_date || '';
        document.getElementById('obj-info').value = obj.info_text || '';
        document.getElementById('obj-hints').value = obj.usage_hints || '';
        document.getElementById('obj-inspection-required').checked = obj.inspection_required !== false;
        document.getElementById('obj-standard-inspection-enabled').checked = !!obj.standard_inspection_enabled;
        await loadObjectInspectionTemplates(obj.standard_inspection_template_id || null);
        document.getElementById('obj-standard-inspection-template').value = obj.standard_inspection_template_id || '';
        toggleStandardInspectionSettings();
        document.getElementById('new-manufacturer').value = '';
        document.getElementById('new-supplier').value = '';
        document.getElementById('new-location').value = '';
        document.getElementById('new-location-type').value = '';
        document.getElementById('add-manufacturer-box').classList.add('hidden');
        document.getElementById('add-supplier-box').classList.add('hidden');
        document.getElementById('add-location-box').classList.add('hidden');
        // Trigger type change to show/hide vehicle-location-box
        const typeSel = document.getElementById('obj-type');
        if (typeSel && typeSel.onchange) typeSel.onchange();

        resetMaintenanceSchedules(obj.maintenances && obj.maintenances.length ? obj.maintenances : [{}]);
        toggleInspectionRequiredSettings();

        document.getElementById('form-title').textContent = 'Objekt bearbeiten';
        showView('edit-object', {
            historyData: { objectId: Number(id) },
            replaceHistory: options.replaceHistory === true,
            skipHistory: options.skipHistory === true
        });
    } catch (e) { alert('Fehler: ' + e.message); }
}

// === Admin ===
let adminUsers = [];
let activeAdminTab = 'users';

function refreshAdminTab(tab = activeAdminTab) {
    if (tab === 'users') loadUsers();
    if (tab === 'masterdata') loadMasterDataLists();
    if (tab === 'locations') loadLocationsAdmin();
    if (tab === 'inspections') loadInspectionTemplatesList();
    if (tab === 'archive') initArchiveYears();
    if (tab === 'api') loadApiClients();
}

function showAdminTab(tab, button = null) {
    activeAdminTab = tab;
    document.querySelectorAll('.admin-tab').forEach(t => t.classList.remove('active'));
    if (button) button.classList.add('active');
    document.getElementById('admin-users').classList.toggle('hidden', tab !== 'users');
    document.getElementById('admin-masterdata').classList.toggle('hidden', tab !== 'masterdata');
    document.getElementById('admin-locations').classList.toggle('hidden', tab !== 'locations');
    document.getElementById('admin-inspections').classList.toggle('hidden', tab !== 'inspections');
    document.getElementById('admin-qrlogin').classList.toggle('hidden', tab !== 'qrlogin');
    document.getElementById('admin-importexport').classList.toggle('hidden', tab !== 'importexport');
    document.getElementById('admin-log').classList.toggle('hidden', tab !== 'log');
    document.getElementById('admin-archive').classList.toggle('hidden', tab !== 'archive');
    document.getElementById('admin-api').classList.toggle('hidden', tab !== 'api');
    refreshAdminTab(tab);
}

async function loadApiClients() {
    const container = document.getElementById('api-clients-list');
    container.innerHTML = '<p>API-Schlüssel werden geladen …</p>';
    try {
        const clients = await api('/api/admin/api-clients');
        if (!clients.length) {
            container.innerHTML = '<p>Noch keine API-Schlüssel vorhanden.</p>';
            return;
        }
        container.innerHTML = `
            <table><thead><tr><th>Anwendung</th><th>Schlüssel</th><th>Rechte</th><th>Letzte Nutzung</th><th>Status</th><th>Aktion</th></tr></thead>
            <tbody>${clients.map(client => `
                <tr>
                    <td>${escapeHtml(client.name)}</td>
                    <td><code>${escapeHtml(client.key_prefix)}…</code></td>
                    <td>${client.scopes.map(scope => scope === 'objects:write' ? 'Anlegen' : 'Lesen').join(', ')}</td>
                    <td>${client.last_used_at ? new Date(client.last_used_at).toLocaleString('de-DE') : 'Noch nie'}</td>
                    <td>${client.is_active ? '<span class="active-state yes">Aktiv</span>' : '<span class="active-state no">Widerrufen</span>'}</td>
                    <td>${client.is_active ? `<button type="button" class="btn-primary btn-small btn-delete" onclick="revokeApiClient(${client.id})">Widerrufen</button>` : '—'}</td>
                </tr>`).join('')}</tbody></table>`;
    } catch (error) {
        container.innerHTML = `<div class="form-message error">${escapeHtml(error.message)}</div>`;
    }
}

async function createApiClient(event) {
    event.preventDefault();
    const scopes = [];
    if (document.getElementById('api-scope-read').checked) scopes.push('objects:read');
    if (document.getElementById('api-scope-write').checked) scopes.push('objects:write');
    if (!scopes.length) return alert('Bitte mindestens eine Berechtigung auswählen.');
    try {
        const created = await api('/api/admin/api-clients', {
            method: 'POST',
            body: JSON.stringify({
                name: document.getElementById('api-client-name').value.trim(),
                scopes
            })
        });
        document.getElementById('api-key-value').textContent = created.api_key;
        document.getElementById('api-key-reveal').classList.remove('hidden');
        document.getElementById('api-client-form').reset();
        document.getElementById('api-scope-read').checked = true;
        await loadApiClients();
    } catch (error) {
        alert('API-Schlüssel konnte nicht erstellt werden: ' + error.message);
    }
}

async function copyApiKey() {
    const value = document.getElementById('api-key-value').textContent;
    try {
        await navigator.clipboard.writeText(value);
        alert('API-Schlüssel wurde kopiert.');
    } catch (error) {
        alert('Automatisches Kopieren ist nicht möglich. Bitte den Schlüssel markieren und manuell kopieren.');
    }
}

async function revokeApiClient(clientId) {
    if (!confirm('Diesen API-Schlüssel wirklich widerrufen? Externe Programme können ihn danach nicht mehr verwenden.')) return;
    try {
        await api('/api/admin/api-clients/' + clientId, { method: 'DELETE' });
        await loadApiClients();
    } catch (error) {
        alert('API-Schlüssel konnte nicht widerrufen werden: ' + error.message);
    }
}

async function loadUsers() {
    try {
        adminUsers = await api('/api/users');
        document.getElementById('users-list').innerHTML = `
            <table><thead><tr><th>Name</th><th>Benutzer</th><th>Funktion</th><th>Aktiv</th><th>Aktionen</th></tr></thead>
            <tbody>${adminUsers.map(u => `
                <tr>
                    <td>${escapeHtml(u.full_name)}</td>
                    <td>${escapeHtml(u.username)}</td>
                    <td><span class="role-badge role-${u.role}">${formatUserRole(u.role)}</span></td>
                    <td>${u.is_active ? '<span class="active-state yes">Aktiv</span>' : '<span class="active-state no">Deaktiviert</span>'}</td>
                    <td>
                        <button class="btn-primary btn-small" onclick="showUserForm(${u.id})">Bearbeiten</button>
                        <button class="btn-primary btn-small btn-delete" onclick="deleteUser(${u.id})">Löschen</button>
                    </td>
                </tr>
            `).join('')}</tbody></table>
        `;
    } catch (e) { console.error(e); }
}

async function deleteUser(id) {
    if (!confirm('Benutzer wirklich löschen?')) return;
    await api('/api/users/' + id, { method: 'DELETE' });
    loadUsers();
}

function formatUserRole(role) {
    const labels = {
        standard: 'Standardnutzer',
        erweitert: 'Erweiterter Nutzer',
        verwaltung: 'Verwaltung',
        admin: 'Administrator'
    };
    return labels[role] || role;
}

function showUserForm(userId = null) {
    const form = document.getElementById('user-form');
    const user = userId ? adminUsers.find(item => item.id === userId) : null;
    form.reset();
    document.getElementById('user-edit-id').value = user ? user.id : '';
    document.getElementById('user-modal-title').textContent = user ? 'Benutzer bearbeiten' : 'Benutzer anlegen';
    document.getElementById('user-save-button').textContent = user ? 'Änderungen speichern' : 'Benutzer speichern';
    document.getElementById('user-username').value = user ? user.username : '';
    document.getElementById('user-username').disabled = Boolean(user);
    document.getElementById('user-full-name').value = user ? user.full_name : '';
    document.getElementById('user-email').value = user && user.email ? user.email : '';
    document.getElementById('user-role').value = user ? user.role : 'standard';
    document.getElementById('user-active').checked = user ? user.is_active : true;
    document.getElementById('user-password').required = !user;
    document.getElementById('user-password-label').textContent = user ? 'Neues Passwort' : 'Passwort *';
    document.getElementById('user-password-help').textContent = user
        ? 'Leer lassen, wenn das bisherige Passwort erhalten bleiben soll.'
        : 'Das Passwort muss mindestens 6 Zeichen lang sein.';
    document.getElementById('user-form-message').className = 'form-message hidden';
    document.getElementById('user-modal').style.display = 'block';
    setTimeout(() => document.getElementById(user ? 'user-full-name' : 'user-username').focus(), 0);
}

function closeUserForm() {
    document.getElementById('user-modal').style.display = 'none';
    document.getElementById('user-form').reset();
}

async function saveUser(event) {
    event.preventDefault();
    const userId = document.getElementById('user-edit-id').value;
    const password = document.getElementById('user-password').value;
    const data = {
        full_name: document.getElementById('user-full-name').value.trim(),
        email: document.getElementById('user-email').value.trim() || null,
        role: document.getElementById('user-role').value,
        is_active: document.getElementById('user-active').checked
    };
    if (!userId) data.username = document.getElementById('user-username').value.trim();
    if (password) data.password = password;
    const message = document.getElementById('user-form-message');
    const submitButton = event.submitter;
    if (submitButton) submitButton.disabled = true;
    try {
        await api(userId ? '/api/users/' + userId : '/api/users', {
            method: userId ? 'PUT' : 'POST',
            body: JSON.stringify(data)
        });
        closeUserForm();
        await loadUsers();
    } catch (error) {
        message.textContent = error.message;
        message.className = 'form-message error';
    } finally {
        if (submitButton) submitButton.disabled = false;
    }
}

async function loadMasterDataLists() {
    // Hersteller
    const manus = await api('/api/manufacturers');
    let manuHtml = `
        <div style="margin-bottom:1rem; padding:1rem; background:#f5f5f5; border-radius:8px;">
            <h4>Hersteller anlegen</h4>
            <div style="display:flex; gap:0.5rem;">
                <input type="text" id="new-manufacturer-admin" placeholder="Neuer Hersteller..." style="flex:1;">
                <button class="btn-primary btn-small" onclick="addManufacturerAdmin()">+ Hinzufügen</button>
            </div>
        </div>
        <div style="margin-top:0.5rem;">
            ${manus.map(m => `<span class="badge badge-reserve" style="margin:0.2rem;display:inline-block">${escapeHtml(m.name)}</span>`).join('') || '<p>Keine Hersteller vorhanden</p>'}
        </div>
    `;
    document.getElementById('manufacturers-list').innerHTML = manuHtml;

    // Lieferanten
    const suppliers = await api('/api/suppliers');
    const supplierHtml = `
        <div style="margin-bottom:1rem; padding:1rem; background:#f5f5f5; border-radius:8px;">
            <h4>Lieferant anlegen</h4>
            <div style="display:flex; gap:0.5rem;">
                <input type="text" id="new-supplier-admin" placeholder="Neuer Lieferant..." style="flex:1;">
                <button class="btn-primary btn-small" onclick="addSupplierAdmin()">+ Hinzufügen</button>
            </div>
        </div>
        <div style="margin-top:0.5rem;">
            ${suppliers.map(supplier => `<span class="badge badge-reserve" style="margin:0.2rem;display:inline-block">${escapeHtml(supplier.name)}</span>`).join('') || '<p>Keine Lieferanten vorhanden</p>'}
        </div>
    `;
    document.getElementById('suppliers-list').innerHTML = supplierHtml;
}

async function addManufacturerAdmin() {
    const name = document.getElementById('new-manufacturer-admin').value.trim();
    if (!name) return alert('Bitte Herstellernamen eingeben');
    try {
        await api('/api/manufacturers', { method: 'POST', body: JSON.stringify({ name }) });
        document.getElementById('new-manufacturer-admin').value = '';
        loadMasterDataLists();
        loadMasterData();
    } catch (e) { alert('Fehler: ' + e.message); }
}

async function addSupplierAdmin() {
    const name = document.getElementById('new-supplier-admin').value.trim();
    if (!name) return alert('Bitte Lieferantennamen eingeben');
    try {
        await api('/api/suppliers', { method: 'POST', body: JSON.stringify({ name }) });
        document.getElementById('new-supplier-admin').value = '';
        loadMasterDataLists();
        loadMasterData();
    } catch (error) { alert('Fehler: ' + error.message); }
}

async function loadLocationsAdmin() {
    const parentInput = document.getElementById('new-location-parent-admin');
    const selectedParentId = parentInput?.value || null;
    const [treeLocations, flatLocations, allObjects] = await Promise.all([
        api('/api/locations'),
        api('/api/locations/all'),
        api('/api/objects')
    ]);

    masterData.locationsFlat = flatLocations;
    masterData.locations = buildLocationTree(flatLocations);
    const locationsList = document.getElementById('locations-list');
    locationsList.innerHTML = treeLocations.length
        ? renderLocationTreeWithObjects(treeLocations, allObjects)
        : '<div class="empty-state">Noch keine Standorte angelegt.</div>';
    renderAdminLocationParentSelector(selectedParentId);
}

function setAdminLocationParent(locationId) {
    const parentInput = document.getElementById('new-location-parent-admin');
    if (!parentInput) return;
    parentInput.value = locationId ? String(locationId) : '';
    renderAdminLocationParentSelector(locationId || null);
}

function renderAdminLocationParentSelector(selectedLocationId = null) {
    const levelsContainer = document.getElementById('admin-location-parent-levels');
    const summary = document.getElementById('admin-location-parent-summary');
    const parentInput = document.getElementById('new-location-parent-admin');
    if (!levelsContainer || !summary || !parentInput) return;

    const allLocations = masterData.locationsFlat || [];
    const selectedId = selectedLocationId ? Number(selectedLocationId) : null;
    parentInput.value = selectedId ? String(selectedId) : '';
    const chain = getLocationChain(selectedId);
    levelsContainer.innerHTML = '';

    let parentId = null;
    let level = 0;
    while (true) {
        const choices = allLocations
            .filter(location => Number(location.parent_id || 0) === Number(parentId || 0))
            .sort((a, b) => a.name.localeCompare(b.name, 'de', { sensitivity: 'base' }));
        if (!choices.length) break;

        const selectedAtLevel = chain[level] && Number(chain[level].parent_id || 0) === Number(parentId || 0)
            ? Number(chain[level].id)
            : null;
        const parentLocation = parentId
            ? allLocations.find(location => Number(location.id) === Number(parentId))
            : null;
        const wrapper = document.createElement('div');
        wrapper.className = 'location-cascade-level';

        const label = document.createElement('label');
        label.htmlFor = `admin-location-parent-level-${level}`;
        label.textContent = level === 0
            ? '1. Hauptstandort'
            : `${level + 1}. Auswahl in „${parentLocation ? parentLocation.name : 'Unterbereich'}“`;

        const select = document.createElement('select');
        select.id = `admin-location-parent-level-${level}`;
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = level === 0
            ? '-- Auf der Hauptebene anlegen --'
            : `-- Direkt unter „${parentLocation ? parentLocation.name : 'diesem Bereich'}“ anlegen --`;
        select.appendChild(placeholder);

        choices.forEach(location => {
            const option = document.createElement('option');
            option.value = String(location.id);
            option.textContent = location.name;
            option.selected = Number(location.id) === selectedAtLevel;
            select.appendChild(option);
        });
        select.addEventListener('change', () => {
            const nextId = select.value ? Number(select.value) : parentId;
            setAdminLocationParent(nextId || null);
        });
        wrapper.append(label, select);
        levelsContainer.appendChild(wrapper);

        if (!selectedAtLevel) break;
        parentId = selectedAtLevel;
        level += 1;
    }

    summary.innerHTML = '';
    if (!selectedId) {
        summary.textContent = 'Der neue Standort wird auf der Hauptebene angelegt.';
        summary.classList.remove('has-selection');
        return;
    }

    const summaryText = document.createElement('span');
    summaryText.innerHTML = `<strong>Wird angelegt unter:</strong> ${escapeHtml(getLocationPath(allLocations, selectedId)).replaceAll(' &gt; ', ' › ')}`;
    const clearButton = document.createElement('button');
    clearButton.type = 'button';
    clearButton.className = 'location-clear-button';
    clearButton.textContent = 'Hauptebene verwenden';
    clearButton.addEventListener('click', () => setAdminLocationParent(null));
    summary.append(summaryText, clearButton);
    summary.classList.add('has-selection');
}

async function addLocationAdmin() {
    const name = document.getElementById('new-location-admin').value.trim();
    const type = document.getElementById('new-location-type-admin').value.trim() || 'Standort';
    const parentId = document.getElementById('new-location-parent-admin').value || null;
    clearInlineFeedback('admin-location-feedback');
    if (!name) {
        showInlineFeedback('admin-location-feedback', 'Bitte einen Namen für den neuen Standort eingeben.');
        document.getElementById('new-location-admin').focus();
        return;
    }
    try {
        const location = await api('/api/locations', { method: 'POST', body: JSON.stringify({ name, location_type: type, parent_id: parentId ? parseInt(parentId) : null }) });
        document.getElementById('new-location-admin').value = '';
        document.getElementById('new-location-type-admin').value = '';
        setAdminLocationParent(null);
        await loadMasterData();
        await loadLocationsAdmin();
        showInlineFeedback('admin-location-feedback', `Standort „${location.name}“ wurde angelegt.`, 'info');
    } catch (error) {
        showInlineFeedback('admin-location-feedback', error.message);
    }
}

function renderLocationTreeWithObjects(locs, allObjects, level = 0) {
    if (!locs || !locs.length) return '';
    const indent = level * 20;
    const colors = ['#e3f2fd', '#f5f5f5', '#fafafa', '#fff8e1', '#f3e5f5'];
    const borderColors = ['#1976d2', '#388e3c', '#f57c00', '#7b1fa2', '#5d4037'];
    const isAdmin = currentUser && currentUser.role === 'admin';
    
    let html = '<ul style="list-style:none; padding-left:0; margin:0;">';
    locs.forEach(l => {
        // Filtere Objekte: Keine Fahrzeuge anzeigen (die haben ihren eigenen verknüpften Standort)
        const locObjects = allObjects.filter(o => o.location_id === l.id && o.object_type !== 'Fahrzeug');
        const objCount = locObjects.length;
        const hasChildren = l.children && l.children.length > 0;
        const isLinkedVehicle = l.linked_object_id || l.location_type === 'Fahrzeug';
        const countInventoryInTree = location => {
            const directCount = allObjects.filter(object => Number(object.location_id) === Number(location.id)).length;
            return directCount + (location.children || []).reduce((sum, child) => sum + countInventoryInTree(child), 0);
        };
        const subtreeObjectCount = countInventoryInTree(l);
        
        html += `<li style="margin:0.3rem 0; padding-left:${indent}px;">`;
        html += `<div style="padding:0.5rem; background:${colors[level % colors.length]}; border-radius:6px; border-left:3px solid ${borderColors[level % borderColors.length]};">`;
        
        // Header mit Icon, Name und Löschen-Button
        html += `<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.3rem;">`;
        html += `<div>`;
        if (isLinkedVehicle && l.linked_object_id) {
            html += `🚒 <strong><a href="#" onclick="event.preventDefault(); openObject(${l.linked_object_id});" style="color:#1565c0; text-decoration:none;">${escapeHtml(l.name)}</a></strong>`;
        } else {
            html += `${hasChildren ? '📁' : '📂'} <strong>${escapeHtml(l.name)}</strong>`;
        }
        html += ` <span style="color:#666; font-size:0.85rem;">(${escapeHtml(l.location_type)})</span></div>`;
        html += `<div style="display:flex; gap:0.3rem; align-items:center;">`;
        const shownObjectCount = isLinkedVehicle ? subtreeObjectCount : objCount;
        if (shownObjectCount > 0) {
            html += `<span class="badge badge-reserve" style="font-size:0.75rem;">${shownObjectCount} Objekt${shownObjectCount > 1 ? 'e' : ''}</span>`;
        }
        // Fahrzeug-Standorte dürfen inklusive Unterstruktur ausschließlich dann
        // gelöscht werden, wenn im gesamten Teilbaum kein Inventar liegt.
        if (isAdmin && isLinkedVehicle && subtreeObjectCount === 0) {
            html += `<button class="btn-primary btn-small btn-delete" onclick="deleteLocation(${l.id}, '${escapeHtml(l.name)}', true)" title="Leeren Fahrzeugstandort inklusive Unterstandorten löschen">🗑️</button>`;
        } else if (isAdmin && isLinkedVehicle && subtreeObjectCount > 0) {
            html += `<span class="location-delete-locked" title="Löschen gesperrt: Im Fahrzeug oder seinen Unterstandorten befindet sich Inventar.">🔒</span>`;
        } else if (isAdmin && !hasChildren && objCount === 0) {
            html += `<button class="btn-primary btn-small btn-delete" onclick="deleteLocation(${l.id}, '${escapeHtml(l.name)}', false)" title="Standort löschen">🗑️</button>`;
        }
        html += `</div></div>`;
        
        // Objekte an diesem Standort (nur Nicht-Fahrzeuge)
        if (locObjects.length > 0) {
            html += '<div style="margin-top:0.4rem; padding-left:1rem; border-left:2px dashed #ccc;">';
            locObjects.forEach(o => {
                html += `<div style="font-size:0.9rem; padding:0.15rem 0;">📦 <a href="#" onclick="event.preventDefault(); openObject(${o.id});" style="color:#1565c0; text-decoration:none;">${escapeHtml(o.designation)}</a> <small style="color:#999;">${o.object_number}</small></div>`;
            });
            html += '</div>';
        }
        
        html += '</div>';
        
        // Rekursiv Kinder rendern
        if (hasChildren) {
            html += renderLocationTreeWithObjects(l.children, allObjects, level + 1);
        }
        
        html += '</li>';
    });
    html += '</ul>';
    return html;
}

async function deleteLocation(locationId, locationName, deleteVehicleTree = false) {
    const question = deleteVehicleTree
        ? `Fahrzeugstandort "${locationName}" inklusive aller Unterstandorte wirklich löschen?\n\nDas Inventar-Fahrzeug selbst bleibt erhalten. Das Löschen wird vom Server blockiert, sobald sich irgendwo in diesem Standortbaum Inventar befindet.`
        : `Standort "${locationName}" wirklich löschen?`;
    if (!confirm(question)) return;
    try {
        const result = await api('/api/locations/' + locationId, { method: 'DELETE' });
        alert(deleteVehicleTree
            ? `Fahrzeugstandort und ${Math.max(0, (result.deleted_locations || 1) - 1)} Unterstandort(e) gelöscht. Das Inventar-Fahrzeug bleibt erhalten.`
            : 'Standort gelöscht!');
        await loadMasterData();
        await loadLocationsAdmin();
    } catch (e) { alert('Fehler: ' + e.message); }
}

function renderLocationTree(locs, level = 0) {
    if (!locs || !locs.length) return '';
    let html = '<ul style="margin-left:' + (level * 20) + 'px">';
    locs.forEach(l => {
        html += `<li>${escapeHtml(l.name)} (${l.location_type})${renderLocationTree(l.children, level + 1)}</li>`;
    });
    html += '</ul>';
    return html;
}

// === Inspection Template Admin ===
let templateFieldCount = 0;
let templateEditId = null;
let editingInspectionId = null;

async function loadInspectionTemplatesList() {
    try {
        // Admin sieht ALLE Prüfkarten, daher mit Admin-Rechten laden
        const templates = await api('/api/inspection-templates');
        document.getElementById('inspection-templates-list').innerHTML = `
            <table><thead><tr><th>Name</th><th>Beschreibung</th><th>Standardintervall</th><th>Kategorie</th><th>Felder</th><th>Aktionen</th></tr></thead>
            <tbody>${templates.map(t => {
                let fields = [];
                try { fields = JSON.parse(t.fields); } catch(e) {}
                return `
                <tr>
                    <td>${escapeHtml(t.name)}</td>
                    <td>${escapeHtml(t.description || '-')}</td>
                    <td>${t.default_interval_days ? `${t.default_interval_days} Tage` : '-'}</td>
                    <td>${t.object_type_id ? (masterData.types.find(ty => ty.id == t.object_type_id)?.name || '-') : 'Alle'}</td>
                    <td>${fields.length + 1} Felder <small>(inkl. Prüfer)</small></td>
                    <td>
                        <button class="btn-secondary btn-small" onclick="openInspectionTemplatePdf(${t.id})">🖨️ PDF</button>
                        <button class="btn-primary btn-small" onclick="editInspectionTemplate(${t.id})">Bearbeiten</button>
                        <button class="btn-primary btn-small btn-delete" onclick="deleteInspectionTemplate(${t.id})">Löschen</button>
                    </td>
                </tr>
                `;
            }).join('')}</tbody></table>
        `;
    } catch (e) { console.error(e); }
}

async function openInspectionTemplatePdf(templateId) {
    const previewWindow = window.open('', '_blank');
    if (previewWindow) {
        previewWindow.document.write('<!doctype html><html><head><title>PDF wird erstellt</title></head><body style="font-family:sans-serif;padding:2rem">Prüfkartenvorlage wird erstellt …</body></html>');
    }
    try {
        const response = await fetch(`/api/inspection-templates/${templateId}/pdf`, {
            headers: token ? { 'Authorization': `Bearer ${token}` } : {}
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || `PDF konnte nicht erstellt werden (${response.status})`);
        }
        const blob = await response.blob();
        const file = new File([blob], `Prüfkarte_${templateId}.pdf`, { type: 'application/pdf' });
        const url = URL.createObjectURL(file);
        if (previewWindow) {
            previewWindow.location.href = url;
        } else {
            const link = document.createElement('a');
            link.href = url;
            link.download = file.name;
            link.click();
        }
        setTimeout(() => URL.revokeObjectURL(url), 120000);
    } catch (error) {
        if (previewWindow) previewWindow.close();
        alert('Fehler: ' + error.message);
    }
}

function showInspectionTemplateForm() {
    templateEditId = null;
    document.getElementById('inspection-template-form-box').classList.remove('hidden');
    fillSelect('tmpl-type', masterData.types, 'name');
    document.getElementById('tmpl-fields-list').innerHTML = '';
    document.getElementById('tmpl-name').value = '';
    document.getElementById('tmpl-desc').value = '';
    document.getElementById('tmpl-default-interval').value = '';
    templateFieldCount = 0;
    addTemplateField();
}

function hideInspectionTemplateForm() {
    document.getElementById('inspection-template-form-box').classList.add('hidden');
    document.getElementById('inspection-template-form').reset();
    templateEditId = null;
}

async function editInspectionTemplate(id) {
    try {
        const t = await api('/api/inspection-templates/' + id);
        templateEditId = id;
        document.getElementById('inspection-template-form-box').classList.remove('hidden');
        fillSelect('tmpl-type', masterData.types, 'name');
        document.getElementById('tmpl-name').value = t.name;
        document.getElementById('tmpl-desc').value = t.description || '';
        document.getElementById('tmpl-type').value = t.object_type_id || '';
        document.getElementById('tmpl-default-interval').value = t.default_interval_days || '';

        // Felder laden
        document.getElementById('tmpl-fields-list').innerHTML = '';
        templateFieldCount = 0;
        let fields = [];
        try { fields = JSON.parse(t.fields); } catch(e) {}
        fields.forEach(f => {
            const idx = templateFieldCount++;
            const container = document.getElementById('tmpl-fields-list');
            const div = document.createElement('div');
            div.className = 'inspection-field';
            div.style.cssText = 'margin:0.5rem 0; padding:0.8rem; background:white; border-radius:6px;';
            div.innerHTML = `
                <div style="display:flex; gap:0.5rem; flex-wrap:wrap;">
                    <input type="text" id="tmpl-f-${idx}-label" placeholder="Feldname *" required style="flex:2; min-width:200px;" value="${escapeHtml(f.label)}">
                    <select id="tmpl-f-${idx}-type" required style="flex:1; min-width:120px;">
                        <option value="checkbox" ${f.type === 'checkbox' ? 'selected' : ''}>Checkbox (Ja/Nein)</option>
                        <option value="text" ${f.type === 'text' ? 'selected' : ''}>Text</option>
                        <option value="number" ${f.type === 'number' ? 'selected' : ''}>Zahl</option>
                        <option value="textarea" ${f.type === 'textarea' ? 'selected' : ''}>Mehrzeilig</option>
                        <option value="select" ${f.type === 'select' ? 'selected' : ''}>Auswahl</option>
                    </select>
                    <label style="display:flex; align-items:center; gap:0.3rem; font-weight:normal;">
                        <input type="checkbox" id="tmpl-f-${idx}-req" ${f.required ? 'checked' : ''}> Pflichtfeld
                    </label>
                    <button type="button" class="btn-primary btn-small btn-delete" onclick="this.parentElement.parentElement.remove()">🗑️</button>
                </div>
                <input type="text" id="tmpl-f-${idx}-opts" placeholder="Optionen mit Komma trennen (nur für Auswahl)" style="margin-top:0.4rem; width:100%; ${f.type === 'select' ? '' : 'display:none;'}">
            `;
            container.appendChild(div);

            if (f.options && f.options.length) {
                div.querySelector(`#tmpl-f-${idx}-opts`).value = f.options.join(', ');
            }

            const typeSel = div.querySelector(`#tmpl-f-${idx}-type`);
            const optsInput = div.querySelector(`#tmpl-f-${idx}-opts`);
            typeSel.onchange = () => {
                optsInput.style.display = typeSel.value === 'select' ? 'block' : 'none';
            };
        });
    } catch (e) { alert('Fehler: ' + e.message); }
}

function addTemplateField() {
    const container = document.getElementById('tmpl-fields-list');
    const idx = templateFieldCount++;
    const div = document.createElement('div');
    div.className = 'inspection-field';
    div.style.cssText = 'margin:0.5rem 0; padding:0.8rem; background:white; border-radius:6px;';
    div.innerHTML = `
        <div style="display:flex; gap:0.5rem; flex-wrap:wrap;">
            <input type="text" id="tmpl-f-${idx}-label" placeholder="Feldname *" required style="flex:2; min-width:200px;">
            <select id="tmpl-f-${idx}-type" required style="flex:1; min-width:120px;">
                <option value="checkbox">Checkbox (Ja/Nein)</option>
                <option value="text">Text</option>
                <option value="number">Zahl</option>
                <option value="textarea">Mehrzeilig</option>
                <option value="select">Auswahl</option>
            </select>
            <label style="display:flex; align-items:center; gap:0.3rem; font-weight:normal;">
                <input type="checkbox" id="tmpl-f-${idx}-req"> Pflichtfeld
            </label>
            <button type="button" class="btn-primary btn-small btn-delete" onclick="this.parentElement.parentElement.remove()">🗑️</button>
        </div>
        <input type="text" id="tmpl-f-${idx}-opts" placeholder="Optionen mit Komma trennen (nur für Auswahl)" style="margin-top:0.4rem; width:100%; display:none;">
    `;
    container.appendChild(div);
    
    // Show/hide options field based on type
    const typeSel = div.querySelector(`#tmpl-f-${idx}-type`);
    const optsInput = div.querySelector(`#tmpl-f-${idx}-opts`);
    typeSel.onchange = () => {
        optsInput.style.display = typeSel.value === 'select' ? 'block' : 'none';
    };
}

async function saveInspectionTemplate(e) {
    e.preventDefault();
    const fields = [];
    for (let i = 0; i < templateFieldCount; i++) {
        const label = document.getElementById(`tmpl-f-${i}-label`);
        const type = document.getElementById(`tmpl-f-${i}-type`);
        const req = document.getElementById(`tmpl-f-${i}-req`);
        const opts = document.getElementById(`tmpl-f-${i}-opts`);
        if (!label || !label.value.trim()) continue;
        
        const field = {
            label: label.value.trim(),
            type: type.value,
            required: req ? req.checked : false
        };
        if (type.value === 'select' && opts && opts.value) {
            field.options = opts.value.split(',').map(o => o.trim()).filter(o => o);
        }
        fields.push(field);
    }
    
    if (fields.length === 0) return alert('Bitte mindestens ein Feld hinzufügen');
    
    const data = {
        name: document.getElementById('tmpl-name').value,
        description: document.getElementById('tmpl-desc').value || null,
        fields: fields,
        object_type_id: document.getElementById('tmpl-type').value ? parseInt(document.getElementById('tmpl-type').value) : null,
        default_interval_days: parseInt(document.getElementById('tmpl-default-interval').value) || null,
        allow_standard_users: false
    };
    
    try {
        if (templateEditId) {
            await api('/api/inspection-templates/' + templateEditId, { method: 'PUT', body: JSON.stringify(data) });
            alert('Prüfkarte aktualisiert!');
        } else {
            await api('/api/inspection-templates', { method: 'POST', body: JSON.stringify(data) });
            alert('Prüfkarte gespeichert!');
        }
        hideInspectionTemplateForm();
        loadInspectionTemplatesList();
    } catch (e) { alert('Fehler: ' + e.message); }
}

async function deleteInspectionTemplate(id) {
    if (!confirm('Prüfkarte wirklich löschen?')) return;
    await api('/api/inspection-templates/' + id, { method: 'DELETE' });
    loadInspectionTemplatesList();
}

// === Inspection Functions ===
let inspectionTemplates = [];
let inspectionObjectMaintenances = [];
let inspectionPendingImages = [];
let inspectionExistingImages = [];
let activeInspectionMarkerId = null;
let inspectionMarkerImage = null;
let inspectionMarkerArrows = [];
let inspectionMarkerStart = null;
let inspectionMarkerDraftEnd = null;
let inspectionMarkerDrawing = false;
let inspectionMarkerColor = '#e00000';
let imageMarkerContext = 'inspection';

function inspectionDateAfterDays(days) {
    const nextDate = new Date();
    nextDate.setHours(12, 0, 0, 0);
    nextDate.setDate(nextDate.getDate() + Number(days));
    return formatDateInput(nextDate);
}

function inspectionIntervalLabel(days) {
    return Number(days) === 1 ? '1 Tag' : `${days} Tage`;
}

function populateInspectionMaintenanceSelect(selectedId = null, locked = false) {
    const field = document.getElementById('inspection-maintenance-field');
    const select = document.getElementById('inspection-maintenance');
    const isStandard = currentUser && currentUser.role === 'standard';
    field.classList.toggle('hidden', !!isStandard);
    select.innerHTML = '<option value="">Keine Prüffrist zurücksetzen</option>';
    if (!isStandard) {
        inspectionObjectMaintenances.forEach(maintenance => {
            const option = document.createElement('option');
            option.value = maintenance.id;
            option.textContent = `${maintenance.description || 'Allgemeine Prüfung / Wartung'} · alle ${inspectionIntervalLabel(maintenance.interval_days)}`;
            select.appendChild(option);
        });
    }
    const hasSelectedMaintenance = selectedId && inspectionObjectMaintenances.some(item => item.id == selectedId);
    select.value = hasSelectedMaintenance ? String(selectedId) : '';
    select.disabled = !!isStandard || locked;
    updateInspectionDueSelection(locked);
}

function updateInspectionDueSelection(preserveExistingDate = false) {
    const select = document.getElementById('inspection-maintenance');
    const field = document.getElementById('inspection-maintenance-field');
    const help = document.getElementById('inspection-maintenance-help');
    const nextDate = document.getElementById('inspection-next-date');
    const nextDateHelp = document.getElementById('inspection-next-date-help');
    const maintenance = inspectionObjectMaintenances.find(item => item.id == select.value);
    const template = inspectionTemplates.find(item => item.id == document.getElementById('inspection-template').value);
    field.classList.toggle('has-selection', !!maintenance);

    if (maintenance) {
        help.textContent = `Nur „${maintenance.description || 'Allgemeine Prüfung / Wartung'}“ wird mit dem Speichern zurückgesetzt.`;
        nextDateHelp.textContent = `Vorschlag: ${inspectionIntervalLabel(maintenance.interval_days)} ab heute. Der Termin bleibt editierbar.`;
        if (!preserveExistingDate) nextDate.value = inspectionDateAfterDays(maintenance.interval_days);
        return;
    }

    help.textContent = 'Keine Artikel-Prüffrist wird verändert – passend für tägliche Kontrollen oder zusätzliche Prüfungen.';
    if (template && template.default_interval_days) {
        nextDateHelp.textContent = `Standardintervall der Prüfkarte: ${inspectionIntervalLabel(template.default_interval_days)}. Der Termin bleibt editierbar.`;
        if (!preserveExistingDate) nextDate.value = inspectionDateAfterDays(template.default_interval_days);
    } else {
        nextDateHelp.textContent = 'Kein Standardintervall hinterlegt. Termin kann manuell eingetragen werden.';
        if (!preserveExistingDate) nextDate.value = '';
    }
}

async function openInspectionModal(objectId, preferredTemplateId = null, preferredMaintenanceId = null) {
    editingInspectionId = null;
    resetInspectionImageState();
    document.getElementById('inspection-object-id').value = objectId;
    document.getElementById('inspection-modal').style.display = 'block';
    document.getElementById('inspection-modal-title').textContent = 'Prüfung durchführen';
    document.getElementById('inspection-fields').innerHTML = '';
    document.getElementById('inspection-next-date').value = '';
    document.getElementById('inspection-notes').value = '';
    document.getElementById('inspection-inspector-name').value = currentUser && currentUser.username !== 'standard'
        ? (currentUser.full_name || '')
        : '';
    document.getElementById('inspection-camera-input').value = '';
    document.getElementById('inspection-upload-input').value = '';

    try {
        const [templates, objectData] = await Promise.all([
            api('/api/inspection-templates?object_id=' + encodeURIComponent(objectId)),
            api('/api/objects/' + encodeURIComponent(objectId))
        ]);
        inspectionTemplates = templates;
        inspectionObjectMaintenances = Array.isArray(objectData.maintenances) ? objectData.maintenances : [];
        const sel = document.getElementById('inspection-template');
        sel.disabled = false;
        sel.innerHTML = '<option value="">-- Prüfkarte wählen --</option>';
        inspectionTemplates.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.id;
            opt.textContent = t.name;
            sel.appendChild(opt);
        });
        if (currentUser && currentUser.role === 'standard') {
            if (inspectionTemplates.length !== 1) {
                closeInspectionModal();
                alert('Für dieses Objekt ist keine Prüfung für Standardnutzer freigegeben.');
                return;
            }
            sel.value = inspectionTemplates[0].id;
            sel.disabled = true;
            loadInspectionTemplate();
        } else if (preferredTemplateId && inspectionTemplates.some(t => t.id == preferredTemplateId)) {
            sel.value = preferredTemplateId;
            loadInspectionTemplate();
        }
        populateInspectionMaintenanceSelect(preferredMaintenanceId);
    } catch (e) { alert('Fehler beim Laden der Prüfkarten: ' + e.message); }
}

function closeInspectionModal() {
    closeInspectionImageMarker();
    document.getElementById('inspection-modal').style.display = 'none';
    editingInspectionId = null;
    resetInspectionImageState();
}

function resetInspectionImageState() {
    inspectionPendingImages.forEach(image => {
        if (image.previewUrl) URL.revokeObjectURL(image.previewUrl);
        if (image.originalUrl && image.originalUrl !== image.previewUrl) URL.revokeObjectURL(image.originalUrl);
    });
    inspectionPendingImages = [];
    inspectionExistingImages = [];
    const pending = document.getElementById('inspection-pending-images');
    const existing = document.getElementById('inspection-existing-images');
    if (pending) pending.innerHTML = '';
    if (existing) existing.innerHTML = '';
}

function addInspectionImages(input) {
    const files = Array.from(input.files || []);
    const remainingSlots = Math.max(0, 8 - inspectionPendingImages.length - inspectionExistingImages.length);
    if (!remainingSlots) {
        alert('Pro Prüfung können höchstens 8 Bilder hinterlegt werden.');
        input.value = '';
        return;
    }
    files.slice(0, remainingSlots).forEach(file => {
        if (!file.type.startsWith('image/')) return;
        const originalUrl = URL.createObjectURL(file);
        inspectionPendingImages.push({
            id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
            file,
            originalUrl,
            previewUrl: originalUrl,
            annotatedBlob: null,
            comment: ''
        });
    });
    if (files.length > remainingSlots) alert('Es wurden nur die ersten 8 Bilder übernommen.');
    input.value = '';
    renderInspectionPendingImages();
}

function renderInspectionPendingImages() {
    const container = document.getElementById('inspection-pending-images');
    container.innerHTML = inspectionPendingImages.map((image, index) => `
        <article class="inspection-image-card">
            <img src="${image.previewUrl}" alt="Neues Prüfungsbild ${index + 1}">
            <div class="inspection-image-card-body">
                <label for="inspection-image-comment-${image.id}">Kommentar zu Bild ${index + 1} *</label>
                <textarea id="inspection-image-comment-${image.id}" required maxlength="1000" placeholder="Was ist auf dem Bild zu sehen? Wo liegt der Mangel?" oninput="updateInspectionImageComment('${image.id}', this.value)">${escapeHtml(image.comment)}</textarea>
                <div class="inspection-image-card-actions">
                    <button type="button" class="btn-secondary btn-small" onclick="openInspectionImageMarker('${image.id}')">➜ Pfeil einzeichnen</button>
                    ${image.annotatedBlob ? `<button type="button" class="btn-secondary btn-small" onclick="restoreInspectionImageOriginal('${image.id}')">Original wiederherstellen</button>` : ''}
                    <button type="button" class="btn-secondary btn-small btn-delete" onclick="removePendingInspectionImage('${image.id}')">Entfernen</button>
                </div>
            </div>
        </article>
    `).join('');
}

function updateInspectionImageComment(imageId, value) {
    const image = inspectionPendingImages.find(item => item.id === imageId);
    if (image) image.comment = value;
}

function removePendingInspectionImage(imageId) {
    const index = inspectionPendingImages.findIndex(item => item.id === imageId);
    if (index < 0) return;
    const [image] = inspectionPendingImages.splice(index, 1);
    if (image.previewUrl) URL.revokeObjectURL(image.previewUrl);
    if (image.originalUrl && image.originalUrl !== image.previewUrl) URL.revokeObjectURL(image.originalUrl);
    renderInspectionPendingImages();
}

function restoreInspectionImageOriginal(imageId) {
    const image = inspectionPendingImages.find(item => item.id === imageId);
    if (!image || !image.annotatedBlob) return;
    if (image.previewUrl && image.previewUrl !== image.originalUrl) URL.revokeObjectURL(image.previewUrl);
    image.previewUrl = image.originalUrl;
    image.annotatedBlob = null;
    renderInspectionPendingImages();
}

function renderInspectionExistingImages() {
    const container = document.getElementById('inspection-existing-images');
    container.innerHTML = inspectionExistingImages.map((image, index) => `
        <article class="inspection-image-card existing">
            <img src="/uploads/inspection_images/${encodeURIComponent(image.filename)}" alt="Gespeichertes Prüfungsbild ${index + 1}" onclick="window.open(this.src, '_blank')">
            <div class="inspection-image-card-body">
                <span class="inspection-image-saved-label">✓ Bereits gespeichert</span>
                <p>${escapeHtml(image.comment).replace(/\n/g, '<br>')}</p>
                ${editingInspectionId ? `<button type="button" class="btn-secondary btn-small btn-delete" onclick="deleteExistingInspectionImage(${image.id})">Bild entfernen</button>` : ''}
            </div>
        </article>
    `).join('');
}

async function deleteExistingInspectionImage(imageId) {
    if (!confirm('Dieses Prüfungsbild wirklich entfernen?')) return;
    try {
        await api('/api/inspection-images/' + imageId, { method: 'DELETE' });
        inspectionExistingImages = inspectionExistingImages.filter(image => image.id !== imageId);
        renderInspectionExistingImages();
    } catch (error) {
        alert('Bild konnte nicht entfernt werden: ' + error.message);
    }
}

async function openInspectionImageMarker(imageId) {
    return openPendingImageMarker(imageId, 'inspection');
}

async function openMessageImageMarker(imageId) {
    return openPendingImageMarker(imageId, 'message');
}

async function openPendingImageMarker(imageId, context) {
    const images = context === 'message' ? messagePendingImages : inspectionPendingImages;
    const image = images.find(item => item.id === imageId);
    if (!image) return;
    imageMarkerContext = context;
    activeInspectionMarkerId = imageId;
    inspectionMarkerArrows = [];
    inspectionMarkerStart = null;
    inspectionMarkerDraftEnd = null;
    inspectionMarkerColor = '#e00000';
    updateInspectionArrowColorControls();
    try {
        inspectionMarkerImage = await loadInspectionMarkerImage(image.previewUrl);
        const canvas = document.getElementById('inspection-marker-canvas');
        const maxDimension = 1600;
        const scale = Math.min(1, maxDimension / Math.max(inspectionMarkerImage.naturalWidth, inspectionMarkerImage.naturalHeight));
        canvas.width = Math.max(1, Math.round(inspectionMarkerImage.naturalWidth * scale));
        canvas.height = Math.max(1, Math.round(inspectionMarkerImage.naturalHeight * scale));
        initializeInspectionMarkerCanvas(canvas);
        drawInspectionMarker();
        document.getElementById('inspection-image-marker-modal').style.display = 'block';
    } catch (_) {
        alert('Das Bild konnte nicht für die Markierung geöffnet werden.');
    }
}

function loadInspectionMarkerImage(source) {
    return new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = reject;
        image.src = source;
    });
}

function initializeInspectionMarkerCanvas(canvas) {
    if (canvas.dataset.markerReady === 'true') return;
    canvas.dataset.markerReady = 'true';
    canvas.addEventListener('pointerdown', event => {
        event.preventDefault();
        canvas.setPointerCapture(event.pointerId);
        inspectionMarkerStart = getInspectionCanvasPoint(canvas, event);
        inspectionMarkerDraftEnd = inspectionMarkerStart;
        inspectionMarkerDrawing = true;
        drawInspectionMarker();
    });
    canvas.addEventListener('pointermove', event => {
        if (!inspectionMarkerDrawing) return;
        event.preventDefault();
        inspectionMarkerDraftEnd = getInspectionCanvasPoint(canvas, event);
        drawInspectionMarker();
    });
    const finishArrow = event => {
        if (!inspectionMarkerDrawing || !inspectionMarkerStart) return;
        event.preventDefault();
        const end = getInspectionCanvasPoint(canvas, event);
        const distance = Math.hypot(end.x - inspectionMarkerStart.x, end.y - inspectionMarkerStart.y);
        if (distance > Math.max(12, canvas.width * 0.015)) {
            inspectionMarkerArrows.push({ start: inspectionMarkerStart, end, color: inspectionMarkerColor });
        }
        inspectionMarkerDrawing = false;
        inspectionMarkerStart = null;
        inspectionMarkerDraftEnd = null;
        drawInspectionMarker();
    };
    canvas.addEventListener('pointerup', finishArrow);
    canvas.addEventListener('pointercancel', finishArrow);
}

function getInspectionCanvasPoint(canvas, event) {
    const bounds = canvas.getBoundingClientRect();
    return {
        x: (event.clientX - bounds.left) * canvas.width / bounds.width,
        y: (event.clientY - bounds.top) * canvas.height / bounds.height
    };
}

function drawInspectionMarker() {
    const canvas = document.getElementById('inspection-marker-canvas');
    if (!inspectionMarkerImage || !canvas.width || !canvas.height) return;
    const context = canvas.getContext('2d');
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(inspectionMarkerImage, 0, 0, canvas.width, canvas.height);
    inspectionMarkerArrows.forEach(arrow => drawInspectionArrow(context, arrow.start, arrow.end, canvas.width, arrow.color));
    if (inspectionMarkerDrawing && inspectionMarkerStart && inspectionMarkerDraftEnd) {
        drawInspectionArrow(context, inspectionMarkerStart, inspectionMarkerDraftEnd, canvas.width, inspectionMarkerColor);
    }
}

function drawInspectionArrow(context, start, end, canvasWidth, color = '#e00000') {
    const lineWidth = Math.max(4, canvasWidth / 260);
    const headLength = Math.max(18, canvasWidth / 35);
    const angle = Math.atan2(end.y - start.y, end.x - start.x);
    context.save();
    context.strokeStyle = color;
    context.fillStyle = color;
    context.lineWidth = lineWidth;
    context.lineCap = 'round';
    context.lineJoin = 'round';
    context.beginPath();
    context.moveTo(start.x, start.y);
    context.lineTo(end.x, end.y);
    context.stroke();
    context.beginPath();
    context.moveTo(end.x, end.y);
    context.lineTo(end.x - headLength * Math.cos(angle - Math.PI / 6), end.y - headLength * Math.sin(angle - Math.PI / 6));
    context.lineTo(end.x - headLength * Math.cos(angle + Math.PI / 6), end.y - headLength * Math.sin(angle + Math.PI / 6));
    context.closePath();
    context.fill();
    context.restore();
}

function setInspectionArrowColor(color) {
    if (!['#e00000', '#111111'].includes(color)) return;
    inspectionMarkerColor = color;
    updateInspectionArrowColorControls();
    drawInspectionMarker();
}

function updateInspectionArrowColorControls() {
    document.querySelectorAll('.inspection-marker-color').forEach(button => {
        const selected = button.dataset.markerColor === inspectionMarkerColor;
        button.classList.toggle('active', selected);
        button.setAttribute('aria-pressed', selected ? 'true' : 'false');
    });
}

function undoInspectionArrow() { inspectionMarkerArrows.pop(); drawInspectionMarker(); }
function clearInspectionArrows() { inspectionMarkerArrows = []; drawInspectionMarker(); }

function closeInspectionImageMarker() {
    const modal = document.getElementById('inspection-image-marker-modal');
    if (modal) modal.style.display = 'none';
    activeInspectionMarkerId = null;
    inspectionMarkerImage = null;
    inspectionMarkerArrows = [];
    inspectionMarkerDrawing = false;
    imageMarkerContext = 'inspection';
}

function applyInspectionImageMarker() {
    if (!activeInspectionMarkerId || !inspectionMarkerArrows.length) {
        alert('Bitte zuerst mindestens einen Pfeil in das Bild zeichnen.');
        return;
    }
    const markerContext = imageMarkerContext;
    const images = markerContext === 'message' ? messagePendingImages : inspectionPendingImages;
    const image = images.find(item => item.id === activeInspectionMarkerId);
    const canvas = document.getElementById('inspection-marker-canvas');
    if (!image) return;
    canvas.toBlob(blob => {
        if (!blob) return alert('Die Markierung konnte nicht gespeichert werden.');
        if (image.previewUrl && image.previewUrl !== image.originalUrl) URL.revokeObjectURL(image.previewUrl);
        image.annotatedBlob = blob;
        image.previewUrl = URL.createObjectURL(blob);
        closeInspectionImageMarker();
        if (markerContext === 'message') renderMessagePendingImages();
        else renderInspectionPendingImages();
    }, 'image/jpeg', 0.9);
}

function loadInspectionTemplate() {
    const templateId = document.getElementById('inspection-template').value;
    const container = document.getElementById('inspection-fields');
    if (!templateId) {
        container.innerHTML = '';
        updateInspectionDueSelection();
        return;
    }

    const template = inspectionTemplates.find(t => t.id == templateId);
    if (!template) return;

    let fields;
    try {
        fields = JSON.parse(template.fields);
    } catch (e) { container.innerHTML = '<p>Fehler beim Laden der Prüfkarte</p>'; return; }

    let html = `<h4>${escapeHtml(template.name)}</h4>`;
    if (template.description) html += `<p><small>${escapeHtml(template.description)}</small></p>`;

    fields.forEach((field, idx) => {
        const required = field.required ? 'required' : '';
        const reqLabel = field.required ? ' *' : '';
        html += `<div class="inspection-field">`;

        if (field.type === 'checkbox') {
            html += `
                <label>
                    <input type="checkbox" id="ins-field-${idx}" name="${escapeHtml(field.label)}" ${required}>
                    ${escapeHtml(field.label)}${reqLabel}
                </label>
            `;
        } else if (field.type === 'select' && field.options) {
            html += `<label>${escapeHtml(field.label)}${reqLabel}</label>`;
            html += `<select id="ins-field-${idx}" ${required}>`;
            html += `<option value="">-- Auswählen --</option>`;
            field.options.forEach(opt => {
                html += `<option value="${escapeHtml(opt)}">${escapeHtml(opt)}</option>`;
            });
            html += `</select>`;
        } else if (field.type === 'textarea') {
            html += `<label>${escapeHtml(field.label)}${reqLabel}</label>`;
            html += `<textarea id="ins-field-${idx}" rows="2" ${required}></textarea>`;
        } else {
            html += `<label>${escapeHtml(field.label)}${reqLabel}</label>`;
            html += `<input type="${field.type}" id="ins-field-${idx}" ${required}>`;
        }
        html += `</div>`;
    });

    container.innerHTML = html;
    updateInspectionDueSelection();
}

async function saveInspection(e) {
    e.preventDefault();
    const objectId = document.getElementById('inspection-object-id').value;
    const templateId = document.getElementById('inspection-template').value;
    if (!templateId) return alert('Bitte eine Prüfkarte auswählen');
    const inspectorName = document.getElementById('inspection-inspector-name').value.trim();
    if (!inspectorName) {
        document.getElementById('inspection-inspector-name').focus();
        return alert('Bitte den Namen des Prüfers eintragen');
    }
    const imageWithoutComment = inspectionPendingImages.find(image => !image.comment.trim());
    if (imageWithoutComment) {
        document.getElementById(`inspection-image-comment-${imageWithoutComment.id}`)?.focus();
        return alert('Bitte zu jedem Bild einen Kommentar eintragen');
    }

    const template = inspectionTemplates.find(t => t.id == templateId);
    if (!template) return;

    let fields;
    try {
        fields = JSON.parse(template.fields);
    } catch (e) { alert('Fehler beim Lesen der Prüfkarte'); return; }

    const results = {};
    let valid = true;
    fields.forEach((field, idx) => {
        const el = document.getElementById(`ins-field-${idx}`);
        if (!el) return;
        if (field.type === 'checkbox') {
            results[field.label] = el.checked;
        } else {
            results[field.label] = el.value;
        }
        if (field.required && !results[field.label] && results[field.label] !== false) {
            valid = false;
            el.style.borderColor = 'red';
        }
    });

    if (!valid) return alert('Bitte alle Pflichtfelder ausfüllen');

    const data = {
        template_id: parseInt(templateId),
        maintenance_id: parseInt(document.getElementById('inspection-maintenance').value) || null,
        inspector_name: inspectorName,
        results: results,
        next_inspection_date: document.getElementById('inspection-next-date').value || null,
        notes: document.getElementById('inspection-notes').value || null
    };

    const submitButton = e.submitter;
    const originalButtonText = submitButton ? submitButton.textContent : '';
    if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = inspectionPendingImages.length ? 'Prüfung und Bilder werden gespeichert …' : 'Prüfung wird gespeichert …';
    }
    try {
        let savedInspection;
        if (editingInspectionId) {
            savedInspection = await api('/api/inspections/' + editingInspectionId, {
                method: 'PUT',
                body: JSON.stringify(data)
            });
        } else {
            savedInspection = await api('/api/objects/' + objectId + '/inspections', {
                method: 'POST',
                body: JSON.stringify(data)
            });
        }
        const uploadErrors = await uploadPendingInspectionImages(savedInspection.id);
        if (uploadErrors.length) {
            editingInspectionId = savedInspection.id;
            document.getElementById('inspection-modal-title').textContent = 'Prüfung bearbeiten';
            alert(`Die Prüfung wurde gespeichert. ${uploadErrors.length} Bild(er) konnten noch nicht hochgeladen werden: ${uploadErrors.join(' · ')}`);
            return;
        }
        if (editingInspectionId) {
            closeInspectionModal();
            alert('Prüfung aktualisiert!');
        } else {
            closeInspectionModal();
            alert('Prüfung gespeichert!');
        }
        await openObject(parseInt(objectId), { replaceHistory: true });
    } catch (error) {
        alert('Fehler: ' + error.message);
    } finally {
        if (submitButton && document.body.contains(submitButton)) {
            submitButton.disabled = false;
            submitButton.textContent = originalButtonText;
        }
    }
}

async function prepareInspectionImageBlob(image) {
    if (image.annotatedBlob) return image.annotatedBlob;
    const source = await loadInspectionMarkerImage(image.originalUrl);
    const maxDimension = 2000;
    const scale = Math.min(1, maxDimension / Math.max(source.naturalWidth, source.naturalHeight));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(source.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(source.naturalHeight * scale));
    canvas.getContext('2d').drawImage(source, 0, 0, canvas.width, canvas.height);
    return new Promise((resolve, reject) => {
        canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Bild konnte nicht verarbeitet werden')), 'image/jpeg', 0.9);
    });
}

async function uploadPendingInspectionImages(inspectionId) {
    const errors = [];
    for (const image of [...inspectionPendingImages]) {
        try {
            const blob = await prepareInspectionImageBlob(image);
            const formData = new FormData();
            formData.append('file', blob, image.annotatedBlob ? 'markiertes-pruefungsbild.jpg' : 'pruefungsbild.jpg');
            formData.append('comment', image.comment.trim());
            const savedImage = await uploadFile(`/api/inspections/${inspectionId}/images`, formData);
            inspectionExistingImages.push(savedImage);
            removePendingInspectionImage(image.id);
        } catch (error) {
            errors.push(error.message);
        }
    }
    renderInspectionExistingImages();
    return errors;
}

async function editInspection(inspectionId) {
    try {
        const i = await api('/api/inspections/' + inspectionId);
        editingInspectionId = inspectionId;

        document.getElementById('inspection-object-id').value = i.object_id;
        document.getElementById('inspection-modal').style.display = 'block';
        document.getElementById('inspection-fields').innerHTML = '';
        document.getElementById('inspection-next-date').value = i.next_inspection_date || '';
        document.getElementById('inspection-notes').value = i.notes || '';
        document.getElementById('inspection-inspector-name').value = i.inspector_name || i.inspected_by_name || '';
        resetInspectionImageState();
        inspectionExistingImages = Array.isArray(i.images) ? i.images : [];
        renderInspectionExistingImages();
        document.getElementById('inspection-modal-title').textContent = 'Prüfung bearbeiten';

        // Template laden und Felder vorausfüllen
        const [templates, objectData] = await Promise.all([
            api('/api/inspection-templates?object_id=' + encodeURIComponent(i.object_id)),
            api('/api/objects/' + encodeURIComponent(i.object_id))
        ]);
        inspectionTemplates = templates;
        inspectionObjectMaintenances = Array.isArray(objectData.maintenances) ? objectData.maintenances : [];
        const sel = document.getElementById('inspection-template');
        sel.innerHTML = '';
        inspectionTemplates.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.id;
            opt.textContent = t.name;
            sel.appendChild(opt);
        });
        sel.value = i.template_id;
        sel.disabled = true; // Template kann nicht geändert werden
        populateInspectionMaintenanceSelect(i.maintenance_id, true);

        // Felder laden und mit bestehenden Werten füllen
        const template = inspectionTemplates.find(t => t.id == i.template_id);
        if (!template) return;

        let fields;
        try {
            fields = JSON.parse(template.fields);
        } catch (e) { alert('Fehler beim Laden der Prüfkarte'); return; }

        let results = {};
        try { results = JSON.parse(i.results); } catch(e) {}

        let html = `<h4>${escapeHtml(template.name)}</h4>`;
        if (template.description) html += `<p><small>${escapeHtml(template.description)}</small></p>`;

        fields.forEach((field, idx) => {
            const required = field.required ? 'required' : '';
            const reqLabel = field.required ? ' *' : '';
            const existingValue = results[field.label];
            html += `<div class="inspection-field">`;

            if (field.type === 'checkbox') {
                html += `
                    <label>
                        <input type="checkbox" id="ins-field-${idx}" name="${escapeHtml(field.label)}" ${required} ${existingValue === true ? 'checked' : ''}>
                        ${escapeHtml(field.label)}${reqLabel}
                    </label>
                `;
            } else if (field.type === 'select' && field.options) {
                html += `<label>${escapeHtml(field.label)}${reqLabel}</label>`;
                html += `<select id="ins-field-${idx}" ${required}>`;
                html += `<option value="">-- Auswählen --</option>`;
                field.options.forEach(opt => {
                    html += `<option value="${escapeHtml(opt)}" ${existingValue === opt ? 'selected' : ''}>${escapeHtml(opt)}</option>`;
                });
                html += `</select>`;
            } else if (field.type === 'textarea') {
                html += `<label>${escapeHtml(field.label)}${reqLabel}</label>`;
                html += `<textarea id="ins-field-${idx}" rows="2" ${required}>${escapeHtml(existingValue || '')}</textarea>`;
            } else {
                html += `<label>${escapeHtml(field.label)}${reqLabel}</label>`;
                html += `<input type="${field.type}" id="ins-field-${idx}" value="${escapeHtml(existingValue || '')}" ${required}>`;
            }
            html += `</div>`;
        });

        document.getElementById('inspection-fields').innerHTML = html;
    } catch (e) { alert('Fehler: ' + e.message); }
}

// === Utils ===
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatStatus(s) {
    const map = {
        'in_benutzung': 'In Benutzung',
        'in_reparatur': 'In Reparatur',
        'ausgemustert': 'Ausgemustert',
        'reserve': 'Reserve',
        'zur_reinigung': 'Zur Reinigung'
    };
    return map[s] || s;
}

// === View Old Inspection ===
async function viewInspection(inspectionId) {
    try {
        const i = await api('/api/inspections/' + inspectionId);
        let results = {};
        try { results = JSON.parse(i.results); } catch(e) {}
        
        document.getElementById('view-inspection-title').textContent = i.template_name || 'Prüfung';
        
        let html = `
            <div style="margin-bottom:1rem; padding:0.8rem; background:#f5f5f5; border-radius:6px;">
                <strong>📅 Prüfdatum:</strong> ${new Date(i.inspected_at).toLocaleDateString('de-DE')}<br>
                <strong>👤 Prüfer:</strong> ${escapeHtml(i.inspector_name || i.inspected_by_name || '-')}<br>
                ${i.maintenance_description ? `<strong>🔄 Zurückgesetzte Prüffrist:</strong> ${escapeHtml(i.maintenance_description)}<br>` : ''}
                ${i.next_inspection_date ? `<strong>📌 Nächste Prüfung:</strong> ${i.next_inspection_date}<br>` : ''}
            </div>
            <h3>Prüfergebnisse</h3>
        `;
        
        Object.entries(results).forEach(([key, value]) => {
            let displayValue;
            if (value === true) displayValue = '<span style="color:#2e7d32; font-weight:600;">✅ Ja / OK</span>';
            else if (value === false) displayValue = '<span style="color:#c62828; font-weight:600;">❌ Nein / Mangel</span>';
            else if (value === '' || value === null || value === undefined) displayValue = '<span style="color:#999;">–</span>';
            else displayValue = escapeHtml(String(value));
            
            html += `
                <div class="inspection-field" style="margin:0.5rem 0;">
                    <strong>${escapeHtml(key)}</strong><br>
                    ${displayValue}
                </div>
            `;
        });
        
        if (i.notes) {
            html += `
                <h3>Bemerkungen</h3>
                <div class="inspection-field">${escapeHtml(i.notes).replace(/\n/g, '<br>')}</div>
            `;
        }

        if (i.images && i.images.length) {
            html += `<h3>Bilddokumentation</h3><div class="inspection-view-gallery">`;
            html += i.images.map((image, index) => `
                <figure class="inspection-view-image">
                    <img src="/uploads/inspection_images/${encodeURIComponent(image.filename)}" alt="Prüfungsbild ${index + 1}" onclick="window.open(this.src, '_blank')">
                    <figcaption><strong>Bild ${index + 1}:</strong> ${escapeHtml(image.comment)}</figcaption>
                </figure>
            `).join('');
            html += `</div>`;
        }
        
        document.getElementById('view-inspection-body').innerHTML = html;
        document.getElementById('view-inspection-modal').style.display = 'block';
    } catch (e) { alert('Fehler: ' + e.message); }
}

function closeViewInspectionModal() {
    document.getElementById('view-inspection-modal').style.display = 'none';
}

// Modal close on outside click
window.onclick = function(event) {
    const modal1 = document.getElementById('inspection-modal');
    const modal2 = document.getElementById('view-inspection-modal');
    const modal3 = document.getElementById('delete-modal');
    const modal4 = document.getElementById('inspection-image-marker-modal');
    const modal5 = document.getElementById('message-history-modal');
    const modal6 = document.getElementById('message-archive-modal');
    if (event.target === modal1) {
        closeInspectionModal();
    }
    if (event.target === modal2) {
        closeViewInspectionModal();
    }
    if (event.target === modal3) {
        closeDeleteModal();
    }
    if (event.target === modal4) {
        closeInspectionImageMarker();
    }
    if (event.target === modal5) {
        closeMessageHistoryModal();
    }
    if (event.target === modal6) {
        closeMessageArchiveModal();
    }
};

// === Import / Export ===
async function exportCSV() {
    try {
        const res = await fetch('/api/export/csv', {
            headers: token ? { 'Authorization': `Bearer ${token}` } : {}
        });
        if (!res.ok) throw new Error('Export fehlgeschlagen');
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const filename = res.headers.get('content-disposition')?.match(/filename="([^"]+)"/)?.[1] || 'feuerwehr_export.csv';
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (e) { alert('Fehler beim Export: ' + e.message); }
}

async function importCSV() {
    const fileInput = document.getElementById('import-csv-file');
    if (!fileInput.files.length) {
        alert('Bitte eine CSV-Datei auswählen');
        return;
    }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    try {
        const res = await fetch('/api/import/csv', {
            method: 'POST',
            headers: token ? { 'Authorization': `Bearer ${token}` } : {},
            body: formData
        });

        const result = await res.json();
        if (!res.ok) {
            throw new Error(result.detail || 'Import fehlgeschlagen');
        }

        let html = `
            <div style="padding:1rem; background:#e8f5e9; border-radius:8px; margin-top:1rem;">
                <h4 style="margin-top:0;">✅ Import abgeschlossen</h4>
                <p><strong>${result.created}</strong> neue Objekte angelegt</p>
                <p><strong>${result.skipped}</strong> bestehende Objekte übersprungen</p>
        `;
        if (result.errors && result.errors.length) {
            html += `<details><summary style="color:#c62828; cursor:pointer;">⚠️ ${result.errors.length} Fehler anzeigen</summary><ul style="margin-top:0.5rem; font-size:0.85rem;">`;
            result.errors.forEach(err => {
                html += `<li>${escapeHtml(err)}</li>`;
            });
            html += '</ul></details>';
        }
        html += '</div>';

        document.getElementById('import-result').innerHTML = html;
        fileInput.value = '';

        if (result.created > 0) {
            loadMasterData();
        }
    } catch (e) {
        alert('Fehler beim Import: ' + e.message);
    }
}

// === Vollständiges Backup (ZIP mit DB + Uploads) ===
async function downloadFullBackup() {
    try {
        const res = await fetch('/api/export/full-backup', {
            headers: token ? { 'Authorization': `Bearer ${token}` } : {}
        });
        if (!res.ok) {
            const data = await res.json();
            throw new Error(data.detail || 'Download fehlgeschlagen');
        }
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `feuerwehr_backup_${new Date().toISOString().slice(0,10)}.zip`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (e) { alert('Fehler beim Download: ' + e.message); }
}

async function uploadFullBackup(input) {
    const file = input.files[0];
    if (!file) return;
    if (!file.name.endsWith('.zip')) {
        alert('Bitte eine ZIP-Datei auswählen');
        input.value = '';
        return;
    }
    if (!confirm('⚠️ WARNUNG: Das aktuelle Backup wird komplett ersetzt (Datenbank + alle Bilder/Dokumente).\\n\\nBist du sicher?')) {
        input.value = '';
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch('/api/import/full-backup', {
            method: 'POST',
            headers: token ? { 'Authorization': `Bearer ${token}` } : {},
            body: formData
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Wiederherstellung fehlgeschlagen');
        alert(data.message || 'Backup erfolgreich wiederhergestellt!');
        setTimeout(() => location.reload(), 3000);
    } catch (e) { alert('Fehler: ' + e.message); }
    input.value = '';
}

// === Prüfarchiv ===
function initArchiveYears() {
    const sel = document.getElementById('archive-year');
    if (!sel) return;
    sel.innerHTML = '';
    const currentYear = new Date().getFullYear();
    for (let y = currentYear; y >= currentYear - 5; y--) {
        const opt = document.createElement('option');
        opt.value = y;
        opt.textContent = y;
        sel.appendChild(opt);
    }
}

async function exportArchive() {
    const year = document.getElementById('archive-year').value;
    try {
        const res = await fetch('/api/export/inspections/' + year, {
            headers: token ? { 'Authorization': `Bearer ${token}` } : {}
        });
        if (!res.ok) throw new Error('Archiv-Download fehlgeschlagen');
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `pruefarchiv_${year}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (e) { alert('Fehler beim Download: ' + e.message); }
}

async function exportArchivePDF() {
    const year = document.getElementById('archive-year').value;
    try {
        const res = await fetch('/api/export/inspections/' + year + '/pdf', {
            headers: token ? { 'Authorization': `Bearer ${token}` } : {}
        });
        if (!res.ok) {
            if (res.status === 404) throw new Error('Keine Prüfungen für dieses Jahr gefunden');
            throw new Error('PDF-Archiv-Download fehlgeschlagen');
        }
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `pruefarchiv_${year}.zip`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (e) { alert('Fehler beim Download: ' + e.message); }
}

// === Messages / Dashboard ===
let messages = [];
let archivedMessages = [];
let messagePendingImages = [];

async function loadDashboardMessages() {
    try {
        messages = await api('/api/messages');
        renderDashboardMessages();
    } catch (e) { console.error('Fehler beim Laden der Meldungen:', e); }
}

async function loadMessageArchive() {
    if (!currentUser || currentUser.role === 'standard') return;
    const results = document.getElementById('message-archive-results');
    const summary = document.getElementById('message-archive-summary');
    const meta = document.getElementById('message-archive-result-meta');
    summary.innerHTML = '';
    meta.textContent = '';
    results.innerHTML = '<div class="empty-state">Meldungsarchiv wird geladen …</div>';
    try {
        archivedMessages = await api('/api/messages/archive');
        filterMessageArchive();
    } catch (error) {
        results.innerHTML = `<div class="empty-state error-state">Meldungsarchiv konnte nicht geladen werden: ${escapeHtml(error.message)}</div>`;
    }
}

function messageArchiveResolution(message) {
    if (message.archive_reason) return message.archive_reason;
    if (message.status === 'geloescht') return 'altbestand';
    return message.status || 'altbestand';
}

function filterMessageArchive(event) {
    if (event) event.preventDefault();
    const searchField = document.getElementById('message-archive-search');
    if (!searchField) return;
    const query = searchField.value.trim().toLocaleLowerCase('de-DE');
    const resolution = document.getElementById('message-archive-resolution-filter').value;
    const linkFilter = document.getElementById('message-archive-link-filter').value;
    const from = document.getElementById('message-archive-from').value;
    const to = document.getElementById('message-archive-to').value;

    const filtered = archivedMessages.filter(message => {
        const archiveDate = (message.archived_at || message.updated_at || message.created_at || '').slice(0, 10);
        const searchable = [
            message.subject,
            message.device_name,
            message.device_id,
            message.description,
            message.action_comment,
            message.reported_by_name,
            message.created_by_name,
            message.archived_by_name,
            ...(message.history || []).flatMap(entry => [entry.details, entry.author_name, entry.status])
        ].filter(Boolean).join(' ').toLocaleLowerCase('de-DE');
        if (query && !searchable.includes(query)) return false;
        if (resolution && messageArchiveResolution(message) !== resolution) return false;
        if (linkFilter === 'linked' && !message.inventory_object_id) return false;
        if (linkFilter === 'unlinked' && message.inventory_object_id) return false;
        if (from && archiveDate && archiveDate < from) return false;
        if (to && archiveDate && archiveDate > to) return false;
        return true;
    });

    const counts = {
        total: filtered.length,
        completed: filtered.filter(message => messageArchiveResolution(message) === 'abgeschlossen').length,
        disposed: filtered.filter(message => messageArchiveResolution(message) === 'entsorgt').length,
        unlinked: filtered.filter(message => !message.inventory_object_id).length
    };
    document.getElementById('message-archive-summary').innerHTML = `
        <div class="inspection-summary-card"><strong>${counts.total}</strong><span>Gefundene Vorgänge</span></div>
        <div class="inspection-summary-card info"><strong>${counts.completed}</strong><span>Abgeschlossen</span></div>
        <div class="inspection-summary-card warning"><strong>${counts.disposed}</strong><span>Entsorgt</span></div>
        <div class="inspection-summary-card danger"><strong>${counts.unlinked}</strong><span>Ohne Artikelzuordnung</span></div>
    `;
    document.getElementById('message-archive-result-meta').textContent = filtered.length === archivedMessages.length
        ? `${filtered.length} archivierte Vorgänge`
        : `${filtered.length} von ${archivedMessages.length} Vorgängen gefunden`;
    renderObjectMessageHistory(document.getElementById('message-archive-results'), filtered, 'archive-results');
}

function resetMessageArchiveFilters() {
    document.getElementById('message-archive-filter').reset();
    filterMessageArchive();
}

function scanMessageArchiveSearch() {
    startQrScan(decodedText => {
        const match = decodedText.match(/FFW-\d+/i);
        document.getElementById('message-archive-search').value = match ? match[0].toUpperCase() : decodedText;
        filterMessageArchive();
    }, null, {
        title: 'Artikel im Meldungsarchiv finden',
        hint: 'QR-Code des Inventarartikels vollständig in den Rahmen halten.'
    });
}

function renderDashboardMessages() {
    const container = document.getElementById('messages-list');
    if (!container) return;

    if (!messages.length) {
        container.innerHTML = '<p style="color:#999; padding:1rem;">Keine aktuellen Meldungen.</p>';
        return;
    }

    const canManageMessages = currentUser && (currentUser.role === 'admin' || currentUser.role === 'verwaltung' || currentUser.role === 'erweitert');

    let html = '';
    messages.forEach(m => {
        const isClosed = m.is_closed;
        const opacity = isClosed ? 'opacity:0.6;' : '';
        const priorityColors = { hoch: '#c62828', mittel: '#f57c00', niedrig: '#388e3c' };
        const priorityColor = priorityColors[m.priority] || '#666';
        const typeLabels = {
            beschaedigung: 'Beschädigung',
            auffaelligkeit: 'Auffälligkeit',
            defekt: 'Defekt',
            info: 'Info',
            notiz: 'Notiz',
            sonstiges: 'Sonstiges'
        };
        const statusLabels = {
            offen: 'Offen',
            in_bearbeitung: 'In Bearbeitung',
            in_klaerung: 'In Klärung',
            zur_reparatur: 'Zur Reparatur',
            bedienungsfehler: 'Bedienungsfehler',
            nicht_mehr_aufgetreten: 'Fehler nicht mehr aufgetreten',
            geprueft_ok: 'Gerät geprüft u. in Ordnung',
            entsorgt: 'Entsorgt',
            abgeschlossen: 'Abgeschlossen',
            wieder_geoeffnet: 'Wieder geöffnet'
        };
        const actionLabels = {
            keine: 'Keine',
            ausser_betrieb: 'Gerät außer Betrieb',
            auf_fahrzeug: 'Aktuell auf Fahrzeug verladen',
            in_werkstatt: 'In Werkstatt abgestellt',
            entsorgt: 'Entsorgt',
            sonstiges: 'Sonstiges'
        };
        const closedLabel = isClosed ? '<span class="badge" style="background:#555; color:white; margin-left:0.3rem;">✓ Abgeschlossen</span>' : '';
        const hiddenForStandardLabel = m.is_visible_to_standard === false
            ? '<span class="badge" style="background:#6a1b9a; color:white; margin-left:0.3rem;">🔒 Standard ausgeblendet</span>'
            : '';
        const history = Array.isArray(m.history) ? m.history : [];
        const historyHtml = history.length ? `
            <details class="message-history">
                <summary>🕓 Verlauf (${history.length})</summary>
                <ol class="message-history-list">
                    ${history.map(entry => {
                        const label = entry.entry_type === 'comment'
                            ? 'Kommentar'
                            : entry.entry_type === 'archive'
                                ? 'Archiviert'
                            : entry.entry_type === 'visibility'
                                ? 'Sichtbarkeit'
                                : (statusLabels[entry.status] || entry.status || 'Status geändert');
                        const dateText = new Date(entry.created_at).toLocaleString('de-DE', {
                            day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'
                        });
                        const expectedText = entry.expected_end_date
                            ? ` · vsl. ${new Date(entry.expected_end_date).toLocaleDateString('de-DE')}`
                            : '';
                        const typeClass = entry.entry_type === 'comment'
                            ? 'message-history-comment'
                            : entry.entry_type === 'archive'
                                ? 'message-history-archive'
                            : entry.entry_type === 'visibility' ? 'message-history-visibility' : '';
                        return `
                            <li class="${typeClass}">
                                <div class="message-history-meta">${escapeHtml(dateText)} · ${escapeHtml(entry.author_name)}</div>
                                <div class="message-history-text"><strong>${escapeHtml(label)}</strong>${entry.details ? ` · ${escapeHtml(entry.details)}` : ''}${escapeHtml(expectedText)}</div>
                            </li>
                        `;
                    }).join('')}
                </ol>
            </details>
        ` : '';

        html += `
            <div class="alert" style="margin-bottom:0.5rem; ${opacity} border-left:4px solid ${priorityColor};">
                <div class="message-card-header">
                    <div style="flex:1;">
                        <strong style="color:${priorityColor};">${typeLabels[m.message_type] || m.message_type}</strong>
                        <span class="badge" style="background:${priorityColor}; color:white; margin-left:0.3rem;">${m.priority}</span>
                        <span class="badge badge-reserve" style="margin-left:0.3rem;">${statusLabels[m.status] || m.status}</span>
                        ${closedLabel}${hiddenForStandardLabel}<br>
                        <strong>${escapeHtml(m.subject)}</strong>
                        ${m.device_name || m.device_id ? `<br><small>🛠️ ${m.device_name ? escapeHtml(m.device_name) : ''} ${m.device_id ? '(' + escapeHtml(m.device_id) + ')' : ''}</small>` : ''}
                        ${m.description ? `<br><small>${escapeHtml(m.description)}</small>` : ''}
                        <br><small><strong>Maßnahme:</strong> ${escapeHtml(actionLabels[m.action] || m.action || 'Keine')}${m.action_comment ? ` – ${escapeHtml(m.action_comment)}` : ''}</small>
                        ${m.images && m.images.length ? `
                            <div class="message-image-gallery">
                                ${m.images.map((image, index) => `
                                    <figure>
                                        <img src="/uploads/message_images/${encodeURIComponent(image.filename)}" alt="Schadensbild ${index + 1}" onclick="window.open(this.src, '_blank')">
                                        <figcaption>${escapeHtml(image.comment)}</figcaption>
                                    </figure>
                                `).join('')}
                            </div>
                        ` : ''}
                        <br><small style="color:#666;">📅 ${new Date(m.created_at).toLocaleDateString('de-DE')} | 👤 ${m.reported_by_name ? escapeHtml(m.reported_by_name) : escapeHtml(m.created_by_name)}${m.reported_by_name ? ' (via ' + escapeHtml(m.created_by_name) + ')' : ''}</small>
                        ${historyHtml}
                    </div>
                    ${canManageMessages ? `
                        <div class="message-admin-controls">
                            <select class="btn-small" aria-label="Status der Meldung ändern" onchange="if (this.value) openMessageHistoryModal(${m.id}, 'status', this.value); this.value = ''">
                                <option value="">Status setzen...</option>
                                <option value="in_bearbeitung">In Bearbeitung</option>
                                <option value="in_klaerung">In Klärung</option>
                                <option value="zur_reparatur">Zur Reparatur</option>
                                <option value="bedienungsfehler">Bedienungsfehler</option>
                                <option value="nicht_mehr_aufgetreten">Fehler nicht mehr aufgetreten</option>
                                <option value="geprueft_ok">Gerät geprüft u. in Ordnung</option>
                                <option value="entsorgt">Entsorgt</option>
                            </select>
                            <button type="button" class="btn-secondary btn-small" onclick="openMessageHistoryModal(${m.id}, 'comment')">💬 Kommentar</button>
                            <label class="message-visibility-toggle">
                                <input type="checkbox" ${m.is_visible_to_standard !== false ? 'checked' : ''} onchange="toggleMessageVisibility(${m.id}, this.checked)">
                                Für Standardnutzer sichtbar
                            </label>
                            <label class="message-visibility-toggle">
                                <input type="checkbox" ${isClosed ? 'checked' : ''} onchange="openMessageHistoryModal(${m.id}, 'close', this.checked)">
                                Abgeschlossen
                            </label>
                            <button type="button" class="btn-primary btn-small btn-delete" onclick="openMessageArchiveModal(${m.id})" aria-label="Meldung aus aktuellen Meldungen entfernen" title="Meldung sicher archivieren">🗑️ Meldung entfernen</button>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    });

    container.innerHTML = html;
}

function resetMessageImageState() {
    messagePendingImages.forEach(image => {
        if (image.previewUrl) URL.revokeObjectURL(image.previewUrl);
        if (image.originalUrl && image.originalUrl !== image.previewUrl) URL.revokeObjectURL(image.originalUrl);
    });
    messagePendingImages = [];
    const container = document.getElementById('message-pending-images');
    if (container) container.innerHTML = '';
    const cameraInput = document.getElementById('message-camera-input');
    const uploadInput = document.getElementById('message-upload-input');
    if (cameraInput) cameraInput.value = '';
    if (uploadInput) uploadInput.value = '';
}

function addMessageImages(input) {
    const files = Array.from(input.files || []);
    const remainingSlots = Math.max(0, 8 - messagePendingImages.length);
    if (!remainingSlots) {
        alert('Pro Meldung können höchstens 8 Bilder hinterlegt werden.');
        input.value = '';
        return;
    }
    files.slice(0, remainingSlots).forEach(file => {
        if (!file.type.startsWith('image/')) return;
        const originalUrl = URL.createObjectURL(file);
        messagePendingImages.push({
            id: `message-${Date.now()}-${Math.random().toString(16).slice(2)}`,
            file,
            originalUrl,
            previewUrl: originalUrl,
            annotatedBlob: null,
            comment: ''
        });
    });
    if (files.length > remainingSlots) alert('Es wurden nur die ersten 8 Bilder übernommen.');
    input.value = '';
    renderMessagePendingImages();
}

function renderMessagePendingImages() {
    const container = document.getElementById('message-pending-images');
    container.innerHTML = messagePendingImages.map((image, index) => `
        <article class="inspection-image-card">
            <img src="${image.previewUrl}" alt="Neues Schadensbild ${index + 1}">
            <div class="inspection-image-card-body">
                <label for="message-image-comment-${image.id}">Kommentar zu Bild ${index + 1} *</label>
                <textarea id="message-image-comment-${image.id}" required maxlength="1000" placeholder="Was ist auf dem Bild zu sehen? Wo liegt der Schaden?" oninput="updateMessageImageComment('${image.id}', this.value)">${escapeHtml(image.comment)}</textarea>
                <div class="inspection-image-card-actions">
                    <button type="button" class="btn-secondary btn-small" onclick="openMessageImageMarker('${image.id}')">➜ Pfeil einzeichnen</button>
                    ${image.annotatedBlob ? `<button type="button" class="btn-secondary btn-small" onclick="restoreMessageImageOriginal('${image.id}')">Original wiederherstellen</button>` : ''}
                    <button type="button" class="btn-secondary btn-small btn-delete" onclick="removePendingMessageImage('${image.id}')">Entfernen</button>
                </div>
            </div>
        </article>
    `).join('');
}

function updateMessageImageComment(imageId, value) {
    const image = messagePendingImages.find(item => item.id === imageId);
    if (image) image.comment = value;
}

function removePendingMessageImage(imageId) {
    const index = messagePendingImages.findIndex(item => item.id === imageId);
    if (index < 0) return;
    const [image] = messagePendingImages.splice(index, 1);
    if (image.previewUrl) URL.revokeObjectURL(image.previewUrl);
    if (image.originalUrl && image.originalUrl !== image.previewUrl) URL.revokeObjectURL(image.originalUrl);
    renderMessagePendingImages();
}

function restoreMessageImageOriginal(imageId) {
    const image = messagePendingImages.find(item => item.id === imageId);
    if (!image || !image.annotatedBlob) return;
    if (image.previewUrl && image.previewUrl !== image.originalUrl) URL.revokeObjectURL(image.previewUrl);
    image.previewUrl = image.originalUrl;
    image.annotatedBlob = null;
    renderMessagePendingImages();
}

function toggleMessageActionComment() {
    const isOther = document.getElementById('msg-action').value === 'sonstiges';
    const box = document.getElementById('msg-action-comment-box');
    const field = document.getElementById('msg-action-comment');
    box.classList.toggle('hidden', !isOther);
    field.required = isOther;
    if (!isOther) field.value = '';
}

function openMessageModal() {
    resetMessageImageState();
    document.getElementById('message-modal').style.display = 'block';
    document.getElementById('msg-action').value = 'keine';
    toggleMessageActionComment();
    // Auto-Priorität basierend auf Typ
    document.getElementById('msg-type').onchange = function() {
        const type = this.value;
        const prioritySel = document.getElementById('msg-priority');
        if (type === 'beschaedigung' || type === 'defekt') {
            prioritySel.value = 'hoch';
        }
    };
}

function closeMessageModal() {
    closeInspectionImageMarker();
    document.getElementById('message-modal').style.display = 'none';
    document.getElementById('message-form').reset();
    toggleMessageActionComment();
    resetMessageImageState();
}

async function saveMessage(e) {
    e.preventDefault();
    const action = document.getElementById('msg-action').value;
    const actionComment = document.getElementById('msg-action-comment').value.trim();
    if (action === 'sonstiges' && !actionComment) {
        document.getElementById('msg-action-comment').focus();
        return alert('Bitte die sonstige Maßnahme beschreiben.');
    }
    const imageWithoutComment = messagePendingImages.find(image => !image.comment.trim());
    if (imageWithoutComment) {
        document.getElementById(`message-image-comment-${imageWithoutComment.id}`)?.focus();
        return alert('Bitte zu jedem Schadensbild einen Kommentar eintragen.');
    }
    const data = {
        inventory_object_id: document.getElementById('msg-object-id').value
            ? Number(document.getElementById('msg-object-id').value)
            : null,
        message_type: document.getElementById('msg-type').value,
        subject: document.getElementById('msg-subject').value,
        device_name: document.getElementById('msg-device-name').value || null,
        device_id: document.getElementById('msg-device-id').value || null,
        description: document.getElementById('msg-description').value || null,
        action,
        action_comment: action === 'sonstiges' ? actionComment : null,
        priority: document.getElementById('msg-priority').value,
        reported_by_name: document.getElementById('msg-reported-by').value || null
    };

    const submitButton = e.submitter;
    const originalButtonText = submitButton ? submitButton.textContent : '';
    if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = messagePendingImages.length ? 'Meldung und Bilder werden gespeichert …' : 'Meldung wird gespeichert …';
    }
    try {
        const savedMessage = await api('/api/messages', { method: 'POST', body: JSON.stringify(data) });
        const uploadErrors = await uploadPendingMessageImages(savedMessage.id);
        closeMessageModal();
        alert(uploadErrors.length
            ? `Meldung gespeichert. ${uploadErrors.length} Bild(er) konnten nicht hochgeladen werden: ${uploadErrors.join(' · ')}`
            : 'Meldung gespeichert!');
        loadDashboardMessages();
    } catch (e) {
        alert('Fehler: ' + e.message);
    } finally {
        if (submitButton && document.body.contains(submitButton)) {
            submitButton.disabled = false;
            submitButton.textContent = originalButtonText;
        }
    }
}

async function uploadPendingMessageImages(messageId) {
    const errors = [];
    for (const image of messagePendingImages) {
        try {
            const blob = await prepareInspectionImageBlob(image);
            const formData = new FormData();
            formData.append('file', blob, image.annotatedBlob ? 'markiertes-schadensbild.jpg' : 'schadensbild.jpg');
            formData.append('comment', image.comment.trim());
            await uploadFile(`/api/messages/${messageId}/images`, formData);
        } catch (error) {
            errors.push(error.message);
        }
    }
    return errors;
}

function openMessageHistoryModal(messageId, mode, value = '') {
    const modal = document.getElementById('message-history-modal');
    const form = document.getElementById('message-history-form');
    const statusBox = document.getElementById('message-history-status-box');
    const endDateBox = document.getElementById('message-history-end-date-box');
    const details = document.getElementById('message-history-details');
    const detailsLabel = document.getElementById('message-history-details-label');
    const title = document.getElementById('message-history-modal-title');
    const intro = document.getElementById('message-history-modal-intro');
    const saveButton = document.getElementById('message-history-save-button');

    form.reset();
    document.getElementById('message-history-message-id').value = messageId;
    document.getElementById('message-history-mode').value = mode;
    document.getElementById('message-history-close-state').value = '';
    document.getElementById('message-history-author').value = currentUser?.full_name || '';
    statusBox.classList.toggle('hidden', mode !== 'status');
    endDateBox.classList.toggle('hidden', mode !== 'status');
    details.required = mode === 'comment';

    if (mode === 'status') {
        document.getElementById('message-history-status').value = value;
        title.textContent = 'Status dokumentieren';
        intro.textContent = 'Ort oder Firma und ein voraussichtliches Enddatum können direkt mitgespeichert werden.';
        detailsLabel.textContent = 'Ort / Firma / weiterer Hinweis';
        details.placeholder = 'z. B. Fa. Welter, Gerät liegt in der Werkstatt';
        saveButton.textContent = 'Status speichern';
    } else if (mode === 'comment') {
        title.textContent = 'Kommentar hinzufügen';
        intro.textContent = 'Die Anmerkung wird mit Datum, Uhrzeit und Name dauerhaft im Verlauf gespeichert.';
        detailsLabel.textContent = 'Kommentar *';
        details.placeholder = 'Sonstige Anmerkung zum Vorgang';
        saveButton.textContent = 'Kommentar speichern';
    } else {
        const willClose = value === true || value === 'true';
        document.getElementById('message-history-close-state').value = willClose ? 'true' : 'false';
        title.textContent = willClose ? 'Vorgang abschließen' : 'Vorgang wieder öffnen';
        intro.textContent = 'Der Schritt bleibt mit Datum und Name dauerhaft im Verlauf erhalten.';
        detailsLabel.textContent = willClose ? 'Abschlussnotiz (optional)' : 'Hinweis zum Wiederöffnen (optional)';
        details.placeholder = willClose ? 'z. B. Reparatur abgeschlossen und Gerät wieder einsatzbereit' : 'Warum wird der Vorgang wieder geöffnet?';
        saveButton.textContent = willClose ? 'Vorgang abschließen' : 'Wieder öffnen';
    }

    modal.style.display = 'block';
    if (mode === 'comment') details.focus();
}

function closeMessageHistoryModal() {
    document.getElementById('message-history-modal').style.display = 'none';
    renderDashboardMessages();
}

async function saveMessageHistoryEntry(event) {
    event.preventDefault();
    const messageId = document.getElementById('message-history-message-id').value;
    const mode = document.getElementById('message-history-mode').value;
    const details = document.getElementById('message-history-details').value.trim();
    const authorName = document.getElementById('message-history-author').value.trim();
    const saveButton = document.getElementById('message-history-save-button');
    const originalText = saveButton.textContent;
    saveButton.disabled = true;
    saveButton.textContent = 'Wird gespeichert …';

    try {
        if (mode === 'comment') {
            await api(`/api/messages/${messageId}/comments`, {
                method: 'POST',
                body: JSON.stringify({ comment: details, author_name: authorName })
            });
        } else {
            const payload = {
                details: details || null,
                author_name: authorName
            };
            if (mode === 'status') {
                payload.status = document.getElementById('message-history-status').value;
                payload.expected_end_date = document.getElementById('message-history-end-date').value || null;
            } else {
                payload.is_closed = document.getElementById('message-history-close-state').value === 'true';
            }
            await api(`/api/messages/${messageId}/status`, {
                method: 'PUT',
                body: JSON.stringify(payload)
            });
        }
        document.getElementById('message-history-modal').style.display = 'none';
        await loadDashboardMessages();
    } catch (e) {
        alert('Fehler: ' + e.message);
    } finally {
        saveButton.disabled = false;
        saveButton.textContent = originalText;
    }
}

async function toggleMessageVisibility(messageId, isVisible) {
    try {
        await api(`/api/messages/${messageId}/visibility`, {
            method: 'PUT',
            body: JSON.stringify({ is_visible_to_standard: isVisible })
        });
        await loadDashboardMessages();
    } catch (e) {
        alert('Fehler: ' + e.message);
        await loadDashboardMessages();
    }
}

function openMessageArchiveModal(messageId) {
    const form = document.getElementById('message-archive-form');
    const message = messages.find(item => item.id === messageId);
    form.reset();
    document.getElementById('message-archive-id').value = messageId;
    document.getElementById('message-archive-author').value = currentUser?.full_name || '';
    document.getElementById('message-archive-notice').innerHTML = message?.inventory_object_id
        ? 'Die Meldung wird <strong>nicht gelöscht</strong>. Bilder und vollständiger Verlauf bleiben dauerhaft beim Inventarartikel und zusätzlich im Meldungsarchiv erhalten.'
        : 'Die Meldung wird <strong>nicht gelöscht</strong>. Da kein vorhandener Inventarartikel eindeutig verknüpft ist, bleiben Bilder und vollständiger Verlauf dauerhaft im zentralen Meldungsarchiv erhalten.';
    document.getElementById('message-archive-modal').style.display = 'block';
}

function closeMessageArchiveModal() {
    document.getElementById('message-archive-modal').style.display = 'none';
}

async function archiveMessage(event) {
    event.preventDefault();
    const messageId = document.getElementById('message-archive-id').value;
    const button = document.getElementById('message-archive-save-button');
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = 'Wird archiviert …';
    try {
        await api(`/api/messages/${messageId}/archive`, {
            method: 'POST',
            body: JSON.stringify({
                resolution: document.getElementById('message-archive-resolution').value,
                comment: document.getElementById('message-archive-comment').value.trim() || null,
                author_name: document.getElementById('message-archive-author').value.trim()
            })
        });
        closeMessageArchiveModal();
        await loadDashboardMessages();
    } catch (e) {
        alert('Fehler: ' + e.message);
    } finally {
        button.disabled = false;
        button.textContent = originalText;
    }
}

function scanQrForMessage() {
    startQrScan((decodedText) => {
        const match = decodedText.match(/FFW-\d+/i);
        const deviceId = match ? match[0].toUpperCase() : decodedText;
        document.getElementById('msg-device-id').value = deviceId;
        // Gerätenamen automatisch laden
        api('/api/objects/resolve-code?q=' + encodeURIComponent(decodedText)).then(object => {
            document.getElementById('msg-device-name').value = object.designation;
            document.getElementById('msg-object-id').value = object.id;
        }).catch(() => {});
    }, 'message-modal');
}

async function exportMessagesLog() {
    try {
        const res = await fetch('/api/export/messages-log', {
            headers: token ? { 'Authorization': `Bearer ${token}` } : {}
        });
        if (!res.ok) throw new Error('Download fehlgeschlagen');
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `meldungslog_${new Date().toISOString().slice(0,10)}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (e) { alert('Fehler beim Download: ' + e.message); }
}

// === Init ===
// Prüfe ob QR-Login Parameter in URL vorhanden ist
const urlParams = new URLSearchParams(window.location.search);
if (urlParams.get('qrlogin') === '1') {
    handleQrLogin();
} else if (token) {
    initApp();
}
