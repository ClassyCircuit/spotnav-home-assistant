"""Actual dashboard serializer with mocked captured HA boundaries (no HA connection)."""
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
package = types.ModuleType("custom_components.spotnav")
package.__path__ = [str(ROOT / "custom_components" / "spotnav")]
sys.modules[package.__name__] = package
from custom_components.spotnav.api.dashboard import serialize_published_intervals, serialize_intervals
from custom_components.spotnav.planning.planner import ChartInterval


class PublishedIntervals(unittest.TestCase):
    def test_original_boundaries_and_major_units(self):
        start = datetime(2026, 10, 25, 0, tzinfo=timezone.utc)
        def row(s, e, price):
            return ChartInterval(s, e, s, e, s.date(), price, price + 20)
        rows = (row(start, start + timedelta(hours=1), -12),
                row(start + timedelta(hours=1, minutes=15), start + timedelta(hours=1, minutes=37), 45))
        c = SimpleNamespace(intervals=rows, area_entry=SimpleNamespace(currency="JPY", tz="Europe/Stockholm"), snapshot=None, plan=None)
        result = serialize_published_intervals(c)
        self.assertEqual([r['raw_price'] for r in result], [-0.12, 0.45])
        self.assertEqual(result[1]['end'], rows[1].end.isoformat())
        self.assertEqual(len(serialize_intervals(c)), 2)
        c.intervals = (rows[0], row(start + timedelta(minutes=30), start + timedelta(hours=2), 10))
        self.assertIsNone(serialize_published_intervals(c))
        c.intervals = None
        self.assertIsNone(serialize_published_intervals(c))


if __name__ == "__main__":
    unittest.main()
