// API Base URL
const API_URL = '';

// Aktuelle Daten
let currentData = {
    mitglieder: [],
    fahrzeuge: [],
    einsaetze: []
};

// Formular-Konfiguration
const formConfig = {
    mitglied: {
        title: 'Mitglied',
        fields: [
            { name: 'dienstnummer', label: 'Dienstnummer', type: 'text', required: true },
            { name: 'vorname', label: 'Vorname', type: 'text', required: true },
            { name: 'nachname', label: 'Nachname', type: 'text', required: true },
            { name: 'geburtsdatum', label: 'Geburtsdatum', type: 'date', required: false },
            { name: 'eintrittsdatum', label: 'Eintrittsdatum', type: 'date', required: false },
            { name: 'funktion', label: 'Funktion', type: 'text', required: false, placeholder: 'z.B. Kommandant, Maschinist' },
            { name: 'status', label: 'Status', type: 'select', options: ['aktiv', 'inaktiv', 'ehrenmitglied'], required: false },
            { name: 'telefon', label: 'Telefon', type: 'tel', required: false },
            { name: 'email', label: 'E-Mail', type: 'email', required: false },
            { name: 'adresse', label: 'Adresse', type: 'textarea', required: false },
            { name: 'notizen', label: 'Notizen', type: 'textarea', required: false }
        ]
    },
    fahrzeug: {
        title: 'Fahrzeug',
        fields: [
            { name: 'kennzeichen', label: 'Kennzeichen', type: 'text', required: true },
            { name: 'bezeichnung', label: 'Bezeichnung', type: 'text', required: true, placeholder: 'z.B. RLF-A 2000' },
            { name: 'marke', label: 'Marke', type: 'text', required: false },
            { name: 'typ', label: 'Typ', type: 'text', required: false },
            { name: 'baujahr', label: 'Baujahr', type: 'number', required: false },
            { name: 'sitzplaetze', label: 'Sitzplätze', type: 'number', required: false },
            { name: 'status', label: 'Status', type: 'select', options: ['einsatzbereit', 'werkstatt', 'außer dienst'], required: false },
            { name: 'letzte_inspektion', label: 'Letzte Inspektion', type: 'date', required: false },
            { name: 'naechste_inspektion', label: 'Nächste Inspektion', type: 'date', required: false },
            { name: 'notizen', label: 'Notizen', type: 'textarea', required: false }
        ]
    },
    einsatz: {
        title: 'Einsatz',
        fields: [
            { name: 'einsatznummer', label: 'Einsatznummer', type: 'text', required: true },
            { name: 'stichwort', label: 'Stichwort', type: 'text', required: true, placeholder: 'z.B. B1, TH1' },
            { name: 'beschreibung', label: 'Beschreibung', type: 'textarea', required: false },
            { name: 'adresse', label: 'Adresse', type: 'text', required: true },
            { name: 'ort', label: 'Ort', type: 'text', required: false },
            { name: 'melder', label: 'Melder', type: 'text', required: false },
            { name: 'status', label: 'Status', type: 'select', options: ['offen', 'abgeschlossen'], required: false }
        ]
    }
};

// Tabellenspalten-Konfiguration
const tableColumns = {
    mitglieder: [
        { key: 'dienstnummer', label: 'Dienstnr.' },
        { key: 'nachname', label: 'Name', format: (m) => `${m.vorname} ${m.nachname}` },
        { key: 'funktion', label: 'Funktion' },
        { key: 'status', label: 'Status', class: (v) => `status-${v}` },
        { key: 'telefon', label: 'Telefon' }
    ],
    fahrzeuge: [
        { key: 'kennzeichen', label: 'Kennzeichen' },
        { key: 'bezeichnung', label: 'Bezeichnung' },
        { key: 'status', label: 'Status', class: (v) => `status-${v.replace(' ', '-')}` },
        { key: 'naechste_inspektion', label: 'Nächste Inspektion' }
    ],
    einsaetze: [
        { key: 'einsatznummer', label: 'Nr.' },
        { key: 'alarmierung', label: 'Alarmierung', format: (e) => e.alarmierung ? new Date(e.alarmierung).toLocaleString('de-DE') : '-' },
        { key: 'stichwort', label: 'Stichwort' },
        { key: 'adresse', label: 'Adresse' },
        { key: 'status', label: 'Status', class: (v) => `status-${v}` }
    ]
};

// --- Initialisierung ---
document.addEventListener('DOMContentLoaded', () => {
    // Tab-Navigation
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    // Daten laden
    loadAllData();
});

// --- Tabs ---
function switchTab(tabName) {
    document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
    
    document.querySelector(`.nav-btn[data-tab="${tabName}"]`).classList.add('active');
    document.getElementById(tabName).classList.add('active');
}

// --- Daten laden ---
async function loadAllData() {
    await Promise.all([
        loadData('mitglieder'),
        loadData('fahrzeuge'),
        loadData('einsaetze')
    ]);
}

async function loadData(type) {
    try {
        const response = await fetch(`${API_URL}/api/${type}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        currentData[type] = await response.json();
        renderTable(type);
    } catch (error) {
        console.error(`Fehler beim Laden von ${type}:`, error);
        alert(`Fehler beim Laden der ${type}. Ist der Server erreichbar?`);
    }
}

// --- Tabellen rendern ---
function renderTable(type) {
    const tbody = document.querySelector(`#table-${type} tbody`);
    const data = currentData[type];
    const columns = tableColumns[type];

    tbody.innerHTML = data.map(item => {
        const cells = columns.map(col => {
            let value = col.format ? col.format(item) : (item[col.key] || '-');
            const cssClass = col.class ? col.class(item[col.key]) : '';
            return `<td data-label="${col.label}"><span class="${cssClass}">${value}</span></td>`;
        }).join('');

        return `
            <tr>
                ${cells}
                <td data-label="Aktionen">
                    <button class="btn-primary btn-small btn-edit" onclick="editItem('${type}', ${item.id})">Bearbeiten</button>
                    <button class="btn-primary btn-small btn-delete" onclick="deleteItem('${type}', ${item.id})">Löschen</button>
                </td>
            </tr>
        `;
    }).join('');

    if (data.length === 0) {
        tbody.innerHTML = `<tr><td colspan="${columns.length + 1}" style="text-align:center;padding:2rem;">Keine Einträge vorhanden</td></tr>`;
    }
}

// --- Suche / Filter ---
function filterTable(type) {
    const searchTerm = document.getElementById(`search-${type}`).value.toLowerCase();
    const rows = document.querySelectorAll(`#table-${type} tbody tr`);
    
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(searchTerm) ? '' : 'none';
    });
}

// --- Modal & Formular ---
function openModal(type, editId = null) {
    const config = formConfig[type];
    const modal = document.getElementById('modal');
    const title = document.getElementById('modal-title');
    const formFields = document.getElementById('form-fields');
    const editIdField = document.getElementById('edit-id');
    const editTypeField = document.getElementById('edit-type');

    title.textContent = editId ? `${config.title} bearbeiten` : `${config.title} hinzufügen`;
    editIdField.value = editId || '';
    editTypeField.value = type;

    let fieldsHtml = '';
    
    // Falls Bearbeiten: Daten laden
    let itemData = {};
    if (editId) {
        const pluralType = type === 'mitglied' ? 'mitglieder' : type === 'fahrzeug' ? 'fahrzeuge' : 'einsaetze';
        itemData = currentData[pluralType].find(i => i.id === editId) || {};
    }

    config.fields.forEach(field => {
        const value = itemData[field.name] || '';
        
        if (field.type === 'select') {
            const options = field.options.map(opt => 
                `<option value="${opt}" ${value === opt ? 'selected' : ''}>${opt}</option>`
            ).join('');
            
            fieldsHtml += `
                <label for="${field.name}">${field.label}${field.required ? ' *' : ''}</label>
                <select name="${field.name}" id="${field.name}" ${field.required ? 'required' : ''}>
                    ${options}
                </select>
            `;
        } else if (field.type === 'textarea') {
            fieldsHtml += `
                <label for="${field.name}">${field.label}${field.required ? ' *' : ''}</label>
                <textarea name="${field.name}" id="${field.name}" ${field.required ? 'required' : ''} placeholder="${field.placeholder || ''}">${value}</textarea>
            `;
        } else {
            fieldsHtml += `
                <label for="${field.name}">${field.label}${field.required ? ' *' : ''}</label>
                <input type="${field.type}" name="${field.name}" id="${field.name}" value="${value}" ${field.required ? 'required' : ''} placeholder="${field.placeholder || ''}">
            `;
        }
    });

    formFields.innerHTML = fieldsHtml;
    modal.style.display = 'block';
}

function closeModal() {
    document.getElementById('modal').style.display = 'none';
}

// Schließen beim Klick außerhalb
window.onclick = function(event) {
    const modal = document.getElementById('modal');
    if (event.target === modal) {
        closeModal();
    }
};

// --- Speichern ---
async function saveForm(event) {
    event.preventDefault();
    
    const editId = document.getElementById('edit-id').value;
    const type = document.getElementById('edit-type').value;
    const pluralType = type === 'mitglied' ? 'mitglieder' : type === 'fahrzeug' ? 'fahrzeuge' : 'einsaetze';
    
    const formData = new FormData(event.target);
    const data = {};
    
    formConfig[type].fields.forEach(field => {
        let value = formData.get(field.name);
        if (field.type === 'number' && value) {
            value = parseInt(value);
        }
        data[field.name] = value;
    });

    const url = editId 
        ? `${API_URL}/api/${pluralType}/${editId}` 
        : `${API_URL}/api/${pluralType}`;
    
    const method = editId ? 'PUT' : 'POST';

    try {
        const response = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Unbekannter Fehler');
        }

        closeModal();
        await loadData(pluralType);
    } catch (error) {
        console.error('Fehler beim Speichern:', error);
        alert(`Fehler beim Speichern: ${error.message}`);
    }
}

// --- Bearbeiten ---
function editItem(type, id) {
    openModal(type.slice(0, -1), id); // "mitglieder" -> "mitglied"
}

// --- Löschen ---
async function deleteItem(type, id) {
    if (!confirm('Möchten Sie diesen Eintrag wirklich löschen?')) return;

    try {
        const response = await fetch(`${API_URL}/api/${type}/${id}`, {
            method: 'DELETE'
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        await loadData(type);
    } catch (error) {
        console.error('Fehler beim Löschen:', error);
        alert('Fehler beim Löschen des Eintrags.');
    }
}
