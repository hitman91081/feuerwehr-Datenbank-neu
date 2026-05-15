#!/bin/bash
# Feuerwehr Inventar - VPS Setup Script
# Dieses Script richtet die Anwendung auf einem neuen Server ein

set -e  # Beende bei Fehlern

echo "🚒 Feuerwehr Inventar - VPS Setup"
echo "================================"

# === Konfiguration ===
APP_DIR="/opt/feuerwehr-inventar"
REPO_URL="https://github.com/hitman91081/feuerwehr-Datenbank-neu.git"
PORT="8000"
DOMAIN=""  # Optional: Deine Domain (z.B. inventar.deine-feuerwehr.de)

# === Root-Check ===
if [ "$EUID" -ne 0 ]; then 
    echo "⚠️  Bitte als root ausführen: sudo bash setup.sh"
    exit 1
fi

# === System-Pakete installieren ===
echo "📦 System-Pakete werden installiert..."
apt-get update
apt-get install -y python3 python3-pip python3-venv git nginx sqlite3 openssl

# === App-Verzeichnis erstellen ===
echo "📁 Verzeichnis wird erstellt..."
mkdir -p $APP_DIR
cd $APP_DIR

# === Git Repository klonen ===
echo "⬇️  Code wird von GitHub geladen..."
if [ -d ".git" ]; then
    git pull
else
    git clone $REPO_URL .
fi

# === Python Umgebung ===
echo "🐍 Python-Umgebung wird eingerichtet..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# === Verzeichnisse erstellen ===
echo "📂 Verzeichnisse werden erstellt..."
mkdir -p data uploads/images uploads/documents uploads/qrcodes

# === SSL-Zertifikate erstellen (self-signed) ===
echo "🔐 SSL-Zertifikate werden erstellt..."
if [ ! -f key.pem ]; then
    openssl req -x509 -nodes -days 365 -newkey rsa:4096 \
        -keyout key.pem \
        -out cert.pem \
        -subj "/C=DE/ST=Bundesland/L=Ort/O=Feuerwehr/CN=${DOMAIN:-localhost}"
fi

# === Admin-Benutzer erstellen ===
echo "👤 Erstelle initiale Benutzer..."
python3 << PYTHON
import sys
sys.path.insert(0, '.')
from app.database import engine, Base
from app.models import User, UserRole
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import bcrypt

Base.metadata.create_all(bind=engine)

from app.database import SessionLocal
db = SessionLocal()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Admin erstellen
if not db.query(User).filter(User.username == 'admin').first():
    admin = User(
        username='admin',
        full_name='Administrator',
        email='admin@feuerwehr.local',
        hashed_password=pwd_context.hash('admin'),
        role=UserRole.ADMIN,
        is_active=True
    )
    db.add(admin)
    
# Standard-Benutzer erstellen
if not db.query(User).filter(User.username == 'standard').first():
    standard = User(
        username='standard',
        full_name='Standardnutzer',
        email='standard@feuerwehr.local',
        hashed_password=pwd_context.hash('standard'),
        role=UserRole.STANDARD,
        is_active=True
    )
    db.add(standard)

db.commit()
db.close()
print("✅ Benutzer erstellt")
PYTHON

# === Systemd Service erstellen ===
echo "⚙️  Systemd-Service wird erstellt..."
cat > /etc/systemd/system/feuerwehr-inventar.service << 'EOF'
[Unit]
Description=Feuerwehr Inventar Verwaltung
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/feuerwehr-inventar
Environment="PATH=/opt/feuerwehr-inventar/venv/bin"
ExecStart=/opt/feuerwehr-inventar/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --ssl-keyfile /opt/feuerwehr-inventar/key.pem --ssl-certfile /opt/feuerwehr-inventar/cert.pem
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# === Nginx als Reverse Proxy (optional) ===
echo "🌐 Nginx wird konfiguriert..."
cat > /etc/nginx/sites-available/feuerwehr-inventar << 'EOF'
server {
    listen 80;
    server_name _;
    
    location / {
        proxy_pass https://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        
        # Wichtig für Uploads
        client_max_body_size 100M;
        
        # SSL zu Backend (da self-signed)
        proxy_ssl_verify off;
    }
    
    location /uploads/ {
        alias /opt/feuerwehr-inventar/uploads/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    
    location /static/ {
        alias /opt/feuerwehr-inventar/app/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
EOF

# Nginx aktivieren
ln -sf /etc/nginx/sites-available/feuerwehr-inventar /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

# === Firewall ===
echo "🔥 Firewall wird konfiguriert..."
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 8000/tcp  # Für direkten Zugriff

# === Service starten ===
echo "🚀 Service wird gestartet..."
systemctl daemon-reload
systemctl enable feuerwehr-inventar
systemctl start feuerwehr-inventar

# === Status prüfen ===
echo ""
echo "================================"
echo "✅ Installation abgeschlossen!"
echo "================================"
echo ""
echo "🌐 Zugriff:"
echo "   HTTP (Nginx):  http://DEINE-SERVER-IP"
echo "   HTTPS (Direkt): https://DEINE-SERVER-IP:8000"
echo ""
echo "👤 Login:"
echo "   Admin:      admin / admin"
echo "   Standard:   standard / standard"
echo ""
echo "📁 Verzeichnis: $APP_DIR"
echo ""
echo "🔄 Wichtige Befehle:"
echo "   Status prüfen:     systemctl status feuerwehr-inventar"
echo "   Logs ansehen:      journalctl -u feuerwehr-inventar -f"
echo "   Neustarten:        systemctl restart feuerwehr-inventar"
echo "   Update (Code):     cd $APP_DIR && git pull && systemctl restart feuerwehr-inventar"
echo ""
echo "💾 Backup:"
echo "   Im Browser: Verwaltung → Import/Export → Vollständiges Backup herunterladen"
echo "   Dateien:     $APP_DIR/data/feuerwehr.db und $APP_DIR/uploads/"
echo ""
echo "⚠️  WICHTIG: Ändere sofort die Passwörter!"
echo ""
