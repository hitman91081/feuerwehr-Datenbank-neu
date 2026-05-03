// === State ===
let token = localStorage.getItem('token') || '';
let currentUser = null;
let masterData = { types: [], manufacturers: [], locations: [] };
let scanner = null;

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

function uploadFile(url, formData) {
    return fetch(url, {
        method: 'POST',
        headers: token ? { 'Authorization': `Bearer ${token}` } : {},
        body: formData
    }).then(r => { if (!r.ok) throw new Error('Upload fehlgeschlagen'); return r.json(); });
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
    }
    if (isAdmin) {
        document.getElementById('nav-admin').classList.remove('hidden');
    }

    await loadMasterData();
    showView('dashboard');
    loadDashboardAlerts();
}

function logout() {
    token = '';
    localStorage.removeItem('token');
    currentUser = null;
    location.reload();
}

// === Views ===
function showView(name) {
    document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
    document.getElementById('view-' + name).classList.remove('hidden');
    document.getElementById('mobile-menu').classList.add('hidden');
    window.scrollTo(0, 0);
}

function toggleMenu() {
    document.getElementById('mobile-menu').classList.toggle('hidden');
}

// === Master Data ===
async function loadMasterData() {
    masterData.types = await api('/api/object-types');
    masterData.manufacturers = await api('/api/manufacturers');
    masterData.locations = await api('/api/locations');
    fillSelect('obj-type', masterData.types, 'name');
    fillSelect('obj-manufacturer', masterData.manufacturers, 'name');
    fillSelect('obj-location', flattenLocations(masterData.locations), 'name');
    fillSelect('new-location-parent', flattenLocations(masterData.locations), 'name');

    // Filter-Dropdowns füllen
    fillFilterSelect('filter-type', masterData.types, 'name');
    fillFilterSelect('filter-location', flattenLocations(masterData.locations), 'name');
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
                document.getElementById('obj-vehicle-as-location').checked = false;
            }
        };
    }
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
function showAddManufacturer() {
    document.getElementById('add-manufacturer-box').classList.toggle('hidden');
    if (!document.getElementById('add-manufacturer-box').classList.contains('hidden')) {
        document.getElementById('new-manufacturer').focus();
    }
}

async function saveNewManufacturer() {
    const name = document.getElementById('new-manufacturer').value.trim();
    if (!name) return alert('Bitte Herstellername eingeben');
    try {
        const m = await api('/api/manufacturers', { method: 'POST', body: JSON.stringify({ name }) });
        masterData.manufacturers.push(m);
        fillSelect('obj-manufacturer', masterData.manufacturers, 'name');
        document.getElementById('obj-manufacturer').value = m.id;
        document.getElementById('new-manufacturer').value = '';
        document.getElementById('add-manufacturer-box').classList.add('hidden');
    } catch (e) { alert('Fehler: ' + e.message); }
}

function showAddLocation() {
    document.getElementById('add-location-box').classList.toggle('hidden');
    fillSelect('new-location-parent', flattenLocations(masterData.locations), 'name');
    if (!document.getElementById('add-location-box').classList.contains('hidden')) {
        document.getElementById('new-location').focus();
    }
}

async function saveNewLocation() {
    const name = document.getElementById('new-location').value.trim();
    const type = document.getElementById('new-location-type').value.trim() || 'Standort';
    const parentId = document.getElementById('new-location-parent').value || null;
    if (!name) return alert('Bitte Standortnamen eingeben');
    try {
        const loc = await api('/api/locations', { method: 'POST', body: JSON.stringify({ name, location_type: type, parent_id: parentId ? parseInt(parentId) : null }) });
        masterData.locations = await api('/api/locations');
        fillSelect('obj-location', flattenLocations(masterData.locations), 'name');
        document.getElementById('obj-location').value = loc.id;
        document.getElementById('new-location').value = '';
        document.getElementById('new-location-type').value = 'Standort';
        document.getElementById('add-location-box').classList.add('hidden');
    } catch (e) { alert('Fehler: ' + e.message); }
}

// === Dashboard ===
async function loadDashboardAlerts() {
    if (currentUser.role === 'standard') return;
    document.getElementById('maintenance-alerts').innerHTML = '';
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
    document.getElementById('search-results').innerHTML = '';
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
function startQrScan() {
    showView('scanner');
    if (!window.Html5Qrcode) {
        alert('QR-Scanner wird geladen... bitte Seite neu laden.');
        return;
    }
    scanner = new Html5Qrcode('qr-reader');
    scanner.start(
        { facingMode: 'environment' },
        { fps: 10, qrbox: { width: 250, height: 250 } },
        (decodedText) => {
            stopQrScan();
            handleQrResult(decodedText);
        },
        () => {}
    ).catch(err => alert('Kamera-Fehler: ' + err));
}

function stopQrScan() {
    if (scanner) { scanner.stop().catch(() => {}); scanner = null; }
    showView('search');
}

function handleQrResult(text) {
    const match = text.match(/FFW-\d+/);
    if (match) {
        document.getElementById('search-input').value = match[0];
        applyFilters();
    } else {
        document.getElementById('search-input').value = text;
        applyFilters();
    }
}

// === Object Detail ===
async function openObject(id) {
    try {
        const obj = await api('/api/objects/' + id);
        renderObjectDetail(obj);
        showView('detail');
    } catch (e) { alert('Fehler: ' + e.message); }
}

function renderObjectDetail(obj) {
    const isStandard = currentUser.role === 'standard';
    const isFull = !isStandard;

    // Infobox
    let infoboxHtml = `
        <h3>${escapeHtml(obj.designation)}</h3>
        ${obj.title_image ? `<img src="/uploads/images/${obj.title_image}" alt="Titelbild">` : ''}
        <table>
            <tr><td>ID</td><td><strong>${obj.object_number}</strong></td></tr>
            <tr><td>Typ</td><td>${obj.object_type ? obj.object_type.name : '-'}</td></tr>
            <tr><td>Hersteller</td><td>${obj.manufacturer ? obj.manufacturer.name : '-'}</td></tr>
            <tr><td>Unterbringung</td><td>${obj.location ? `<a href="#" onclick="event.preventDefault(); showObjectsByLocation(${obj.location.id}, '${escapeHtml(obj.location.name)}')">${escapeHtml(obj.location.name)}</a>` : '-'}</td></tr>
            ${isFull ? `<tr><td>Seriennummer</td><td>${escapeHtml(obj.serial_number || '-')}</td></tr>` : ''}
            ${isFull ? `<tr><td>Anschaffung</td><td>${obj.acquisition_date || '-'}</td></tr>` : ''}
            <tr><td>Status</td><td><span class="badge badge-${obj.status}">${formatStatus(obj.status)}</span></td></tr>
        </table>
        ${obj.qr_code ? `<div style="text-align:center;margin-top:1rem;"><img src="/uploads/qrcodes/${obj.qr_code.filename}" style="width:120px;"><br><small>${obj.object_number}</small></div>` : ''}
        ${isFull ? `
            <div style="margin-top:1rem;text-align:center;">
                <a href="/api/objects/${obj.id}/sticker/print" target="_blank" class="btn-primary btn-small">🖨️ Aufkleber</a>
            </div>
        ` : ''}
    `;
    document.getElementById('detail-infobox').innerHTML = infoboxHtml;

    // Content
    let contentHtml = `
        <div class="wiki-actions">
            <button class="btn-secondary btn-small" onclick="showView('search')">← Zurück</button>
            ${isFull ? `<button class="btn-primary btn-small" onclick="editObject(${obj.id})">✏️ Bearbeiten</button>` : ''}
        </div>
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
        contentHtml += docs.map(d => `<a href="/uploads/documents/${d.filename}" target="_blank">📄 ${escapeHtml(d.original_name)}</a>`).join('');
        contentHtml += `</div>`;
    }

    // Upload-Bereich für berechtigte Nutzer
    if (isFull) {
        contentHtml += `
            <h2>Dokumente hochladen</h2>
            <input type="file" id="detail-doc-upload" multiple accept=".pdf,.txt,.md,image/*" onchange="uploadDetailDocs(${obj.id})">
            <small>PDF, Bilder, Textdateien – werden sofort hochgeladen</small>
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

        if (obj.maintenances && obj.maintenances.length) {
            contentHtml += `<h2>Wartung</h2>`;
            obj.maintenances.forEach(m => {
                const daysLeft = m.next_maintenance_date ? daysUntil(m.next_maintenance_date) : null;
                contentHtml += `
                    <div class="alert ${daysLeft !== null && daysLeft < 0 ? 'alert-danger' : ''}">
                        <strong>Intervall:</strong> ${m.interval_days} Tage<br>
                        <strong>Letzte Wartung:</strong> ${m.last_maintenance_date || '-'}<br>
                        <strong>Nächste Wartung:</strong> ${m.next_maintenance_date || '-'}
                        ${daysLeft !== null ? `<br><strong>Restzeit:</strong> ${daysLeft < 0 ? 'Überfällig!' : daysLeft + ' Tage'}` : ''}
                        ${m.notes ? '<br>' + escapeHtml(m.notes) : ''}
                    </div>
                `;
            });
        }

        if (obj.repairs && obj.repairs.length) {
            contentHtml += `<h2>Reparaturverlauf</h2><table><thead><tr><th>Datum</th><th>Beschreibung</th><th>Kosten</th></tr></thead><tbody>`;
            contentHtml += obj.repairs.map(r => `
                <tr><td>${r.date}</td><td>${escapeHtml(r.description)}</td><td>${r.cost ? r.cost.toFixed(2) + ' €' : '-'}</td></tr>
            `).join('');
            contentHtml += `</tbody></table>`;
        }

        // Prüfungen
        contentHtml += `<h2>Prüfungen</h2>`;
        if (isFull) {
            contentHtml += `<button class="btn-primary btn-small" onclick="openInspectionModal(${obj.id})">+ Neue Prüfung</button>`;
        }
        if (obj.inspections && obj.inspections.length) {
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
                
                contentHtml += `
                    <div class="alert" style="margin-bottom:0.5rem;">
                        <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:0.5rem;">
                            <div>
                                <strong>${i.template_name || 'Prüfung'}</strong> ${statusBadge}<br>
                                <small>📅 ${new Date(i.inspected_at).toLocaleDateString('de-DE')} | 👤 ${i.inspected_by_name || '-'}</small>
                            </div>
                            <button class="btn-primary btn-small" onclick="viewInspection(${i.id}, '${escapeHtml(i.template_name || 'Prüfung')}', '${i.inspected_at}', '${i.inspected_by_name || '-'}')">👁️ Ansehen</button>
                        </div>
                        ${i.next_inspection_date ? `<small style="display:block; margin-top:0.3rem;">Nächste Prüfung: ${i.next_inspection_date}</small>` : ''}
                    </div>
                `;
            });
            contentHtml += `</div>`;
        } else {
            contentHtml += `<p>Keine Prüfungen vorhanden.</p>`;
        }
    }

    document.getElementById('detail-content').innerHTML = contentHtml;
}

async function uploadDetailDocs(objectId) {
    const input = document.getElementById('detail-doc-upload');
    if (!input.files.length) return;
    for (const file of input.files) {
        const fd = new FormData();
        fd.append('file', file);
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
async function saveObject(e) {
    e.preventDefault();
    const id = document.getElementById('edit-object-id').value;
    const data = {
        object_type_id: parseInt(document.getElementById('obj-type').value) || null,
        designation: document.getElementById('obj-designation').value,
        serial_number: document.getElementById('obj-serial').value || null,
        manufacturer_id: parseInt(document.getElementById('obj-manufacturer').value) || null,
        location_id: parseInt(document.getElementById('obj-location').value) || null,
        info_text: document.getElementById('obj-info').value || null,
        usage_hints: document.getElementById('obj-hints').value || null,
        acquisition_date: document.getElementById('obj-acquisition').value || null,
        status: document.getElementById('obj-status').value,
        maintenance_interval_days: parseInt(document.getElementById('obj-maint-days').value) || null,
        maintenance_notes: document.getElementById('obj-maint-notes').value || null
    };

    // Neuer Hersteller?
    const newManu = document.getElementById('new-manufacturer').value.trim();
    if (newManu && !data.manufacturer_id) {
        try {
            const m = await api('/api/manufacturers', { method: 'POST', body: JSON.stringify({ name: newManu }) });
            data.manufacturer_id = m.id;
            masterData.manufacturers.push(m);
            fillSelect('obj-manufacturer', masterData.manufacturers, 'name');
            document.getElementById('obj-manufacturer').value = m.id;
        } catch (e) { alert('Hersteller konnte nicht angelegt werden: ' + e.message); return; }
    }

    // Neuer Standort?
    const newLoc = document.getElementById('new-location').value.trim();
    const newLocType = document.getElementById('new-location-type').value.trim();
    if (newLoc && !data.location_id) {
        try {
            const loc = await api('/api/locations', { method: 'POST', body: JSON.stringify({ name: newLoc, location_type: newLocType || 'Standort' }) });
            data.location_id = loc.id;
            // Locations neu laden
            masterData.locations = await api('/api/locations');
            fillSelect('obj-location', flattenLocations(masterData.locations), 'name');
            document.getElementById('obj-location').value = loc.id;
        } catch (e) { alert('Standort konnte nicht angelegt werden: ' + e.message); return; }
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
                fd.append('is_public', 'true');
                await uploadFile('/api/objects/' + obj.id + '/documents', fd);
            }
        }

        // Fahrzeug auch als Standort anlegen?
        const vehicleAsLoc = document.getElementById('obj-vehicle-as-location').checked;
        const selectedType = masterData.types.find(t => t.id == data.object_type_id);
        if (!id && vehicleAsLoc && selectedType && selectedType.name === 'Fahrzeug') {
            try {
                await api('/api/locations', {
                    method: 'POST',
                    body: JSON.stringify({ name: obj.designation, location_type: 'Fahrzeug', parent_id: data.location_id || null })
                });
                masterData.locations = await api('/api/locations');
            } catch (e) { console.warn('Standort konnte nicht angelegt werden:', e); }
        }

        alert('Gespeichert!');
        // Formular zurücksetzen
        document.getElementById('object-form').reset();
        document.getElementById('edit-object-id').value = '';
        document.getElementById('new-manufacturer').value = '';
        document.getElementById('new-location').value = '';
        document.getElementById('new-location-type').value = '';
        document.getElementById('vehicle-location-box').classList.add('hidden');
        document.getElementById('obj-vehicle-as-location').checked = false;
        document.getElementById('add-manufacturer-box').classList.add('hidden');
        document.getElementById('add-location-box').classList.add('hidden');

        showView('search');
        document.getElementById('search-input').value = obj.object_number;
        applyFilters();
    } catch (e) { alert('Fehler: ' + e.message); }
}

async function showObjectsByLocation(locationId, locationName) {
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
        showView('location-objects');
    } catch (e) { alert('Fehler: ' + e.message); }
}

async function editObject(id) {
    try {
        const obj = await api('/api/objects/' + id);
        await loadMasterData(); // Stellt sicher, dass alle Dropdowns aktuell sind

        document.getElementById('edit-object-id').value = obj.id;
        document.getElementById('obj-designation').value = obj.designation;
        document.getElementById('obj-type').value = obj.object_type ? obj.object_type.id : '';
        document.getElementById('obj-serial').value = obj.serial_number || '';
        document.getElementById('obj-manufacturer').value = obj.manufacturer ? obj.manufacturer.id : '';
        document.getElementById('obj-location').value = obj.location ? obj.location.id : '';
        document.getElementById('obj-status').value = obj.status;
        document.getElementById('obj-acquisition').value = obj.acquisition_date || '';
        document.getElementById('obj-info').value = obj.info_text || '';
        document.getElementById('obj-hints').value = obj.usage_hints || '';
        document.getElementById('new-manufacturer').value = '';
        document.getElementById('new-location').value = '';
        document.getElementById('new-location-type').value = '';
        document.getElementById('add-manufacturer-box').classList.add('hidden');
        document.getElementById('add-location-box').classList.add('hidden');
        document.getElementById('obj-vehicle-as-location').checked = false;
        // Trigger type change to show/hide vehicle-location-box
        const typeSel = document.getElementById('obj-type');
        if (typeSel && typeSel.onchange) typeSel.onchange();

        if (obj.maintenances && obj.maintenances[0]) {
            document.getElementById('obj-maint-days').value = obj.maintenances[0].interval_days;
            document.getElementById('obj-maint-notes').value = obj.maintenances[0].notes || '';
        } else {
            document.getElementById('obj-maint-days').value = '';
            document.getElementById('obj-maint-notes').value = '';
        }

        document.getElementById('form-title').textContent = 'Objekt bearbeiten';
        showView('edit-object');
    } catch (e) { alert('Fehler: ' + e.message); }
}

// === Admin ===
function showAdminTab(tab) {
    document.querySelectorAll('.admin-tab').forEach(t => t.classList.remove('active'));
    event.target.classList.add('active');
    document.getElementById('admin-users').classList.toggle('hidden', tab !== 'users');
    document.getElementById('admin-masterdata').classList.toggle('hidden', tab !== 'masterdata');
    document.getElementById('admin-inspections').classList.toggle('hidden', tab !== 'inspections');
    if (tab === 'users') loadUsers();
    if (tab === 'masterdata') loadMasterDataLists();
    if (tab === 'inspections') loadInspectionTemplatesList();
}

async function loadUsers() {
    try {
        const users = await api('/api/users');
        document.getElementById('users-list').innerHTML = `
            <table><thead><tr><th>Name</th><th>Benutzer</th><th>Rolle</th><th>Aktiv</th><th>Aktionen</th></tr></thead>
            <tbody>${users.map(u => `
                <tr>
                    <td>${escapeHtml(u.full_name)}</td>
                    <td>${escapeHtml(u.username)}</td>
                    <td>${u.role}</td>
                    <td>${u.is_active ? 'Ja' : 'Nein'}</td>
                    <td>
                        <button class="btn-primary btn-small" onclick="editUserPrompt(${u.id}, '${u.username}', '${u.full_name}', '${u.email}', '${u.role}')">Bearbeiten</button>
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

function showUserForm() {
    const username = prompt('Benutzername:');
    if (!username) return;
    const fullName = prompt('Vollständiger Name:');
    const password = prompt('Passwort:');
    const role = prompt('Rolle (standard/erweitert/verwaltung/admin):', 'standard');
    api('/api/users', {
        method: 'POST',
        body: JSON.stringify({ username, full_name: fullName, password, role, is_active: true })
    }).then(() => loadUsers()).catch(e => alert(e.message));
}

function editUserPrompt(id, username, fullName, email, role) {
    const newName = prompt('Name:', fullName);
    const newRole = prompt('Rolle:', role);
    const newPass = prompt('Neues Passwort (leer = unverändert):');
    const data = { full_name: newName, role: newRole };
    if (newPass) data.password = newPass;
    api('/api/users/' + id, { method: 'PUT', body: JSON.stringify(data) })
        .then(() => loadUsers()).catch(e => alert(e.message));
}

async function loadMasterDataLists() {
    const manus = await api('/api/manufacturers');
    document.getElementById('manufacturers-list').innerHTML = manus.map(m => `
        <span class="badge badge-reserve" style="margin:0.2rem;display:inline-block">${escapeHtml(m.name)}</span>
    `).join('') || '<p>Keine Hersteller</p>';

    const locs = await api('/api/locations');
    document.getElementById('locations-list').innerHTML = renderLocationTree(locs);
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

async function loadInspectionTemplatesList() {
    try {
        const templates = await api('/api/inspection-templates');
        document.getElementById('inspection-templates-list').innerHTML = `
            <table><thead><tr><th>Name</th><th>Beschreibung</th><th>Kategorie</th><th>Felder</th><th>Aktionen</th></tr></thead>
            <tbody>${templates.map(t => {
                let fields = [];
                try { fields = JSON.parse(t.fields); } catch(e) {}
                return `
                <tr>
                    <td>${escapeHtml(t.name)}</td>
                    <td>${escapeHtml(t.description || '-')}</td>
                    <td>${t.object_type_id ? (masterData.types.find(ty => ty.id == t.object_type_id)?.name || '-') : 'Alle'}</td>
                    <td>${fields.length} Felder</td>
                    <td>
                        <button class="btn-primary btn-small" onclick="editInspectionTemplate(${t.id})">Bearbeiten</button>
                        <button class="btn-primary btn-small btn-delete" onclick="deleteInspectionTemplate(${t.id})">Löschen</button>
                    </td>
                </tr>
                `;
            }).join('')}</tbody></table>
        `;
    } catch (e) { console.error(e); }
}

function showInspectionTemplateForm() {
    templateEditId = null;
    document.getElementById('inspection-template-form-box').classList.remove('hidden');
    fillSelect('tmpl-type', masterData.types, 'name');
    document.getElementById('tmpl-fields-list').innerHTML = '';
    document.getElementById('tmpl-name').value = '';
    document.getElementById('tmpl-desc').value = '';
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
        object_type_id: document.getElementById('tmpl-type').value ? parseInt(document.getElementById('tmpl-type').value) : null
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

async function openInspectionModal(objectId) {
    document.getElementById('inspection-object-id').value = objectId;
    document.getElementById('inspection-modal').style.display = 'block';
    document.getElementById('inspection-fields').innerHTML = '';
    document.getElementById('inspection-next-date').value = '';
    document.getElementById('inspection-notes').value = '';

    try {
        inspectionTemplates = await api('/api/inspection-templates');
        const sel = document.getElementById('inspection-template');
        sel.innerHTML = '<option value="">-- Prüfkarte wählen --</option>';
        inspectionTemplates.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.id;
            opt.textContent = t.name;
            sel.appendChild(opt);
        });
    } catch (e) { alert('Fehler beim Laden der Prüfkarten: ' + e.message); }
}

function closeInspectionModal() {
    document.getElementById('inspection-modal').style.display = 'none';
}

function loadInspectionTemplate() {
    const templateId = document.getElementById('inspection-template').value;
    const container = document.getElementById('inspection-fields');
    if (!templateId) { container.innerHTML = ''; return; }

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
}

async function saveInspection(e) {
    e.preventDefault();
    const objectId = document.getElementById('inspection-object-id').value;
    const templateId = document.getElementById('inspection-template').value;
    if (!templateId) return alert('Bitte eine Prüfkarte auswählen');

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
        results: results,
        next_inspection_date: document.getElementById('inspection-next-date').value || null,
        notes: document.getElementById('inspection-notes').value || null
    };

    try {
        await api('/api/objects/' + objectId + '/inspections', {
            method: 'POST',
            body: JSON.stringify(data)
        });
        closeInspectionModal();
        alert('Prüfung gespeichert!');
        openObject(parseInt(objectId));
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
async function viewInspection(inspectionId, templateName, inspectedAt, inspectedBy) {
    try {
        const i = await api('/api/inspections/' + inspectionId);
        let results = {};
        try { results = JSON.parse(i.results); } catch(e) {}
        
        document.getElementById('view-inspection-title').textContent = templateName || 'Prüfung';
        
        let html = `
            <div style="margin-bottom:1rem; padding:0.8rem; background:#f5f5f5; border-radius:6px;">
                <strong>📅 Prüfdatum:</strong> ${new Date(inspectedAt).toLocaleDateString('de-DE')}<br>
                <strong>👤 Prüfer:</strong> ${escapeHtml(inspectedBy)}<br>
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
    if (event.target === modal1) {
        closeInspectionModal();
    }
    if (event.target === modal2) {
        closeViewInspectionModal();
    }
};

// === Init ===
if (token) {
    initApp();
}
