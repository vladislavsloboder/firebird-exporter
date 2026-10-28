# Firebird 2.5 Prometheus Exporter & PMM Integration

[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)
[![Firebird](https://img.shields.io/badge/Firebird-2.5-orange.svg)](https://www.firebirdsql.org/)
[![Prometheus](https://img.shields.io/badge/Prometheus-Compatible-red.svg)](https://prometheus.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A lightweight, modular Python-based Prometheus Exporter specifically designed for **Firebird 2.5**. It exposes critical internal database statistics (such as Transaction Counters, OIT/OAT, Lock states, and custom SQL metrics) to **Percona Monitoring and Management (PMM)** and **Grafana**.

---

## 🏗️ Architecture Overview

The solution bridges Firebird 2.5 internal monitoring tables (`MON$*`) with PMM's time-series database and an external Grafana instance.

![Architecture Overview](architecture.png)

---

## 🚀 Features
* **Transaction Counter Monitoring:** Tracks `MON$NEXT_TRANSACTION`, `MON$OLDEST_TRANSACTION` (OIT), and `MON$OLDEST_ACTIVE` (OAT).
* **Garbage Collection Lag Detection:** Calculates the transaction gap (`Next - OIT`) to prevent database bloat.
* **Lock Management:** Monitors granted and waiting locks via `MON$LOCKS`.
* **Dynamic Custom Metrics:** Easily add custom SQL queries via a separate `metrics.json` file.
* **PMM & Grafana Ready:** Seamlessly integrates into Docker-based PMM environments and external Grafana setups.

---

## ⚙️ Installation & Setup (German / Deutsch)

### 1. Voraussetzungen & Abhängigkeiten
Installiere Python 3 und die benötigten Bibliotheken auf deinem Datenbank- oder Exporter-Server:
```bash
pip install fdb prometheus_client
```

### 2. Konfiguration
Lege einen Projektordner an (z. B. `/opt/firebird-exporter`) und platziere dort folgende Dateien:
* `firebird_exporter.py` (Das Hauptskript)
* `config.json` (Zugangsdaten)
* `metrics.json` (Optionale Custom Queries)

**Beispiel `config.json`:**
```json
{
  "server": {
    "port": 9103,
    "scrape_interval_seconds": 15
  },
  "database": {
    "dsn": "localhost:/pfad/zu/deiner/datenbank.fdb",
    "user": "SYSDBA",
    "password": "dein_passwort",
    "charset": "UTF8"
  }
}
```

### 3. Als Systemd-Dienst einrichten
Erstelle die Service-Datei:
```bash
sudo nano /etc/systemd/system/firebird-exporter.service
```
Füge folgenden Inhalt ein:
```ini
[Unit]
Description=Firebird 2.5 Prometheus Exporter
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/firebird-exporter
ExecStart=/usr/bin/python3 /opt/firebird-exporter/firebird_exporter.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
Dienst aktivieren und starten:
```bash
sudo systemctl daemon-reload
sudo systemctl enable firebird-exporter
sudo systemctl start firebird-exporter
```

### 4. Integration in PMM
Füge den Exporter als **External Service** in PMM hinzu (entweder über die PMM Web-UI unter *Configuration -> PMM Inventory -> Add Instance* oder via CLI):
```bash
pmm-admin add external \
  --service-name=firebird-exporter \
  --listen-port=9103 \
  --metrics-path=/metrics
```
## Testen des Exporters

Um die Funktionalität des Exporters und den Abruf der Metriken zu überprüfen, kannst du die bereitgestellte Testroutine (`test_exporter.py`) verwenden.

### 1. Voraussetzungen prüfen
Stelle sicher, dass der Exporter-Dienst läuft und auf Port `9103` erreichbar ist (entweder lokal oder via Docker).

### 2. Test-Skript ausführen
Das Testskript prüft, ob der Metrik-Endpunkt (`/metrics`) erreichbar ist und ob die erwarteten Prometheus-Metriken korrekt zurückgegeben werden.

Führe das Skript in deinem Terminal aus:
```bash
python3 test_exporter.py
```
---

## 🇬🇧 English Documentation

### Features
* **Transaction Monitoring:** Real-time tracking of transaction counters, OIT, and OAT.
* **Garbage Collection Health:** Monitors transaction gaps to avoid performance degradation.
* **Lock Tracking:** Measures active and waiting database locks.
* **Custom Queries:** Extend monitoring easily using `metrics.json`.

### Quick Start
1. Install dependencies: `pip install fdb prometheus_client`
2. Configure `config.json` with your Firebird 2.5 credentials and path.
3. Run manually to test: `python3 firebird_exporter.py`
4. Access metrics at: `http://<server-ip>:9103/metrics`
5. Register with PMM using `pmm-admin` or the PMM Web UI.
---
## 🐳 Deployment als Docker-Container

Der Exporter lässt sich als einzelner Container betreiben. Auf dem Server werden weder Python noch `pip` oder die Firebird-Client-Bibliothek installiert, alles steckt im Image (siehe `Dockerfile`). Für ein reproduzierbares Ergebnis sind die Versionen im `Dockerfile` fest eingetragen:

```dockerfile
FROM python:3.12-slim
...
RUN pip install --no-cache-dir fdb==2.0.4 prometheus_client==0.26.0
```

### 1. Konfiguration

`config.json` neben der `docker-compose.yml` anlegen (Beispiel siehe oben). Innerhalb des Containers zeigt `localhost` auf den Container selbst, im `dsn` also den Hostnamen oder die IP des Firebird-Servers eintragen, z. B. `192.168.1.10:/daten/db.fdb`.

### 2. Starten

```bash
docker compose up -d --build
docker logs --tail 20 firebird-prometheus-exporter
curl -s http://localhost:9103/metrics | grep -E '^firebird_(up|scrape)'
```

`firebird_up 1.0` bedeutet, dass die Verbindung zur Datenbank funktioniert.

> Läuft Firebird nicht in derselben Compose-Datei, den Eintrag `depends_on: - firebird` entfernen, sonst bricht Compose mit einem Fehler ab.

### 3. PMM-Agent anbinden

Ist auf dem Host ein PMM-Client installiert, registriert er den Exporter-Port einmalig als externen Service. Der Agent liest `localhost:9103`:

```bash
pmm-admin add external \
  --service-name=firebird-exporter \
  --group=firebird \
  --listen-port=9103 \
  --metrics-path=/metrics
```

Läuft der PMM-Client selbst in einem anderen Container oder auf einem anderen Host, nimmst du stattdessen die URL des Exporters:

```bash
pmm-admin add external-serverless \
  --external-name=firebird-exporter \
  --group=firebird \
  --url=http://<exporter-host>:9103/metrics
```

Nach ein bis zwei Minuten liefert die Abfrage `firebird_up` in PMM unter *Explore* einen Wert.

### 4. Update

```bash
git pull
docker compose up -d --build
```

Änderungen an `config.json` oder `metrics.json` brauchen nur `docker compose restart firebird-exporter`.

---

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
