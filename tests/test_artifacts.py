"""Check the published experiment's internal consistency without timing assertions."""
import csv
import hashlib
import json
from pathlib import Path
import statistics
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PublishedArtifactTests(unittest.TestCase):
    def test_source_hash_and_sample_counts(self):
        meta = json.loads((ROOT/'results/metadata.json').read_text())
        self.assertEqual(meta['source_sha256'], hashlib.sha256((ROOT/'src/integer_compiler/core.py').read_bytes()).hexdigest())
        with (ROOT/'results/raw_timings.csv').open(newline='') as f:
            raw = list(csv.DictReader(f))
        self.assertEqual(len(raw), 5*3*meta['samples_per_engine'])
        for r in raw:
            self.assertGreater(int(r['elapsed_ns']), 0)
            self.assertAlmostEqual(float(r['ns_per_call']), int(r['elapsed_ns'])/int(r['iterations']))

    def test_summary_medians_reconcile(self):
        with (ROOT/'results/raw_timings.csv').open(newline='') as f:
            raw = list(csv.DictReader(f))
        with (ROOT/'results/summary.csv').open(newline='') as f:
            summary = list(csv.DictReader(f))
        for row in summary:
            samples = [float(r['ns_per_call']) for r in raw if r['workload']==row['workload'] and r['engine']==row['engine']]
            self.assertEqual(len(samples), int(row['samples']))
            self.assertAlmostEqual(statistics.median(samples), float(row['median_ns']))


if __name__ == '__main__':
    unittest.main()
