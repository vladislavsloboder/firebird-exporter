FROM python:3.10-slim

WORKDIR /app

# 1. System-Abhängigkeiten (Firebird Client Library für fdb) installieren
RUN apt-get update && apt-get install -y \
    libfbclient2 \
    && rm -rf /var/lib/apt/lists/*

# 2. Python-Bibliotheken per pip3 installieren
RUN pip install --no-cache-dir fdb prometheus_client requests

# 3. Skripte und Konfigurationen in den Container kopieren
COPY firebird_exporter.py .
COPY config.json .
COPY metrics.json .

EXPOSE 9103

# 4. Exporter beim Start ausführen
CMD ["python3", "firebird_exporter.py"]

