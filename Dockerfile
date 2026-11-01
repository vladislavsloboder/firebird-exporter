# =============================================================================
#  Project      : Firebird 2.5 Prometheus Exporter & PMM Integration
#  File         : Dockerfile
#  Description  : Portables Image fuer firebird_exporter.py. Enthaelt KEINE
#                 umgebungsspezifischen Daten (kein Port, keine Datenbank,
#                 kein Passwort). Konfiguration kommt zur Laufzeit ueber
#                 docker-compose (Umgebungsvariablen und/oder config.json).
#  Author       : Vladislav Sloboder
#  Repository   : https://github.com/vladislavsloboder/firebird-exporter
#  Created      : 2026-10-27
#  Last changed : 2026-10-29
#  Version      : 2.1.0
#  License      : MIT (SPDX-License-Identifier: MIT)
#  Build        : docker build -t firebird-exporter:2.1.0 .
# =============================================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    EXPORTER_PORT=9103

WORKDIR /app

# 1. Firebird-Client-Bibliothek (wird von fdb benoetigt)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libfbclient2 \
    && rm -rf /var/lib/apt/lists/*

# 2. Python-Libraries in festen Versionen
RUN pip install --no-cache-dir fdb==2.0.4 prometheus_client==0.26.0

# 3. Nur Exporter und Standard-Metriken. Keine config.json im Image.
COPY firebird_exporter.py metrics.json ./

# 4. Nicht als root laufen
RUN useradd --system --uid 10001 --no-create-home exporter
USER exporter

# Nur Information. Der tatsaechliche Port kommt aus EXPORTER_PORT.
EXPOSE 9103

# Healthcheck nutzt denselben Port wie der Exporter
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/metrics' % os.environ.get('EXPORTER_PORT', '9103'), timeout=4)" || exit 1

CMD ["python3", "firebird_exporter.py"]


