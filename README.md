# Feuerwehr Datenbank

Eine einfache, aber leistungsfähige Web-Anwendung zur Verwaltung von Feuerwehr-Mitgliedern, Fahrzeugen und Einsätzen.

## Funktionen

- **Mitgliederverwaltung**: Verwalte alle Feuerwehrmitglieder mit Dienstnummer, Funktion, Kontaktdaten und Status.
- **Fahrzeugverwaltung**: Behälte den Überblick über alle Fahrzeuge, deren Status und Inspektionstermine.
- **Einsatzverwaltung**: Erfasse und verwalte Einsätze mit Stichwort, Adresse und Status.
- **Responsives Design**: Funktioniert auf Desktop, Tablet und Smartphone.
- **REST API**: Alle Daten sind über eine moderne API erreichbar (`/docs` für automatische Dokumentation).

## Technologien

- **Backend**: Python, FastAPI, SQLAlchemy, SQLite
- **Frontend**: HTML5, CSS3, Vanilla JavaScript
- **Container**: Docker, Docker Compose

## Lokale Entwicklung

### Ohne Docker

```bash
# Virtuelle Umgebung erstellen (empfohlen)
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Abhängigkeiten installieren
pip install -r requirements.txt

# Server starten
uvicorn app.main:app --reload
```

Die App ist dann unter `http://localhost:8000` erreichbar.
Die API-Dokumentation findest du unter `http://localhost:8000/docs`.

### Mit Docker

```bash
# Container bauen und starten
docker-compose up --build -d

# Logs ansehen
docker-compose logs -f

# Container stoppen
docker-compose down
```

## Deployment auf einem VPS

### 1. GitHub Repository erstellen

1. Erstelle ein neues Repository auf GitHub (z.B. `feuerwehr-datenbank`).
2. Verbinde dein lokales Repository:

```bash
git remote add origin https://github.com/DEIN_USERNAME/feuerwehr-datenbank.git
git branch -M main
git push -u origin main
```

**Alternative mit GitHub Desktop**: Öffne den Ordner in GitHub Desktop und veröffentliche das Repository.

### 2. Auf dem VPS deployn

Verbinde dich per SSH mit deinem VPS:

```bash
ssh benutzer@dein-vps.de
```

Dann führe aus:

```bash
# Repository klonen
cd /opt
git clone https://github.com/DEIN_USERNAME/feuerwehr-datenbank.git
cd feuerwehr-datenbank

# Docker Compose starten
docker-compose up --build -d
```

### 3. Updates einspielen

Wenn du Änderungen lokal machst und zu GitHub pushst:

```bash
# Auf dem VPS:
cd /opt/feuerwehr-datenbank
git pull
docker-compose up --build -d
```

### 4. Reverse Proxy (empfohlen)

Für den Produktivbetrieb solltest du einen Reverse Proxy wie **Nginx** oder **Traefik** verwenden, um HTTPS zu ermöglichen.

#### Mit Nginx (Beispiel)

```nginx
server {
    listen 80;
    server_name feuerwehr.dein-domain.de;
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Projektstruktur

```
.
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI App & Endpunkte
│   ├── database.py      # Datenbank-Modelle & Verbindung
│   └── static/          # Frontend Dateien
│       ├── index.html
│       ├── css/
│       │   └── style.css
│       └── js/
│           └── app.js
├── data/                # SQLite Datenbank (Docker Volume)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Datenbank

Standardmäßig wird SQLite verwendet. Die Datenbankdatei wird im `data/`-Verzeichnis gespeichert und ist durch ein Docker-Volume persistiert.

Für größere Installationen kannst du leicht auf PostgreSQL umstellen, indem du die `DATABASE_URL` Umgebungsvariable anpasst.

## Lizenz

MIT
