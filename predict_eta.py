import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Predict ETA from trained route model.")
    parser.add_argument("--model", default="model_outputs/eta_model.joblib", help="Path to trained model bundle.")
    parser.add_argument("--route", choices=["morning", "evening"], required=True, help="Route type.")
    parser.add_argument("--start-time", required=True, help="Start time HH:MM (24h).")
    parser.add_argument("--progress-ratio", type=float, default=0.0, help="Current progress ratio [0,1].")
    parser.add_argument("--progress-m", type=float, default=None, help="Current progress in meters from route start.")
    parser.add_argument("--lat", type=float, default=None, help="Optional current latitude on/near baseline polyline.")
    parser.add_argument("--lng", type=float, default=None, help="Optional current longitude on/near baseline polyline.")
    parser.add_argument("--vehicle-class", default=None, choices=["Shuttle", "Public Bus"], help="Vehicle class.")
    parser.add_argument("--weekday", type=int, default=None, help="Weekday 0=Mon..6=Sun (defaults to today).")
    parser.add_argument("--offroute-m", type=float, default=0.0, help="Current off-route distance in meters.")
    parser.add_argument("--profiles-dir", default="model_outputs", help="Directory containing route_profile_*.csv and choke_points.csv.")
    parser.add_argument("--top-chokes", type=int, default=5, help="How many choke points ahead to print.")
    return parser.parse_args()


def parse_hhmm(value: str) -> int:
    dt = datetime.strptime(value, "%H:%M")
    return dt.hour * 60 + dt.minute


def default_vehicle_class(route: str) -> str:
    return "Shuttle" if route == "morning" else "Public Bus"


def resolve_progress_ratio(route_ref: dict, progress_ratio: float, progress_m: float | None) -> float:
    if progress_m is not None:
        total_m = float(route_ref.get("total_m", 1.0))
        if total_m <= 0:
            return 0.0
        return float(np.clip(progress_m / total_m, 0.0, 1.0))
    return float(np.clip(progress_ratio, 0.0, 1.0))


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1 = np.deg2rad(lat1)
    p2 = np.deg2rad(lat2)
    dp = p2 - p1
    dl = np.deg2rad(lng2 - lng1)
    a = np.sin(dp / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2.0) ** 2
    return float(2.0 * r * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a)))


def nearest_progress_ratio_from_latlng(profile: pd.DataFrame, lat: float, lng: float) -> tuple[float, int, float]:
    if profile.empty:
        return 0.0, 0, float("nan")
    dists = profile.apply(lambda r: haversine_m(lat, lng, float(r["lat"]), float(r["lng"])), axis=1)
    idx = int(dists.idxmin())
    ratio = idx / max(1, len(profile) - 1)
    return float(np.clip(ratio, 0.0, 1.0)), idx, float(dists.iloc[idx])


def main() -> None:
    args = parse_args()
    model_path = Path(args.model)
    profiles_dir = Path(args.profiles_dir)

    bundle = joblib.load(model_path)
    model = bundle["model"]
    route_ref = bundle["route_references"][args.route]

    minute_of_day = parse_hhmm(args.start_time)
    weekday = int(datetime.now().weekday() if args.weekday is None else args.weekday)
    progress_ratio = resolve_progress_ratio(route_ref, args.progress_ratio, args.progress_m)
    vehicle_class = args.vehicle_class or default_vehicle_class(args.route)

    profile_path = profiles_dir / f"route_profile_{args.route}.csv"
    if not profile_path.exists():
        raise FileNotFoundError(f"Missing route profile: {profile_path.as_posix()}")
    profile = pd.read_csv(profile_path)

    if profile.empty:
        raise RuntimeError(f"Route profile is empty: {profile_path.as_posix()}")

    selected_bin = None
    selected_point_dist_m = None
    if args.lat is not None and args.lng is not None:
        progress_ratio, selected_bin, selected_point_dist_m = nearest_progress_ratio_from_latlng(profile, float(args.lat), float(args.lng))

    bin_idx = int(np.clip(progress_ratio * max(1, len(profile) - 1), 0, len(profile) - 1))
    row = profile.iloc[bin_idx]

    feature_row = {
        "route_type": 0 if args.route == "morning" else 1,
        "vehicle_class": 0 if vehicle_class == "Shuttle" else 1,
        "start_minute": minute_of_day,
        "weekday": weekday,
        "progress_ratio": progress_ratio,
        "offroute_m": float(max(0.0, args.offroute_m)),
        "speed_kph": float(row["avg_speed_kph"]),
        "global_bin_speed_kph": float(row["avg_speed_kph"]),
        "bin_session_support": int(row["session_support"]),
    }

    feature_cols = bundle["features"]
    x = pd.DataFrame([{k: feature_row[k] for k in feature_cols}])
    eta_min = float(model.predict(x)[0])
    eta_min = max(0.0, eta_min)

    start_dt = datetime.combine(datetime.today().date(), datetime.strptime(args.start_time, "%H:%M").time())
    eta_dt = start_dt + timedelta(minutes=eta_min)

    result = {
        "route": args.route,
        "vehicle_class": vehicle_class,
        "start_time": args.start_time,
        "progress_ratio": progress_ratio,
        "estimated_eta_min": round(eta_min, 2),
        "estimated_arrival_time": eta_dt.strftime("%H:%M:%S"),
        "model": bundle.get("best_model_name", "unknown"),
        "support_at_position": int(row["session_support"]),
    }

    if selected_bin is not None:
        result["selected_bin_idx"] = int(selected_bin)
        result["selected_point_to_baseline_m"] = round(float(selected_point_dist_m), 2)

    choke_path = profiles_dir / "choke_points.csv"
    if choke_path.exists():
        choke_df = pd.read_csv(choke_path)
        subset = choke_df[choke_df["route_type"] == args.route].copy()
        if not subset.empty:
            remaining = subset[subset["bin_idx"] >= bin_idx].sort_values("congestion", ascending=False).head(args.top_chokes)
            result["choke_points_ahead"] = remaining[
                ["bin_idx", "avg_speed_kph", "congestion", "lat", "lng", "session_support"]
            ].to_dict(orient="records")

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
