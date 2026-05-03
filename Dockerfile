# Verwende ein schlankes Python-Image
FROM python:3.12-slim

# Setze Arbeitsverzeichnis
WORKDIR /app

# Installiere System-Abhängigkeiten
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Kopiere Requirements und installiere Python-Abhängigkeiten
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiere den Anwendungscode
COPY app/ ./app/

# Erstelle Verzeichnis für die Datenbank (für Volume-Mounts)
RUN mkdir -p /app/data

# Exponiere Port
EXPOSE 8000

# Starte die Anwendung
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
