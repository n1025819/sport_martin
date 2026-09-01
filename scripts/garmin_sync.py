"""從 Garmin Connect 讀取活動並產生既有儀表板使用的 data/strava.json。"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "strava.json"
ENCRYPTED_TOKEN = ROOT / "data" / "garmin-tokens.enc"
TAIPEI = timezone(timedelta(hours=8))

RIDE_KEYS = {
    "cycling", "road_biking", "mountain_biking", "indoor_cycling",
    "virtual_ride", "gravel_cycling", "bmx", "cyclocross", "e_bike_fitness",
}
RUN_KEYS = {
    "running", "street_running", "trail_running", "treadmill_running",
    "indoor_running", "track_running", "virtual_run", "ultra_run",
}
SWIM_KEYS = {"swimming", "lap_swimming", "open_water_swimming"}
WEIGHT_KEYS = {
    "strength_training", "cardio", "hiit", "yoga", "pilates",
    "indoor_cardio", "elliptical", "stair_climbing", "breathwork",
}


def number(value, default=0.0):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def rounded(value):
    return round(number(value)) if value is not None else None


def type_key(activity):
    value = activity.get("activityType") or {}
    if isinstance(value, dict):
        value = value.get("typeKey", "")
    return str(value or "").lower()


def category(activity):
    key = type_key(activity)
    name = str(activity.get("activityName") or "").lower()
    if "hyrox" in key or "hyrox" in name:
        return "hyrox"
    if key in RIDE_KEYS or any(x in key for x in ("cycling", "biking", "bike", "ride")):
        return "ride"
    if key in RUN_KEYS or "running" in key or key.endswith("_run"):
        return "run"
    if key in SWIM_KEYS or "swim" in key:
        return "swim"
    if key in WEIGHT_KEYS or any(x in key for x in ("strength", "weight", "yoga", "pilates", "cardio")):
        return "weight"
    return None


def start_local(activity):
    value = activity.get("startTimeLocal") or activity.get("startTimeGMT") or ""
    value = str(value).replace(" ", "T")
    return value if len(value) >= 16 else value.ljust(16, "0")


def pace(speed_ms, per_meters=1000):
    speed_ms = number(speed_ms)
    if speed_ms <= 0:
        return None
    seconds = per_meters / speed_ms
    minutes = int(seconds // 60)
    secs = int(round(seconds % 60))
    if secs == 60:
        minutes += 1
        secs = 0
    return "%d:%02d" % (minutes, secs)


def base_card(activity):
    start = start_local(activity)
    moving = number(activity.get("movingDuration"), number(activity.get("duration")))
    return {
        "id": activity.get("activityId"),
        "name": activity.get("activityName") or "Garmin Activity",
        "date": start[:10],
        "time": start[11:16],
        "moving_time_sec": round(moving),
        "moving_time_hr": round(moving / 3600, 1),
        "avg_heartrate": rounded(activity.get("averageHR")),
        "max_heartrate": rounded(activity.get("maxHR")),
        "calories_kcal": rounded(activity.get("calories")),
        "description": activity.get("description") or None,
        "source": "garmin_connect",
        "source_activity_type": type_key(activity),
    }


def activity_card(activity, kind, ftp):
    card = base_card(activity)
    distance = number(activity.get("distance"))
    moving = number(activity.get("movingDuration"), number(activity.get("duration")))
    speed = number(activity.get("averageSpeed"))
    if speed <= 0 and moving > 0:
        speed = distance / moving

    if kind in ("weight", "hyrox"):
        card.update({
            "total_sets": activity.get("totalSets"),
            "total_reps": activity.get("totalReps"),
            "total_volume": activity.get("totalVolume"),
        })
        return card

    card.update({
        "distance_km": round(distance / 1000, 2),
        "avg_speed_kmh": round(speed * 3.6, 1),
        "polyline": None,
    })

    if kind == "ride":
        avg_power = number(activity.get("avgPower"))
        norm_power = number(activity.get("normPower"), avg_power)
        if_score = round(norm_power / ftp, 3) if norm_power > 0 and ftp > 0 else None
        tss = round((moving * norm_power * (norm_power / ftp)) / (ftp * 3600) * 100) if if_score else None
        card.update({
            "elevation_m": round(number(activity.get("elevationGain"))),
            "avg_cadence_rpm": rounded(activity.get("averageBikingCadenceInRevPerMinute", activity.get("averageCadence"))),
            "avg_watts": round(avg_power) if avg_power > 0 else None,
            "max_watts": rounded(activity.get("maxPower")),
            "np_watts": round(norm_power) if norm_power > 0 else None,
            "trainer": any(x in type_key(activity) for x in ("indoor", "virtual")),
            "sport_type": "Ride",
            "if_score": if_score,
            "tss": tss,
            "top_laps": [],
            "route_stream": [],
        })
    elif kind == "run":
        card.update({
            "elevation_m": round(number(activity.get("elevationGain"))),
            "max_speed_kmh": round(number(activity.get("maxSpeed")) * 3.6, 1) if activity.get("maxSpeed") else None,
            "avg_pace_km": pace(speed),
            "avg_cadence_spm": rounded(activity.get("averageRunningCadenceInStepsPerMinute", activity.get("averageCadence"))),
        })
    elif kind == "swim":
        card.update({"pace_per_100m": pace(speed, 100)})
    return card


def merge_cards(new_cards, old_cards, replace):
    if replace:
        merged = {str(item.get("id")): item for item in new_cards if item.get("id") is not None}
    else:
        merged = {str(item.get("id")): item for item in old_cards if item.get("id") is not None}
        for item in new_cards:
            if item.get("id") is not None:
                merged[str(item["id"])] = {**merged.get(str(item["id"]), {}), **item}
    return sorted(merged.values(), key=lambda item: (item.get("date", ""), item.get("time", "")), reverse=True)


def status_of(count, target):
    ratio = count / target if target else 0
    return "over" if ratio >= 1.5 else "done" if ratio >= 1 else "warning" if ratio >= 0.5 else "danger"


def build_dashboard(activities, existing=None, fetch_all=True, ftp=238):
    existing = existing if isinstance(existing, dict) and existing.get("source") == "garmin_connect" else {}
    grouped = {"ride": [], "run": [], "swim": [], "weight": [], "hyrox": []}
    for activity in activities:
        kind = category(activity)
        if kind:
            grouped[kind].append(activity_card(activity, kind, ftp))

    lists = {}
    for kind, json_key in (("ride", "recent_rides"), ("run", "recent_runs"), ("swim", "recent_swims"), ("weight", "recent_weights"), ("hyrox", "recent_hyrox")):
        lists[kind] = merge_cards(grouped[kind], existing.get(json_key, []), fetch_all)

    # An activity renamed in Garmin (for example strength training → HYROX)
    # must move categories during incremental sync instead of being counted twice.
    fetched_categories = {
        str(activity.get("activityId")): category(activity)
        for activity in activities
        if activity.get("activityId") is not None and category(activity)
    }
    for kind in lists:
        lists[kind] = [
            item for item in lists[kind]
            if fetched_categories.get(str(item.get("id")), kind) == kind
        ]

    now = datetime.now(TAIPEI)
    year_prefix = str(now.year) + "-"
    month_prefix = now.strftime("%Y-%m")
    monday = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")

    def in_period(items, prefix=None, after=None):
        if prefix:
            return [item for item in items if item.get("date", "").startswith(prefix)]
        return [item for item in items if item.get("date", "") >= after]

    months = sorted({item.get("date", "")[:7] for values in lists.values() for item in values if len(item.get("date", "")) >= 7})
    history = []
    for month in months:
        rides = in_period(lists["ride"], prefix=month)
        runs = in_period(lists["run"], prefix=month)
        swims = in_period(lists["swim"], prefix=month)
        weights = in_period(lists["weight"], prefix=month)
        hyrox = in_period(lists["hyrox"], prefix=month)
        history.append({
            "month": month,
            "ride": {"distance_km": round(sum(x.get("distance_km", 0) for x in rides), 1), "elevation_m": round(sum(x.get("elevation_m", 0) for x in rides)), "count": len(rides)},
            "run": {"distance_km": round(sum(x.get("distance_km", 0) for x in runs), 1), "count": len(runs)},
            "swim": {"distance_km": round(sum(x.get("distance_km", 0) for x in swims), 1), "count": len(swims)},
            "weight_training": {"count": len(weights)},
            "hyrox": {"count": len(hyrox)},
        })

    month = {kind: in_period(values, prefix=month_prefix) for kind, values in lists.items()}
    week = {kind: in_period(values, after=monday) for kind, values in lists.items()}
    ytd_rides = in_period(lists["ride"], prefix=year_prefix)
    ytd_runs = in_period(lists["run"], prefix=year_prefix)
    ytd_swims = in_period(lists["swim"], prefix=year_prefix)

    def sum_km(values): return round(sum(x.get("distance_km", 0) for x in values), 1)
    def sum_hr(values): return round(sum(x.get("moving_time_sec", 0) for x in values) / 3600, 1)
    def weight_parts(values):
        text = " ".join(x.get("name", "").lower() for x in values)
        return {
            "chest": "胸" in text or "chest" in text,
            "back": "背" in text or "back" in text,
            "legs": "腿" in text or "leg" in text,
            "shoulders": "肩" in text or "shoulder" in text,
            "arms": any(x in text for x in ("手", "arm", "二頭", "三頭")),
        }

    return {
        "source": "garmin_connect",
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": {
            "ytd_distance_km": sum_km(ytd_rides),
            "ytd_elevation_m": round(sum(x.get("elevation_m", 0) for x in ytd_rides)),
            "ytd_rides": len(ytd_rides),
            "ytd_moving_time_hr": sum_hr(ytd_rides),
            "ytd_run_distance_km": sum_km(ytd_runs),
            "ytd_runs": len(ytd_runs),
            "ytd_swim_distance_km": sum_km(ytd_swims),
            "ytd_swims": len(ytd_swims),
            "all_time_distance_km": sum_km(lists["ride"]),
            "all_time_rides": len(lists["ride"]),
            "all_time_elevation_m": round(sum(x.get("elevation_m", 0) for x in lists["ride"])),
        },
        "recent_rides": lists["ride"],
        "recent_runs": lists["run"],
        "recent_swims": lists["swim"],
        "recent_weights": lists["weight"],
        "recent_hyrox": lists["hyrox"],
        "monthly_history": history,
        "monthly_summary": {
            "ride_km": sum_km(month["ride"]), "ride_hr": sum_hr(month["ride"]),
            "run_km": sum_km(month["run"]), "run_hr": sum_hr(month["run"]),
            "swim_m": round(sum_km(month["swim"]) * 1000), "swim_hr": sum_hr(month["swim"]),
            "weight_count": len(month["weight"]), "weight_hr": sum_hr(month["weight"]),
            "hyrox_count": len(month["hyrox"]), "hyrox_hr": sum_hr(month["hyrox"]),
        },
        "monthly_goals": {
            "ride": {"count": len(month["ride"]), "target": 4, "status": status_of(len(month["ride"]), 4)},
            "run": {"count": len(month["run"]), "target": 4, "status": status_of(len(month["run"]), 4)},
            "swim": {"count": len(month["swim"]), "target": 4, "status": status_of(len(month["swim"]), 4)},
            "weight": {"count": len(month["weight"]), "target": 10, "status": status_of(len(month["weight"]), 10)},
            "hyrox": {"count": len(month["hyrox"]), "target": 4, "status": status_of(len(month["hyrox"]), 4)},
        },
        "weekly_quest": {
            "ride": {"done": sum_km(week["ride"]) >= 30 or sum_hr(week["ride"]) >= 1, "distance_km": sum_km(week["ride"]), "moving_time_hr": sum_hr(week["ride"]), "target_km": 30, "target_hr": 1},
            "run": {"done": sum_km(week["run"]) >= 10 or sum_hr(week["run"]) >= 1, "distance_km": sum_km(week["run"]), "moving_time_hr": sum_hr(week["run"]), "target_km": 10, "target_hr": 1},
            "swim": {"done": sum_km(week["swim"]) * 1000 >= 1000 or sum_hr(week["swim"]) >= 1, "distance_m": round(sum_km(week["swim"]) * 1000), "moving_time_hr": sum_hr(week["swim"]), "target_m": 1000, "target_hr": 1},
            "weight": {"done": len(week["weight"]) >= 1, "count": len(week["weight"]), "target": 1, "parts": weight_parts(week["weight"])},
            "hyrox": {"done": len(week["hyrox"]) >= 1, "count": len(week["hyrox"]), "target": 1},
        },
        "segments": [],
        "seg_scan_ids": [],
        "power_prs": [],
    }


def read_existing(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def live_fetch(fetch_all):
    if sys.version_info < (3, 12):
        raise RuntimeError("Garmin 同步需要 Python 3.12 以上")
    key = os.getenv("GARMIN_TOKEN_KEY", "").strip()
    if not key:
        raise RuntimeError("缺少 GARMIN_TOKEN_KEY GitHub Secret")
    if not ENCRYPTED_TOKEN.exists():
        raise RuntimeError("缺少 data/garmin-tokens.enc；請先執行 garmin_login.py")

    from garminconnect import Garmin
    from garmin_crypto import decrypt_file, encrypt_file

    with tempfile.TemporaryDirectory(prefix="garmin-sync-") as temp_dir:
        token_file = Path(temp_dir) / "garmin_tokens.json"
        decrypt_file(ENCRYPTED_TOKEN, token_file, key)
        client = Garmin()
        client.login(temp_dir)
        if fetch_all:
            start_date = os.getenv("GARMIN_START_DATE", "2000-01-01")
            activities = client.get_activities_by_date(start_date, datetime.now(TAIPEI).date().isoformat())
        else:
            activities = client.get_activities(0, 100)
        if isinstance(activities, dict):
            activities = activities.get("activityList", [])
        client.client.dump(temp_dir)
        encrypt_file(token_file, ENCRYPTED_TOKEN, key)
        return activities, client.get_full_name()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, help="使用本機 JSON fixture，不登入 Garmin")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fetch-all", action="store_true", default=os.getenv("GARMIN_FETCH_ALL") == "1")
    args = parser.parse_args()

    if args.fixture:
        activities = json.loads(args.fixture.read_text(encoding="utf-8"))
        full_name = "Fixture Athlete"
        fetch_all = True
    else:
        fetch_all = args.fetch_all
        activities, full_name = live_fetch(fetch_all)

    existing = read_existing(args.output)
    result = build_dashboard(activities, existing, fetch_all, number(os.getenv("GARMIN_FTP"), 238))
    result["athlete_name"] = full_name or "Martin"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Garmin 同步完成：%d 筆活動 → %s" % (len(activities), args.output))


if __name__ == "__main__":
    main()
