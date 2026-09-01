import json
import unittest
from pathlib import Path

from scripts.garmin_sync import build_dashboard


class GarminDashboardTests(unittest.TestCase):
    def test_activity_mapping_and_metrics(self):
        fixture = Path(__file__).parent / "fixtures" / "garmin-activities.sample.json"
        activities = json.loads(fixture.read_text(encoding="utf-8"))
        data = build_dashboard(activities, fetch_all=True, ftp=238)

        self.assertEqual(data["source"], "garmin_connect")
        self.assertEqual(len(data["recent_rides"]), 1)
        self.assertEqual(len(data["recent_runs"]), 1)
        self.assertEqual(len(data["recent_swims"]), 1)
        self.assertEqual(len(data["recent_weights"]), 1)
        self.assertEqual(data["recent_rides"][0]["avg_watts"], 168)
        self.assertEqual(data["recent_runs"][0]["avg_pace_km"], "5:12")
        self.assertEqual(data["recent_swims"][0]["pace_per_100m"], "2:20")
        self.assertEqual(data["summary"]["all_time_distance_km"], 32.1)
        self.assertEqual(data["segments"], [])
        self.assertEqual(data["power_prs"], [])


if __name__ == "__main__":
    unittest.main()
