import unittest
import requests
import time
import subprocess
import os

EXPORTER_URL = "http://localhost:9103/metrics"

class TestFirebirdExporter(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Optionally start the exporter process before running tests."""
        # Note: Ensure config.json and metrics.json are present before running
        cls.process = subprocess.Popen(
            ["python3", "firebird_exporter.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        # Give the exporter server 3 seconds to spin up
        time.sleep(3)

    @classmethod
    def tearDownClass(cls):
        """Terminate the exporter process after tests finish."""
        cls.process.terminate()
        cls.process.wait()

    def test_http_endpoint_status(self):
        """Test if the /metrics endpoint returns HTTP 200 OK."""
        response = requests.get(EXPORTER_URL)
        self.assertEqual(response.status_code, 200, "Exporter endpoint did not return 200 OK")

    def test_standard_metrics_exist(self):
        """Test if core Firebird 2.5 metrics are present in the output."""
        response = requests.get(EXPORTER_URL)
        content = response.text

        expected_metrics = [
            "firebird_transactions_total",
            "firebird_transaction_oit",
            "firebird_transaction_oat",
            "firebird_transaction_gap",
            "firebird_locks_active_total",
            "firebird_locks_waiting_total"
        ]

        for metric in expected_metrics:
            self.assertIn(metric, content, f"Expected metric '{metric}' missing from exporter output")

    def test_custom_metrics_exist(self):
        """Test if custom metrics from metrics.json are present in output."""
        response = requests.get(EXPORTER_URL)
        content = response.text

        # Check for sample custom metric defined in default metrics.json
        self.assertIn("firebird_custom_table_count", content, "Custom metric missing from output")

if __name__ == '__main__':
    unittest.main()

