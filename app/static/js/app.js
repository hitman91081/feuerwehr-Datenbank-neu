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

// === Dashboard ===
async function loadDashboardAlerts() {
    if (currentUser.role === 'standard') return;
    document.getElementById('maintenance-alerts').innerHTML = '';
}

// === Search ===
let searchTimeout;
function debouncedSearch() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(doSearch, 300);
}

async function doSearch() {
    const q = document.getElementById('search-input').value.trim();
    if (!q) { document.getElementById('search-results').innerHTML = ''; return; }
    try {
        const results = await api('/api/objects/search?q=' + encodeURIComponent(q));
        renderSearchResults(results);
    } catch (e) { console.error(e); }
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
        doSearch();
    } else {
        document.getElementById('search-input').value = text;
        doSearch();
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
            <tr><td>Unterbringung</td><td>${obj.location ? escapeHtml(obj.location.name) : '-'}</td></tr>
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

        alert('Gespeichert!');
        // Formular zurücksetzen
        document.getElementById('object-form').reset();
        document.getElementById('edit-object-id').value = '';
        document.getElementById('new-manufacturer').value = '';
        document.getElementById('new-location').value = '';
        document.getElementById('new-location-type').value = '';

        showView('search');
        document.getElementById('search-input').value = obj.object_number;
        doSearch();
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
    if (tab === 'users') loadUsers();
    if (tab === 'masterdata') loadMasterDataLists();
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

// === Init ===
if (token) {
    initApp();
}
