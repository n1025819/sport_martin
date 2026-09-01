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

    def test_hyrox_name_gets_its_own_category(self):
        activities = [{
            "activityId": 9001,
            "activityName": "HYROX 訓練",
            "activityType": {"typeKey": "strength_training"},
            "startTimeLocal": "2026-09-01 18:30:00",
            "duration": 3600,
            "movingDuration": 3600,
        }]

        data = build_dashboard(activities, fetch_all=True)

        self.assertEqual(len(data["recent_hyrox"]), 1)
        self.assertEqual(len(data["recent_weights"]), 0)
        self.assertEqual(data["monthly_summary"]["hyrox_count"], 1)
        self.assertEqual(data["monthly_summary"]["hyrox_hr"], 1.0)


if __name__ == "__main__":
    unittest.main()
