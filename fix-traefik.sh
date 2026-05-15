#!/bin/bash
# Fix-Script: Traefik statt Nginx verwenden
# Führe das auf dem VPS aus

set -e

echo "🔧 Traefik-Konfiguration wird eingerichtet..."

# === 1. Nginx stoppen & deaktivieren ===
echo "🛑 Nginx wird gestoppt..."
systemctl stop nginx 2>/dev/null || true
systemctl disable nginx 2>/dev/null || true

# === 2. App-Service ohne SSL (Traefik übernimmt SSL) ===
echo "⚙️  App-Service wird auf HTTP umgestellt..."
cat > /etc/systemd/system/feuerwehr-inventar.service << 'EOF'
[Unit]
Description=Feuerwehr Inventar Verwaltung
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/feuerwehr-inventar
Environment="PATH=/opt/feuerwehr-inventar/venv/bin"
ExecStart=/opt/feuerwehr-inventar/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# === 3. Traefik Dynamic Config erstellen ===
echo "📄 Traefik-Router-Config wird erstellt..."
mkdir -p /opt/traefik/dynamic
cat > /opt/traefik/dynamic/feuerwehr-inventar.yml << 'EOF'
http:
  routers:
    feuerwehr-inventar:
      rule: "Host(`inventar.deine-domain.de`)"
      service: feuerwehr-inventar
      entryPoints:
        - websecure
      tls:
        certResolver: default
      
    feuerwehr-inventar-http:
      rule: "Host(`inventar.deine-domain.de`)"
      service: feuerwehr-inventar
      entryPoints:
        - web
      middlewares:
        - redirect-to-https

  services:
    feuerwehr-inventar:
      loadBalancer:
        servers:
          - url: "http://172.17.0.1:8000"

  middlewares:
    redirect-to-https:
      redirectScheme:
        scheme: https
        permanent: true
EOF

cat > /opt/traefik/dynamic/feuerwehr-inventar-localip.yml << 'EOF'
# Alternative: Zugriff über IP (ohne Domain)
# Wenn du keine Domain hast, nutze diese Config
http:
  routers:
    feuerwehr-inventar-ip:
      rule: "PathPrefix(`/`)"
      service: feuerwehr-inventar-ip
      entryPoints:
        - web
      priority: 1

  services:
    feuerwehr-inventar-ip:
      loadBalancer:
        servers:
          - url: "http://172.17.0.1:8000"
EOF

echo ""
echo "================================"
echo "✅ Konfiguration angepasst!"
echo "================================"
echo ""
echo "🔄 App wird neu gestartet..."
systemctl daemon-reload
systemctl restart feuerwehr-inventar

echo ""
echo "📋 Nächste Schritte:"
echo ""
echo "1️⃣  Traefik-Container neu starten (damit die Config geladen wird):"
echo "   docker restart traefik"
echo "   # ODER falls du Docker Compose nutzt:"
echo "   cd /pfad/zu/traefik && docker-compose restart"
echo ""
echo "2️⃣  Wichtig: Mounte das Config-Verzeichnis in Traefik:"
echo "   In deiner docker-compose.yml oder docker run:"
echo "   volumes:"
echo "     - /opt/traefik/dynamic:/etc/traefik/dynamic:ro"
echo ""
echo "3️⃣  Domain anpassen (wenn du eine hast):"
echo "   nano /opt/traefik/dynamic/feuerwehr-inventar.yml"
echo "   Ersetze 'inventar.deine-domain.de' mit deiner Domain"
echo ""
echo "4️⃣  Ohne Domain (Zugriff über IP):"
echo "   Nutze die Datei: /opt/traefik/dynamic/feuerwehr-inventar-localip.yml"
echo "   Achte darauf, dass Traefik nur für diesen Service auf Port 80 läuft!"
echo ""
echo "🌐 Zugriff nach Einrichtung:"
echo "   Mit Domain:  https://inventar.deine-domain.de"
echo "   Ohne Domain: http://DEINE-SERVER-IP (direkt auf Port 80 via Traefik)"
echo ""
echo "📊 Status prüfen:"
echo "   App:  systemctl status feuerwehr-inventar"
echo "   App-Logs:  journalctl -u feuerwehr-inventar -f"
echo ""
