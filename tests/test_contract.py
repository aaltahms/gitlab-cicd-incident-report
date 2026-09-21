"""Behavioral contract and subprocess tests; no network or third-party libraries."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from incident_summary.core import IncidentValidationError, build_summary, validate_incidents

BASE = dict(id="A", severity="high", status="open", service="Network", opened_at="2026-09-01T00:00:00Z")

class ContractTests(unittest.TestCase):
    def test_invalid_records(self):
        cases = [None, {}, [None], [dict(BASE, id=" ")], [dict(BASE, severity="urgent")],
                 [dict(BASE, status="pending")], [dict(BASE, service=" ")],
                 [dict(BASE, opened_at="2026-09-01")], [dict(BASE, opened_at="bad")],
                 [dict(BASE, resolved_at="2026-09-01T01:00:00Z")],
                 [dict(BASE, typo=True)], [BASE, dict(BASE, id=" A ")]]
        for records in cases:
            with self.subTest(records=records), self.assertRaises(IncidentValidationError):
                validate_incidents(records)

    def test_empty_dataset_has_no_invented_resolution(self):
        result = build_summary([])
        self.assertEqual(result['total_incidents'], 0)
        self.assertIsNone(result['p90_resolution_minutes'])
        self.assertIsNone(result['mean_resolution_minutes'])

    def test_timezone_equivalence_and_exact_aging(self):
        records = [BASE, dict(BASE, id="B", opened_at="2026-08-31T20:00:00-04:00")]
        result = build_summary(validate_incidents(records), datetime(2026, 9, 2, tzinfo=timezone.utc))
        self.assertEqual([r['age_minutes'] for r in result['active_backlog']], [1440, 1440])
        self.assertEqual([r['id'] for r in result['active_backlog']], ['A', 'B'])

    def test_snapshot_rejects_future_events(self):
        for snapshot in [datetime(2026, 8, 1, tzinfo=timezone.utc), datetime(2026, 9, 2)]:
            with self.assertRaises(IncidentValidationError):
                build_summary(validate_incidents([BASE]), snapshot)

    def test_percentile_nearest_rank_and_resolved_only_sample(self):
        rows = [dict(BASE, id=str(i), status="closed", resolved_at=f"2026-09-01T00:{i:02}:00Z") for i in range(1, 11)]
        result = build_summary(validate_incidents(rows + [BASE]))
        self.assertEqual(result['p90_resolution_minutes'], 9)
        self.assertEqual(result['resolution_sample_size'], 10)
        self.assertEqual(result['median_resolution_minutes'], 5.5)

class CLITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'input.json'
        self.source.write_text(json.dumps([BASE]))
        self.output = self.root / 'report.json'
        self.html = self.root / 'index.html'

    def run_cli(self, source=None, output=None, extra=()):
        return subprocess.run([sys.executable, '-m', 'incident_summary.cli', str(source or self.source),
            '--json', str(output or self.output), '--html', str(self.html), *extra],
            capture_output=True, text=True)

    def test_end_to_end_reproducibility(self):
        args = ('--as-of', '2026-09-02T00:00:00Z')
        self.assertEqual(self.run_cli(extra=args).returncode, 0)
        first = (self.output.read_bytes(), self.html.read_bytes())
        self.assertEqual(self.run_cli(extra=args).returncode, 0)
        self.assertEqual(first, (self.output.read_bytes(), self.html.read_bytes()))
        self.assertEqual(json.loads(first[0])['active_backlog'][0]['age_minutes'], 1440)
        self.assertIn(b'synthetic', first[1])

    def test_invalid_json_preserves_existing_reports(self):
        self.output.write_text('keep')
        self.source.write_text('{broken')
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(self.output.read_text(), 'keep')
        self.assertFalse(self.html.exists())

    def test_missing_file_reports_error(self):
        result = self.run_cli(source=self.root / 'absent')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)

    def test_invalid_encoding_reports_error(self):
        self.source.write_bytes(b'\xff')
        self.assertEqual(self.run_cli().returncode, 2)

    def test_input_overwrite_rejected(self):
        before = self.source.read_bytes()
        self.assertEqual(self.run_cli(output=self.source).returncode, 2)
        self.assertEqual(self.source.read_bytes(), before)

    def test_alias_overwrite_rejected(self):
        alias = self.root / 'alias.json'
        os.link(self.source, alias)
        self.assertEqual(self.run_cli(output=alias).returncode, 2)

    def test_output_collision_rejected(self):
        self.assertEqual(self.run_cli(output=self.html).returncode, 2)

    def test_invalid_snapshot_produces_no_artifacts(self):
        self.assertEqual(self.run_cli(extra=('--as-of', '2020-01-01T00:00:00Z')).returncode, 2)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.html.exists())

if __name__ == '__main__':
    unittest.main()
