"""Firebird 2.5 Prometheus Exporter.

Alle Metriken werden in metrics.json definiert. Der Code enthaelt nur die
Exporter-eigenen Metriken (firebird_up, Scrape-Dauer, Plattenplatz).

Unterstuetzte Modi in metrics.json:
  scalar  - eine Zahl (erste Spalte der ersten Zeile)
  row     - eine Zeile, jede Spalte wird eine eigene Metrik ("columns")
  labeled - mehrere Zeilen; die ersten Spalten sind Labels ("labels"),
            die naechste Spalte ist der Wert
"""
import json
import os
import shutil
import threading
import time

import fdb
from prometheus_client import REGISTRY, start_http_server
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

MODES = ("scalar", "row", "labeled")


def load_json_file(filename):
    """Laedt eine JSON-Datei und meldet fehlende Dateien klar."""
    if not os.path.exists(filename):
        raise FileNotFoundError(f"Die Datei {filename} wurde nicht gefunden!")
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)


def load_metric_definitions(cfg):
    """Prueft metrics.json beim Start und ueberspringt deaktivierte Eintraege."""
    definitions = []
    for i, m in enumerate(cfg.get("metrics", [])):
        if m.get("enabled", True) is False:
            continue
        mode = m.get("mode", "scalar")
        if mode not in MODES:
            raise ValueError(f"metrics[{i}]: unbekannter mode '{mode}'")
        if "sql" not in m:
            raise ValueError(f"metrics[{i}]: 'sql' fehlt")
        if mode in ("scalar", "labeled") and "name" not in m:
            raise ValueError(f"metrics[{i}]: 'name' fehlt")
        if mode == "row" and not m.get("columns"):
            raise ValueError(f"metrics[{i}]: 'columns' fehlt")
        if mode == "labeled" and not m.get("labels"):
            raise ValueError(f"metrics[{i}]: 'labels' fehlt")
        definitions.append(m)
    return definitions


def new_family(kind, name, help_text, labels=None):
    """Counter ohne _created-Metrik, Gauge unveraendert."""
    labels = labels or []
    if kind == "counter":
        base = name[:-6] if name.endswith("_total") else name
        return CounterMetricFamily(base, help_text, labels=labels)
    return GaugeMetricFamily(name, help_text, labels=labels)


def run_metric(cur, m):
    """Fuehrt eine Metrik-Definition aus und liefert Metric-Families."""
    cur.execute(m["sql"])
    mode = m.get("mode", "scalar")
    help_text = m.get("help", m.get("name", ""))

    if mode == "scalar":
        row = cur.fetchone()
        if not row or row[0] is None:
            return []
        fam = new_family(m.get("type", "gauge"), m["name"], help_text)
        fam.add_metric([], float(row[0]))
        return [fam]

    if mode == "row":
        row = cur.fetchone()
        if not row:
            return []
        out = []
        for i, col in enumerate(m["columns"]):
            if i < len(row) and row[i] is not None:
                fam = new_family(col.get("type", "gauge"), col["name"],
                                 col.get("help", col["name"]))
                fam.add_metric([], float(row[i]))
                out.append(fam)
        return out

    # labeled
    labels = m["labels"]
    n = len(labels)
    fam = new_family(m.get("type", "gauge"), m["name"], help_text, labels)
    for row in cur.fetchall():
        if len(row) > n and row[n] is not None:
            fam.add_metric([str(x).strip() for x in row[:n]], float(row[n]))
    return [fam]


class FirebirdCollector:
    """Fragt Firebird bei jedem Scrape ab (mit kurzem Cache)."""

    def __init__(self, db_config, definitions, disk_path, cache_seconds):
        self.db = db_config
        self.definitions = definitions
        self.disk_path = disk_path
        self.cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._cache = None
        self._cache_ts = 0.0

    def describe(self):
        # Verhindert, dass die Registry beim Registrieren schon scrapt.
        return []

    def collect(self):
        with self._lock:
            now = time.time()
            if self._cache is None or now - self._cache_ts >= self.cache_seconds:
                self._cache = self._scrape()
                self._cache_ts = time.time()
            families = self._cache
        for fam in families:
            yield fam

    def _scrape(self):
        start = time.time()
        families = []
        up = 0
        failed = 0
        con = None
        try:
            con = fdb.connect(
                dsn=self.db["dsn"],
                user=self.db["user"],
                password=self.db["password"],
                charset=self.db.get("charset", "UTF8"),
            )
            up = 1
            for m in self.definitions:
                cur = con.cursor()
                try:
                    families.extend(run_metric(cur, m))
                except Exception as err:  # eine kaputte Query stoppt die anderen nicht
                    failed += 1
                    label = m.get("name") or "row-query"
                    print(f"Fehler bei Metrik '{label}': {err}", flush=True)
                finally:
                    cur.close()
        except Exception as err:
            print(f"Fehler bei der Datenbankverbindung: {err}", flush=True)
        finally:
            if con:
                try:
                    con.close()
                except Exception:
                    pass

        families.extend(self._disk_families())

        g = GaugeMetricFamily("firebird_up", "1 wenn die Verbindung zu Firebird klappt")
        g.add_metric([], up)
        families.append(g)
        g = GaugeMetricFamily("firebird_scrape_failed_metrics",
                              "Anzahl fehlgeschlagener Metrik-Queries im letzten Scrape")
        g.add_metric([], failed)
        families.append(g)
        g = GaugeMetricFamily("firebird_scrape_duration_seconds", "Dauer des letzten Scrapes")
        g.add_metric([], time.time() - start)
        families.append(g)
        return families

    def _disk_families(self):
        if not self.disk_path:
            return []
        try:
            usage = shutil.disk_usage(self.disk_path)
        except Exception as err:
            print(f"Plattenplatz nicht lesbar ({self.disk_path}): {err}", flush=True)
            return []
        out = []
        for name, help_text, value in (
            ("firebird_disk_total_bytes", "Gesamtgroesse des Daten-Volumes", usage.total),
            ("firebird_disk_free_bytes", "Freier Platz auf dem Daten-Volume", usage.free),
            ("firebird_disk_used_bytes", "Belegter Platz auf dem Daten-Volume", usage.used),
        ):
            g = GaugeMetricFamily(name, help_text)
            g.add_metric([], value)
            out.append(g)
        return out


if __name__ == "__main__":
    CONFIG = load_json_file("config.json")
    DEFINITIONS = load_metric_definitions(load_json_file("metrics.json"))
    SERVER = CONFIG["server"]
    port = SERVER["port"]
    cache_seconds = SERVER.get("scrape_interval_seconds", 15)
    disk_path = CONFIG.get("disk", {}).get("path")

    REGISTRY.register(FirebirdCollector(CONFIG["database"], DEFINITIONS, disk_path, cache_seconds))
    start_http_server(port)
    print(f"Firebird 2.5 Prometheus Exporter auf Port {port} gestartet.", flush=True)
    print(f"{len(DEFINITIONS)} Metrik-Definitionen geladen, Cache {cache_seconds}s.", flush=True)
    while True:
        time.sleep(3600)
