import json
import tempfile
import unittest
from pathlib import Path

from incident_summary.core import IncidentValidationError, build_summary, load_incidents, render_html, validate_incidents


class IncidentSummaryTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {
                "id": "INC-001",
                "severity": "high",
                "status": "resolved",
                "service": "Identity",
                "opened_at": "2026-09-01T10:00:00Z",
                "resolved_at": "2026-09-01T11:30:00Z",
            },
            {
                "id": "INC-002",
                "severity": "medium",
                "status": "open",
                "service": "Network",
                "opened_at": "2026-09-02T09:00:00-04:00",
                "resolved_at": None,
            },
            {
                "id": "INC-003",
                "severity": "critical",
                "status": "closed",
                "service": "Identity",
                "opened_at": "2026-09-03T14:00:00Z",
                "resolved_at": "2026-09-03T14:30:00Z",
            },
        ]

    def test_summary_counts_and_resolution_statistics(self):
        summary = build_summary(validate_incidents(self.records))
        self.assertEqual(summary["total_incidents"], 3)
        self.assertEqual(summary["active_incidents"], 1)
        self.assertEqual(summary["resolved_incidents"], 2)
        self.assertEqual(summary["by_service"], {"Identity": 2, "Network": 1})
        self.assertEqual(summary["mean_resolution_minutes"], 60.0)
        self.assertEqual(summary["median_resolution_minutes"], 60.0)

    def test_duplicate_ids_are_rejected(self):
        duplicate = [self.records[0], dict(self.records[0])]
        with self.assertRaisesRegex(IncidentValidationError, "duplicate id"):
            validate_incidents(duplicate)

    def test_closed_incident_requires_resolution_time(self):
        invalid = dict(self.records[0], status="closed", resolved_at=None)
        with self.assertRaisesRegex(IncidentValidationError, "require resolved_at"):
            validate_incidents([invalid])

    def test_resolution_cannot_precede_open_time(self):
        invalid = dict(self.records[0], resolved_at="2026-09-01T09:59:00Z")
        with self.assertRaisesRegex(IncidentValidationError, "precedes"):
            validate_incidents([invalid])

    def test_html_escapes_service_names(self):
        record = dict(self.records[0], service="Identity <Admin>")
        rendered = render_html(build_summary(validate_incidents([record])))
        self.assertIn("Identity &lt;Admin&gt;", rendered)
        self.assertNotIn("Identity <Admin>", rendered)

    def test_load_incidents_reads_utf8_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "incidents.json"
            path.write_text(json.dumps(self.records), encoding="utf-8")
            self.assertEqual(len(load_incidents(path)), 3)


if __name__ == "__main__":
    unittest.main()
