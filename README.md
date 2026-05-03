# Feuerwehr Inventarverwaltung

Moderne Web-Anwendung zur Verwaltung von Feuerwehr-Equipment, Fahrzeugen und Ausrüstung mit QR-Code-Unterstützung.

## Funktionen

- **Benutzerverwaltung** mit 4 Rollen: Standardnutzer, Erweiterter Nutzer, Verwaltung, Admin
- **Objektverwaltung**: Fahrzeuge, Gebrauchsgegenstände, Verbrauchsgegenstände, Ausrüstung
- **Automatische ID- & QR-Code-Generierung** beim Anlegen
- **Hierarchische Unterbringung** (z.B. Fahrzeug → Raum → Platz)
- **Wartungsmanagement** mit Restzeit-Anzeige
- **Reparaturverlauf** pro Objekt
- **Dokumentenmanagement** (PDF, Bilder) mit Sichtbarkeitssteuerung
- **Druckbare QR-Aufkleber**
- **QR-Code Scanner** direkt im Browser (Smartphone-Kamera)
- **Wikipedia-ähnliche Detailansicht** für einfache Bedienung
- **Responsive Design** für Desktop, Tablet und Smartphone

## Technologien

- **Backend**: Python, FastAPI, SQLAlchemy, SQLite
- **Auth**: JWT-Token, bcrypt
- **Frontend**: Vanilla JS, HTML5, CSS3
- **QR-Codes**: `qrcode` Bibliothek mit Pillow
- **Container**: Docker, Docker Compose

## Schnellstart (lokal)

### 1. Abhängigkeiten installieren

```bash
cd "Feuerwehr Datenbank"
pip3 install -r requirements.txt
```

### 2. Server starten

```bash
python3 -m uvicorn app.main:app --reload
```

### 3. App öffnen

Im Browser: [http://localhost:8000](http://localhost:8000)

**Standard-Login**: `admin` / `admin`

### 4. API-Dokumentation

[http://localhost:8000/docs](http://localhost:8000/docs)

## Benutzerrollen & Rechte

| Rolle | Objekte ansehen | Objekte bearbeiten | Benutzer verwalten |
|-------|-----------------|--------------------|--------------------|
| Standardnutzer | Ja (nur öffentl. Felder) | Nein | Nein |
| Erweiterter Nutzer | Ja | Ja | Nein |
| Verwaltung | Ja | Ja | Nein |
| Admin | Ja | Ja | Ja |

## Docker (VPS)

```bash
docker-compose up --build -d
```

> **Wichtig**: Passe die `BASE_URL` Umgebungsvariable in der `docker-compose.yml` an deine Domain an, damit die QR-Codes korrekt funktionieren!

## GitHub

```bash
git remote add origin https://github.com/DEIN_USERNAME/feuerwehr-inventar.git
git branch -M main
git push -u origin main
```

## Projektstruktur

```
.
├── app/
│   ├── main.py          # API Endpunkte
│   ├── models.py        # Datenbank-Modelle
│   ├── schemas.py       # Pydantic-Schemas
│   ├── auth.py          # Authentifizierung
│   ├── database.py      # DB-Verbindung
│   └── static/          # Frontend
├── uploads/             # Bilder, Dokumente, QR-Codes
├── data/                # SQLite-Datenbank
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Hinweise

- Der Default-Admin wird beim ersten Start automatisch erstellt.
- Ändere das Standard-Passwort sofort nach dem ersten Login!
- Die SQLite-Datenbank wird im `data/`-Ordner persistiert.
- Für den Produktivbetrieb solltest du `SECRET_KEY` und `BASE_URL` als Umgebungsvariablen setzen.
