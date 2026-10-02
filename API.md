# Externe Inventar-API (v1)

Die erste API-Version unterstützt das Lesen und Anlegen von Inventarobjekten. Prüfungen und Meldungen sind bewusst noch nicht für externe Schreibzugriffe freigegeben.

## API-Schlüssel

Ein Administrator erstellt Schlüssel in **Verwaltung → API**. Der vollständige Schlüssel wird nur direkt nach dem Erstellen angezeigt und anschließend ausschließlich gehasht gespeichert.

Der Schlüssel wird bei jedem Aufruf im Header übertragen:

```http
X-API-Key: fwi_...
```

Es gibt zwei getrennte Berechtigungen:

- `objects:read`: Stammdaten und Objekte lesen
- `objects:write`: Objekte anlegen

## Stammdaten abfragen

```bash
curl -H "X-API-Key: fwi_..." \
  https://inventar.example.de/api/v1/meta
```

Die Antwort enthält gültige Kategorien, Hersteller, Lieferanten, vollständige Standortpfade und Statuswerte.

## Objekte suchen

```bash
curl -H "X-API-Key: fwi_..." \
  "https://inventar.example.de/api/v1/objects?q=Schlauch&limit=50&offset=0"
```

Optionale Filter:

- `q`: Bezeichnung, Inventarnummer oder Seriennummer
- `object_type`: exakter Kategoriename
- `object_status`: z. B. `in_benutzung`
- `location`: vollständiger Standortpfad; schließt Unterstandorte ein
- `limit`: 1 bis 200
- `offset`: Startposition

Ein einzelnes Objekt kann über Inventarnummer, Seriennummer oder interne ID gelesen werden:

```bash
curl -H "X-API-Key: fwi_..." \
  https://inventar.example.de/api/v1/objects/FFW-00042
```

## Objekt anlegen

```bash
curl -X POST \
  -H "X-API-Key: fwi_..." \
  -H "Content-Type: application/json" \
  https://inventar.example.de/api/v1/objects \
  -d '{
    "designation": "C-Schlauch 20 m",
    "object_type": "Schläuche, Armaturen und Zubehör",
    "serial_number": "C-001",
    "manufacturer": "Hersteller XY",
    "supplier": "Lieferant XY",
    "location": "Gerätehaus > HLF 20/20 > G1",
    "acquisition_date": "2026-10-02",
    "status": "in_benutzung",
    "inspection_required": true,
    "maintenance_schedules": [
      {
        "description": "Jährliche Prüfung",
        "interval_days": 365
      }
    ],
    "create_missing_master_data": true
  }'
```

`create_missing_master_data` darf fehlende Kategorien, Hersteller und Lieferanten anlegen. Standortpfade werden aus Sicherheitsgründen nie automatisch erzeugt. Bereits vergebene Seriennummern führen zu HTTP `409` statt zu einer Dublette.

## Fehler und Dokumentation

Fehler enthalten eine verständliche Meldung im Feld `detail`. Die vollständige interaktive OpenAPI-Dokumentation liegt unter `/docs`, die maschinenlesbare Beschreibung unter `/openapi.json`.
