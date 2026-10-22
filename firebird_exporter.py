import time
import json
import os
from prometheus_client import start_http_server, Gauge, Counter
import fdb

# --- HILFSFUNKTIONEN ---

def load_json_file(filename):
    """Lädt eine JSON-Datei und fängt Fehler ab, falls sie nicht existiert."""
    if not os.path.exists(filename):
        raise FileNotFoundError(f"Die Datei {filename} wurde nicht gefunden!")
    with open(filename, 'r', encoding='utf-8') as f:
        return json.load(f)

# --- KONFIGURATION & METRIKEN EINLESEN ---
# Lädt die Server- und Datenbankeinstellungen aus der config.json
CONFIG = load_json_file('config.json')
# Lädt die benutzerdefinierten SQL-Abfragen aus der metrics.json
METRICS_CONFIG = load_json_file('metrics.json')

DB_CONFIG = CONFIG['database']
SERVER_CONFIG = CONFIG['server']

# --- PROMETHEUS METRIKEN DEFINIEREN (Standard für Firebird 2.5) ---

# Counter für Transaktionen (Prometheus berechnet daraus automatisch die Rate pro Sekunde)
TX_TOTAL = Counter('firebird_transactions_total', 'Gesamtzahl der bisher erzeugten Transaktionen (Next Transaction ID)')

# Gauges für den Zustand des Transaction Counters und Locks
TX_OIT = Gauge('firebird_transaction_oit', 'Oldest Interesting Transaction (OIT)')
TX_OAT = Gauge('firebird_transaction_oat', 'Oldest Active Transaction (OAT)')
TX_GAP = Gauge('firebird_transaction_gap', 'Abstand zwischen Next Transaction und OIT (Garbage Collection Stau)')

ACTIVE_LOCKS = Gauge('firebird_locks_active_total', 'Anzahl der aktuell gehaltenen Locks')
WAITING_LOCKS = Gauge('firebird_locks_waiting_total', 'Anzahl der Transaktionen, die auf ein Lock warten')

# Dynamische Metriken aus der metrics.json im Speicher vorbereiten
DYNAMIC_GAUGES = {}
for q in METRICS_CONFIG.get('custom_queries', []):
    metric_name = q['name']
    help_text = q['help']
    mode = q.get('mode', 'scalar')
    
    if mode == 'labeled_kv':
        # Erstellt eine Gauge mit dynamischem Label 'metric_key'
        DYNAMIC_GAUGES[metric_name] = {
            'gauge': Gauge(metric_name, help_text, ['metric_key']),
            'mode': 'labeled_kv',
            'sql': q['sql']
        }
    else:
        # Standard Scalar-Gauge ohne Labels
        DYNAMIC_GAUGES[metric_name] = {
            'gauge': Gauge(metric_name, help_text),
            'mode': 'scalar',
            'sql': q['sql']
        }

# --- DATENSAMMEL-FUNKTION ---

def collect_metrics():
    """Verbindet sich mit Firebird, liest Standard- und Custom-Metriken aus."""
    con = None
    try:
        # Verbindung zur Firebird 2.5 Datenbank herstellen
        con = fdb.connect(
            dsn=DB_CONFIG['dsn'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            charset=DB_CONFIG['charset']
        )
        cur = con.cursor()

        # 1. Standard-Abfrage: Transaction Counter & OIT/OAT aus MON$DATABASE
        cur.execute("""
            SELECT 
                MON$NEXT_TRANSACTION, 
                MON$OLDEST_TRANSACTION, 
                MON$OLDEST_ACTIVE 
            FROM MON$DATABASE
        """)
        row = cur.fetchone()
        if row:
            next_tx, oit, oat = row[0], row[1], row[2]
            
            # Absoluten Zähler für Prometheus übergeben
            TX_TOTAL._value.set(next_tx)
            TX_OIT.set(oit)
            TX_OAT.set(oat)
            
            # Wichtiger Abstand zur Überwachung des Garbage-Collection-Staus
            TX_GAP.set(next_tx - oit)

        # 2. Standard-Abfrage: Locks überwachen über MON$LOCKS
        cur.execute("""
            SELECT 
                SUM(CASE WHEN MON$LOCK_STATE = 0 THEN 1 ELSE 0 END) AS granted_locks,
                SUM(CASE WHEN MON$LOCK_STATE = 1 THEN 1 ELSE 0 END) AS waiting_locks
            FROM MON$LOCKS
        """)
        lock_row = cur.fetchone()
        if lock_row:
            granted, waiting = lock_row[0] or 0, lock_row[1] or 0
            ACTIVE_LOCKS.set(granted)
            WAITING_LOCKS.set(waiting)

        # 3. Dynamische Abfragen aus der metrics.json ausführen
        for key, item in DYNAMIC_GAUGES.items():
            try:
                cur.execute(item['sql'])
                if item['mode'] == 'scalar':
                    res = cur.fetchone()
                    if res and res[0] is not None:
                        item['gauge'].set(res[0])
                elif item['mode'] == 'labeled_kv':
                    for sub_row in cur.fetchall():
                        # Erwartet Spalte 1 als Label-Name und Spalte 2 als numerischen Wert
                        label_val, metric_val = sub_row[0], sub_row[1]
                        if metric_val is not None:
                            item['gauge'].labels(metric_key=str(label_val)).set(metric_val)
            except Exception as query_err:
                print(f"Fehler bei Custom Query '{key}': {query_err}")

        cur.close()
        
    except Exception as e:
        print(f"Fehler bei der Datenbankverbindung oder beim Abrufen: {e}")
    finally:
        # Verbindung immer sauber schließen, um Leaks zu vermeiden
        if con:
            con.close()

# --- HAUPTPROGRAMM ---

if __name__ == '__main__':
    port = SERVER_CONFIG['port']
    interval = SERVER_CONFIG['scrape_interval_seconds']

    # Prometheus HTTP-Server starten
    start_http_server(port)
    print(f"Firebird 2.5 Prometheus Exporter gestartet auf Port {port}...")
    print(f"Lese Intervall: {interval} Sekunden.")

    # Endlosschleife zum zyklischen Abrufen der Metriken
    while True:
        collect_metrics()
        time.sleep(interval)

