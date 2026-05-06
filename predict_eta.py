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
    parser.add_argument("--dest-lat", type=float, default=None, help="Optional destination latitude on/near baseline polyline.")
    parser.add_argument("--dest-lng", type=float, default=None, help="Optional destination longitude on/near baseline polyline.")
    parser.add_argument("--vehicle-class", default=None, choices=["Shuttle", "Public Bus"], help="Vehicle class.")
    parser.add_argument("--weekday", type=int, default=None, help="Weekday 0=Mon..6=Sun (defaults to today).")
    parser.add_argument("--offroute-m", type=float, default=0.0, help="Current off-route distance in meters.")
    parser.add_argument("--session-id", type=int, default=None, help="Optional session ID for session-aware blending.")
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


def segment_local_eta_min(profile: pd.DataFrame, start_bin: int, end_bin: int) -> float:
    if profile.empty:
        return 0.0

    n = len(profile)
    s = int(np.clip(start_bin, 0, n - 1))
    e = int(np.clip(end_bin, 0, n - 1))
    if e <= s:
        return 0.0

    total_min = 0.0
    for i in range(s, e):
        a = profile.iloc[i]
        b = profile.iloc[i + 1]
        d_m = haversine_m(float(a["lat"]), float(a["lng"]), float(b["lat"]), float(b["lng"]))

        # Penalize slow bins and congestion so short choke segments are not underestimated.
        speed_kph = max(3.0, float(b.get("avg_speed_kph", 20.0)))
        congestion = float(np.clip(b.get("congestion", 0.0), 0.0, 1.0))
        congestion_multiplier = 1.0 + (congestion**2) * 2.4
        effective_speed_kph = max(2.0, speed_kph / congestion_multiplier)

        total_min += (d_m / 1000.0) / effective_speed_kph * 60.0

    return float(max(0.0, total_min))


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

    destination_bin = None
    destination_progress_ratio = None
    destination_point_dist_m = None
    if args.dest_lat is not None and args.dest_lng is not None:
        destination_progress_ratio, destination_bin, destination_point_dist_m = nearest_progress_ratio_from_latlng(
            profile, float(args.dest_lat), float(args.dest_lng)
        )

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
    eta_min_full_route = max(0.0, float(model.predict(x)[0]))

    eta_min = eta_min_full_route
    remaining_to_route_end = max(0.0, 1.0 - progress_ratio)
    remaining_to_destination = None
    destination_delta_ratio = None
    destination_ahead = None
    route_end_bin = len(profile) - 1
    model_eta_for_trip = eta_min_full_route
    local_eta_for_trip = segment_local_eta_min(profile, bin_idx, route_end_bin)
    blend_local_weight = 0.45

    if destination_progress_ratio is not None:
        destination_delta_ratio = destination_progress_ratio - progress_ratio
        destination_ahead = destination_delta_ratio >= 0.0
        remaining_to_destination = max(0.0, destination_delta_ratio)
        destination_target_bin = int(np.clip(round(destination_progress_ratio * route_end_bin), 0, route_end_bin))

        if remaining_to_route_end > 1e-9:
            model_eta_for_trip = eta_min_full_route * (remaining_to_destination / remaining_to_route_end)
        else:
            model_eta_for_trip = 0.0

        if destination_ahead:
            local_eta_for_trip = segment_local_eta_min(profile, bin_idx, destination_target_bin)
        else:
            local_eta_for_trip = 0.0

        # For short spans, emphasize local profile ETA to preserve sharp congestion behavior.
        trip_span = float(np.clip(abs(destination_delta_ratio), 0.0, 1.0))
        blend_local_weight = float(np.clip(0.45 + (0.25 - trip_span) * 1.2, 0.45, 0.8))

    eta_min = (1.0 - blend_local_weight) * model_eta_for_trip + blend_local_weight * local_eta_for_trip
    eta_min = max(0.0, eta_min)

    # Session-aware blending: if session_id is provided, blend with per-session baseline.
    session_aware_blend_weight = 0.0
    session_baseline_eta = None
    if args.session_id is not None:
        sess_stats_path = profiles_dir / "session_statistics.csv"
        if sess_stats_path.exists():
            try:
                sess_stats_df = pd.read_csv(sess_stats_path)
                session_row = sess_stats_df[(sess_stats_df["session_id"] == args.session_id) & (sess_stats_df["route_type"] == args.route)]
                if not session_row.empty and np.isfinite(session_row.iloc[0]["mean_eta_min"]):
                    session_baseline_eta = float(session_row.iloc[0]["mean_eta_min"])
                    # Blend: 30% session baseline, 70% model/local blend
                    session_aware_blend_weight = 0.30
                    eta_min = (1.0 - session_aware_blend_weight) * eta_min + session_aware_blend_weight * session_baseline_eta
                    eta_min = max(0.0, eta_min)
            except Exception:
                pass

    start_dt = datetime.combine(datetime.today().date(), datetime.strptime(args.start_time, "%H:%M").time())
    eta_dt = start_dt + timedelta(minutes=eta_min)

    result = {
        "route": args.route,
        "vehicle_class": vehicle_class,
        "start_time": args.start_time,
        "progress_ratio": progress_ratio,
        "remaining_ratio_to_route_end": round(float(remaining_to_route_end), 6),
        "estimated_eta_min": round(eta_min, 2),
        "estimated_eta_min_to_route_end": round(eta_min_full_route, 2),
        "estimated_eta_local_min": round(local_eta_for_trip, 2),
        "eta_blend_local_weight": round(float(blend_local_weight), 3),
        "session_aware_blend_weight": round(float(session_aware_blend_weight), 3),
        "session_baseline_eta_min": round(float(session_baseline_eta), 2) if session_baseline_eta is not None else None,
        "estimated_arrival_time": eta_dt.strftime("%H:%M:%S"),
        "model": bundle.get("best_model_name", "unknown"),
        "support_at_position": int(row["session_support"]),
    }

    if selected_bin is not None:
        result["selected_bin_idx"] = int(selected_bin)
        result["selected_point_to_baseline_m"] = round(float(selected_point_dist_m), 2)

    if destination_bin is not None:
        result["destination_bin_idx"] = int(destination_bin)
        result["destination_progress_ratio"] = round(float(destination_progress_ratio), 6)
        result["destination_point_to_baseline_m"] = round(float(destination_point_dist_m), 2)
        result["remaining_ratio_to_destination"] = round(float(remaining_to_destination), 6)
        result["destination_delta_ratio"] = round(float(destination_delta_ratio), 6)
        result["destination_ahead"] = bool(destination_ahead)
        result["requested_trip_span_ratio"] = round(float(abs(destination_delta_ratio)), 6)
        result["destination_applied"] = True
    else:
        result["destination_applied"] = False

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
