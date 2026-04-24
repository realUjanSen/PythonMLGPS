import argparse
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
try:
    from scipy.spatial import cKDTree
except Exception:
    cKDTree = None
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupShuffleSplit

try:
    from xgboost import XGBRegressor
except Exception:
    XGBRegressor = None


SESSION_PATTERN = re.compile(r"session_(\d+)_")


@dataclass
class RouteReference:
    route_type: str
    session_id: int
    file_name: str
    lat0: float
    lng0: float
    xy: np.ndarray
    cumulative_m: np.ndarray
    total_m: float
    n_bins: int
    vertex_tree: object | None = None


def log_step(message: str, t0: float) -> None:
    elapsed = time.time() - t0
    print(f"[{elapsed:7.1f}s] {message}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Train an ETA model from GPS sessions using baseline snapping, "
            "weighted gap-filling, and session-aware validation."
        )
    )
    parser.add_argument("--csv-dir", default="csv", help="Directory containing session CSV files.")
    parser.add_argument("--morning-ref", type=int, default=43, help="Morning baseline session id.")
    parser.add_argument("--evening-ref", type=int, default=35, help="Evening baseline session id.")
    parser.add_argument("--bin-meters", type=float, default=120.0, help="Segment bin size in meters.")
    parser.add_argument("--out-dir", default="model_outputs", help="Output directory.")
    parser.add_argument("--snapped-out-dir", default="csv_snapped", help="Output directory for snapped CSV copies.")
    return parser.parse_args()


def session_id_from_name(file_name: str) -> int | None:
    match = SESSION_PATTERN.search(file_name)
    if not match:
        return None
    return int(match.group(1))


def classify_route_type_from_time(start_ts: pd.Timestamp) -> str | None:
    minute_of_day = start_ts.hour * 60 + start_ts.minute
    if 7 * 60 <= minute_of_day <= 8 * 60 + 30:
        return "morning"
    if 14 * 60 <= minute_of_day <= 18 * 60:
        return "evening"
    return None


def classify_route_type_from_name(file_name: str) -> str | None:
    lower = file_name.lower()
    if "home_to_office" in lower:
        return "morning"
    if "office_to_home" in lower:
        return "evening"
    return None


def normalize_vehicle_class(value: object) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if "shuttle" in raw:
        return "Shuttle"
    if raw in {"bus", "publicbus"}:
        return "Public Bus"
    if "public" in raw and "bus" in raw:
        return "Public Bus"
    return ""


def default_vehicle_class(route_type: str | None) -> str:
    if route_type == "morning":
        return "Shuttle"
    if route_type == "evening":
        return "Public Bus"
    return ""


def latlng_to_xy(lat: np.ndarray, lng: np.ndarray, lat0: float, lng0: float) -> np.ndarray:
    lat_rad = np.deg2rad(lat)
    lat0_rad = math.radians(lat0)
    x = (lng - lng0) * 111320.0 * math.cos(lat0_rad)
    y = (lat - lat0) * 111320.0
    return np.column_stack([x, y])


def cumulative_lengths(xy: np.ndarray) -> np.ndarray:
    if len(xy) == 0:
        return np.array([0.0])
    if len(xy) == 1:
        return np.array([0.0])
    steps = np.sqrt(np.sum(np.diff(xy, axis=0) ** 2, axis=1))
    return np.concatenate([[0.0], np.cumsum(steps)])


def project_point_to_polyline(point_xy: np.ndarray, line_xy: np.ndarray, cum_m: np.ndarray) -> tuple[float, float, np.ndarray]:
    best_dist = float("inf")
    best_along = 0.0
    best_snap = line_xy[0]

    for i in range(len(line_xy) - 1):
        a = line_xy[i]
        b = line_xy[i + 1]
        ab = b - a
        ab2 = float(np.dot(ab, ab))
        if ab2 <= 1e-9:
            snap = a
            t = 0.0
        else:
            t = float(np.dot(point_xy - a, ab) / ab2)
            t = max(0.0, min(1.0, t))
            snap = a + t * ab

        d = float(np.linalg.norm(point_xy - snap))
        if d < best_dist:
            best_dist = d
            seg_len = cum_m[i + 1] - cum_m[i]
            best_along = cum_m[i] + t * seg_len
            best_snap = snap

    return best_along, best_dist, best_snap


def interpolate_latlng_from_along(along_m: float, ref: RouteReference) -> tuple[float, float]:
    along_m = float(np.clip(along_m, 0.0, ref.total_m))
    idx = int(np.searchsorted(ref.cumulative_m, along_m, side="right") - 1)
    idx = max(0, min(idx, len(ref.xy) - 2))

    a = ref.xy[idx]
    b = ref.xy[idx + 1]
    seg_start = ref.cumulative_m[idx]
    seg_end = ref.cumulative_m[idx + 1]
    seg_len = max(1e-9, seg_end - seg_start)
    t = (along_m - seg_start) / seg_len
    snap_xy = a + t * (b - a)

    lat = ref.lat0 + (snap_xy[1] / 111320.0)
    lng = ref.lng0 + (snap_xy[0] / (111320.0 * math.cos(math.radians(ref.lat0))))
    return float(lat), float(lng)


def load_sessions(csv_dir: Path) -> list[dict]:
    sessions: list[dict] = []
    files = sorted(csv_dir.glob("session_*.csv"))
    total = len(files)

    for idx, file_path in enumerate(files, start=1):
        session_id = session_id_from_name(file_path.name)
        if session_id is None:
            continue

        df = None
        for encoding in ["utf-8", "utf-8-sig", "latin1", "cp1252"]:
            try:
                df = pd.read_csv(file_path, encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        if df is None:
            continue
        required = {"Timestamp", "Latitude", "Longitude"}
        if not required.issubset(df.columns):
            continue

        df = df.copy()
        # Mixed ISO formats are present (with and without fractional seconds).
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce", format="mixed")
        df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
        df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")

        class_col = None
        header_norm = {str(c).strip().lower().replace("_", "").replace(" ", ""): c for c in df.columns}
        for key in ["vehicleclass", "vehicletype", "busclass", "bustype", "class"]:
            if key in header_norm:
                class_col = header_norm[key]
                break

        df = df.dropna(subset=["Timestamp", "Latitude", "Longitude"]).sort_values("Timestamp")
        if len(df) < 5:
            continue

        start_ts = df["Timestamp"].iloc[0]
        route_type = classify_route_type_from_name(file_path.name)
        if route_type is None:
            route_type = classify_route_type_from_time(start_ts)
        if route_type is None:
            continue

        vehicle_class = ""
        if class_col is not None:
            for value in df[class_col].tolist():
                vehicle_class = normalize_vehicle_class(value)
                if vehicle_class:
                    break
        if not vehicle_class:
            vehicle_class = default_vehicle_class(route_type)

        sessions.append(
            {
                "session_id": session_id,
                "file_name": file_path.name,
                "route_type": route_type,
                "vehicle_class": vehicle_class,
                "start_ts": start_ts,
                "df": df.reset_index(drop=True),
            }
        )

        if idx % 10 == 0:
            print(f"Loaded {idx}/{total} files...", flush=True)

    return sessions


def build_reference(reference_session: dict, bin_m: float) -> RouteReference:
    points = reference_session["df"][["Latitude", "Longitude"]].drop_duplicates().to_numpy()
    lat0 = float(points[:, 0].mean())
    lng0 = float(points[:, 1].mean())
    xy = latlng_to_xy(points[:, 0], points[:, 1], lat0, lng0)
    cum_m = cumulative_lengths(xy)
    total_m = float(cum_m[-1])
    n_bins = int(math.ceil(total_m / bin_m))

    tree = cKDTree(xy) if cKDTree is not None and len(xy) > 0 else None

    return RouteReference(
        route_type=reference_session["route_type"],
        session_id=reference_session["session_id"],
        file_name=reference_session["file_name"],
        lat0=lat0,
        lng0=lng0,
        xy=xy,
        cumulative_m=cum_m,
        total_m=total_m,
        n_bins=n_bins,
        vertex_tree=tree,
    )


def match_session_to_reference(session: dict, ref: RouteReference, bin_m: float) -> pd.DataFrame:
    df = session["df"].copy()
    xy = latlng_to_xy(df["Latitude"].to_numpy(), df["Longitude"].to_numpy(), ref.lat0, ref.lng0)

    if ref.vertex_tree is not None and len(ref.xy) > 0:
        offroute, nearest_idx = ref.vertex_tree.query(xy)
        nearest_idx = np.asarray(nearest_idx, dtype=int)
        nearest_idx = np.clip(nearest_idx, 0, len(ref.cumulative_m) - 1)
        progress = ref.cumulative_m[nearest_idx]
    else:
        progress = np.zeros(len(df), dtype=float)
        offroute = np.zeros(len(df), dtype=float)
        for i in range(len(df)):
            along_m, dist_m, _ = project_point_to_polyline(xy[i], ref.xy, ref.cumulative_m)
            progress[i] = along_m
            offroute[i] = dist_m

    # Remove zig-zag noise by enforcing non-decreasing progress.
    progress = np.maximum.accumulate(progress)

    df["progress_m"] = progress
    df["offroute_m"] = offroute
    df["bin_idx"] = np.clip((df["progress_m"] // bin_m).astype(int), 0, max(0, ref.n_bins - 1))

    dt_s = df["Timestamp"].diff().dt.total_seconds().to_numpy()
    dp_m = df["progress_m"].diff().to_numpy()

    speed_kph = np.full(len(df), np.nan)
    valid = (dt_s > 0.5) & (dt_s <= 300) & (dp_m >= 0)
    speed_kph[valid] = np.clip((dp_m[valid] / dt_s[valid]) * 3.6, 0.5, 90.0)
    df["speed_kph"] = speed_kph

    end_ts = df["Timestamp"].iloc[-1]
    df["eta_remaining_min"] = (end_ts - df["Timestamp"]).dt.total_seconds() / 60.0

    return df


def weighted_mean(values: list[float], weights: list[float]) -> float:
    arr_v = np.asarray(values, dtype=float)
    arr_w = np.asarray(weights, dtype=float)
    denom = arr_w.sum()
    if denom <= 1e-9:
        return float(np.nan)
    return float((arr_v * arr_w).sum() / denom)


def build_route_profiles(matches: pd.DataFrame, ref: RouteReference, bin_m: float) -> pd.DataFrame:
    rows = []
    for (session_id, bin_idx), grp in matches.groupby(["session_id", "bin_idx"]):
        speed_values = grp["speed_kph"].to_numpy()
        if not np.isfinite(speed_values).any():
            continue
        speed = float(np.nanmedian(speed_values))
        if not np.isfinite(speed):
            continue
        rows.append({"session_id": session_id, "bin_idx": int(bin_idx), "session_bin_speed": speed})

    by_session_bin = pd.DataFrame(rows)
    if by_session_bin.empty:
        return pd.DataFrame(columns=["bin_idx", "avg_speed_kph", "session_support", "congestion", "lat", "lng"])

    coverage = (
        matches.groupby("session_id")["progress_m"]
        .agg(["min", "max"])
        .reset_index()
    )
    coverage["coverage_ratio"] = ((coverage["max"] - coverage["min"]) / max(1.0, ref.total_m)).clip(0.05, 1.0)

    merged = by_session_bin.merge(coverage[["session_id", "coverage_ratio"]], on="session_id", how="left")

    agg_rows = []
    for bin_idx, grp in merged.groupby("bin_idx"):
        speeds = grp["session_bin_speed"].tolist()
        weights = grp["coverage_ratio"].fillna(0.1).tolist()
        avg_speed = weighted_mean(speeds, weights)
        agg_rows.append(
            {
                "bin_idx": int(bin_idx),
                "avg_speed_kph": avg_speed,
                "session_support": int(grp["session_id"].nunique()),
            }
        )

    profile = pd.DataFrame(agg_rows)
    if profile.empty:
        return profile

    all_bins = pd.DataFrame({"bin_idx": np.arange(ref.n_bins, dtype=int)})
    profile = all_bins.merge(profile, on="bin_idx", how="left")

    global_median = float(np.nanmedian(profile["avg_speed_kph"].to_numpy()))
    if not np.isfinite(global_median):
        global_median = 22.0
    profile["avg_speed_kph"] = profile["avg_speed_kph"].fillna(global_median)
    profile["session_support"] = profile["session_support"].fillna(0).astype(int)

    free_flow = float(np.nanpercentile(profile["avg_speed_kph"].to_numpy(), 90))
    free_flow = max(15.0, free_flow)
    profile["congestion"] = (1.0 - (profile["avg_speed_kph"] / free_flow)).clip(0.0, 1.0)

    lat_list = []
    lng_list = []
    for bin_idx in profile["bin_idx"].tolist():
        along = (bin_idx + 0.5) * bin_m
        lat, lng = interpolate_latlng_from_along(along, ref)
        lat_list.append(lat)
        lng_list.append(lng)
    profile["lat"] = lat_list
    profile["lng"] = lng_list

    return profile


def build_training_table(
    all_matches: pd.DataFrame,
    profile_map: dict[str, pd.DataFrame],
    ref_map: dict[str, RouteReference],
) -> pd.DataFrame:
    rows = []

    for _, row in all_matches.iterrows():
        route_type = row["route_type"]
        profile = profile_map[route_type]
        ref = ref_map[route_type]

        bin_idx = int(row["bin_idx"])
        if len(profile) == 0:
            global_speed = 22.0
            support = 0
        else:
            p = profile.iloc[min(max(bin_idx, 0), len(profile) - 1)]
            global_speed = float(p["avg_speed_kph"])
            support = int(p["session_support"])

        start_ts = row["start_ts"]
        minute_of_day = int(start_ts.hour * 60 + start_ts.minute)

        rows.append(
            {
                "session_id": int(row["session_id"]),
                "route_type": 0 if route_type == "morning" else 1,
                "vehicle_class": 0 if str(row.get("vehicle_class", "")).lower().startswith("shuttle") else 1,
                "start_minute": minute_of_day,
                "weekday": int(start_ts.dayofweek),
                "progress_ratio": float(row["progress_m"] / max(1.0, ref.total_m)),
                "offroute_m": float(row["offroute_m"]),
                "speed_kph": float(row["speed_kph"]) if np.isfinite(row["speed_kph"]) else global_speed,
                "global_bin_speed_kph": global_speed,
                "bin_session_support": support,
                "target_eta_min": float(row["eta_remaining_min"]),
            }
        )

    train_df = pd.DataFrame(rows)
    train_df = train_df.replace([np.inf, -np.inf], np.nan).dropna()
    train_df = train_df[train_df["target_eta_min"] >= 0].reset_index(drop=True)
    return train_df


def train_models(train_df: pd.DataFrame, t0: float) -> tuple[dict, str, pd.DataFrame, list[str], dict]:
    feature_cols = [
        "route_type",
        "vehicle_class",
        "start_minute",
        "weekday",
        "progress_ratio",
        "offroute_m",
        "speed_kph",
        "global_bin_speed_kph",
        "bin_session_support",
    ]

    X = train_df[feature_cols]
    y = train_df["target_eta_min"]
    groups = train_df["session_id"]

    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=42)
    train_idx, test_idx = next(splitter.split(X, y, groups))

    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

    candidates: dict[str, object] = {
        "random_forest": RandomForestRegressor(
            n_estimators=300,
            random_state=42,
            n_jobs=-1,
            min_samples_leaf=5,
        ),
        "hist_gradient_boosting": HistGradientBoostingRegressor(
            random_state=42,
            max_depth=8,
            learning_rate=0.05,
            max_iter=500,
            min_samples_leaf=20,
        ),
    }

    if XGBRegressor is not None:
        candidates["xgboost"] = XGBRegressor(
            n_estimators=600,
            max_depth=8,
            learning_rate=0.04,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_alpha=0.0,
            reg_lambda=1.0,
            objective="reg:squarederror",
            random_state=42,
            n_jobs=-1,
        )

    metrics = []
    fitted = {}
    predictions: dict[str, np.ndarray] = {}
    xgb_history: dict | None = None

    for name, model in candidates.items():
        log_step(f"Training model: {name}", t0)
        if name == "xgboost":
            model.fit(
                X_train,
                y_train,
                eval_set=[(X_train, y_train), (X_test, y_test)],
                verbose=False,
            )
            xgb_history = model.evals_result()
        else:
            model.fit(X_train, y_train)

        pred = model.predict(X_test)
        mae = mean_absolute_error(y_test, pred)
        rmse = math.sqrt(mean_squared_error(y_test, pred))
        r2 = r2_score(y_test, pred)
        metrics.append({"model": name, "mae_min": mae, "rmse_min": rmse, "r2": r2})
        fitted[name] = model
        predictions[name] = pred

    metrics_df = pd.DataFrame(metrics).sort_values("mae_min").reset_index(drop=True)
    best_name = metrics_df.iloc[0]["model"]

    eval_artifacts = {
        "y_test": np.asarray(y_test),
        "predictions": predictions,
        "xgb_history": xgb_history,
    }
    return fitted, best_name, metrics_df, feature_cols, eval_artifacts


def evaluate_on_baseline_sessions(
    models: dict,
    feature_cols: list[str],
    all_matches: pd.DataFrame,
    profile_map: dict[str, pd.DataFrame],
    ref_map: dict[str, RouteReference],
    morning_ref: int,
    evening_ref: int,
) -> pd.DataFrame:
    baseline_subset = all_matches[
        ((all_matches["route_type"] == "morning") & (all_matches["session_id"] == morning_ref))
        | ((all_matches["route_type"] == "evening") & (all_matches["session_id"] == evening_ref))
    ].copy()

    if baseline_subset.empty:
        return pd.DataFrame(columns=["model", "mae_min", "rmse_min", "r2", "rows"])

    baseline_train_df = build_training_table(baseline_subset, profile_map, ref_map)
    if baseline_train_df.empty:
        return pd.DataFrame(columns=["model", "mae_min", "rmse_min", "r2", "rows"])

    X_base = baseline_train_df[feature_cols]
    y_base = baseline_train_df["target_eta_min"]

    rows = []
    for name, model in models.items():
        pred = model.predict(X_base)
        rows.append(
            {
                "model": name,
                "mae_min": float(mean_absolute_error(y_base, pred)),
                "rmse_min": float(math.sqrt(mean_squared_error(y_base, pred))),
                "r2": float(r2_score(y_base, pred)),
                "rows": int(len(y_base)),
            }
        )

    return pd.DataFrame(rows).sort_values("mae_min").reset_index(drop=True)


def export_training_plots(metrics_df: pd.DataFrame, eval_artifacts: dict, out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    # Model comparison chart.
    fig = plt.figure(figsize=(10, 5))
    ax = fig.add_subplot(1, 1, 1)
    x = np.arange(len(metrics_df))
    ax.bar(x - 0.2, metrics_df["mae_min"], width=0.4, label="MAE (min)")
    ax.bar(x + 0.2, metrics_df["rmse_min"], width=0.4, label="RMSE (min)")
    ax.set_xticks(x)
    ax.set_xticklabels(metrics_df["model"].tolist(), rotation=15)
    ax.set_ylabel("Minutes")
    ax.set_title("ETA Model Error Comparison")
    ax.legend()
    fig.tight_layout()
    path = out_dir / "training_metrics.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    written.append(path.as_posix())

    # Prediction scatter for each model.
    y_test = np.asarray(eval_artifacts.get("y_test", []), dtype=float)
    preds = eval_artifacts.get("predictions", {}) or {}
    if y_test.size > 0 and preds:
        n = len(preds)
        cols = 2
        rows = int(math.ceil(n / cols))
        fig = plt.figure(figsize=(12, 4 * rows))
        for i, (name, pred) in enumerate(preds.items(), start=1):
            ax = fig.add_subplot(rows, cols, i)
            ax.scatter(y_test, pred, s=8, alpha=0.35)
            min_v = float(min(np.min(y_test), np.min(pred)))
            max_v = float(max(np.max(y_test), np.max(pred)))
            ax.plot([min_v, max_v], [min_v, max_v], "r--", linewidth=1)
            ax.set_title(f"{name}: Predicted vs Actual ETA")
            ax.set_xlabel("Actual ETA (min)")
            ax.set_ylabel("Predicted ETA (min)")
        fig.tight_layout()
        path = out_dir / "pred_vs_actual.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        written.append(path.as_posix())

    # XGBoost learning curve if available.
    xgb_history = eval_artifacts.get("xgb_history")
    if xgb_history and "validation_0" in xgb_history and "validation_1" in xgb_history:
        train_rmse = xgb_history["validation_0"].get("rmse", [])
        valid_rmse = xgb_history["validation_1"].get("rmse", [])
        if train_rmse and valid_rmse:
            fig = plt.figure(figsize=(10, 5))
            ax = fig.add_subplot(1, 1, 1)
            ax.plot(train_rmse, label="Train RMSE")
            ax.plot(valid_rmse, label="Validation RMSE")
            ax.set_title("XGBoost Learning Curve")
            ax.set_xlabel("Boosting Round")
            ax.set_ylabel("RMSE")
            ax.legend()
            fig.tight_layout()
            path = out_dir / "xgboost_learning_curve.png"
            fig.savefig(path, dpi=160)
            plt.close(fig)
            written.append(path.as_posix())

    return written


def complete_sessions_with_profile(
    session_matches: dict[int, pd.DataFrame],
    session_meta: pd.DataFrame,
    profile_map: dict[str, pd.DataFrame],
    ref_map: dict[str, RouteReference],
    bin_m: float,
) -> pd.DataFrame:
    completed_rows = []

    for _, meta in session_meta.iterrows():
        session_id = int(meta["session_id"])
        route_type = meta["route_type"]
        profile = profile_map[route_type]
        ref = ref_map[route_type]

        if len(profile) == 0:
            continue

        observed = session_matches[session_id]
        observed_speed = observed.groupby("bin_idx")["speed_kph"].median()

        for bin_idx in range(ref.n_bins):
            speed = observed_speed.get(bin_idx, np.nan)
            if not np.isfinite(speed):
                speed = float(profile.iloc[bin_idx]["avg_speed_kph"])
                source = "imputed"
            else:
                source = "observed"

            completed_rows.append(
                {
                    "session_id": session_id,
                    "file_name": meta["file_name"],
                    "route_type": route_type,
                    "bin_idx": bin_idx,
                    "distance_m_start": float(bin_idx * bin_m),
                    "distance_m_end": float((bin_idx + 1) * bin_m),
                    "speed_kph": float(speed),
                    "source": source,
                }
            )

    return pd.DataFrame(completed_rows)


def export_snapped_csvs(
    sessions: list[dict],
    session_matches: dict[int, pd.DataFrame],
    ref_map: dict[str, RouteReference],
    snapped_out_dir: Path,
) -> int:
    snapped_out_dir.mkdir(parents=True, exist_ok=True)
    written = 0

    for session in sessions:
        session_id = session["session_id"]
        route_type = session["route_type"]
        ref = ref_map[route_type]
        matched = session_matches.get(session_id)
        if matched is None or matched.empty:
            continue

        out_df = matched.copy()
        snapped_lat = []
        snapped_lng = []
        for along in out_df["progress_m"].to_numpy():
            lat, lng = interpolate_latlng_from_along(float(along), ref)
            snapped_lat.append(lat)
            snapped_lng.append(lng)

        out_df["Latitude"] = snapped_lat
        out_df["Longitude"] = snapped_lng
        out_df["SnapProgressM"] = out_df["progress_m"].round(3)
        out_df["SnapOffrouteM"] = out_df["offroute_m"].round(3)
        out_df["SnapReferenceSession"] = ref.file_name
        out_df["SnapRouteType"] = route_type

        base_cols = list(session["df"].columns)
        extra_cols = ["SnapProgressM", "SnapOffrouteM", "SnapReferenceSession", "SnapRouteType"]
        ordered_cols = [c for c in base_cols if c in out_df.columns] + extra_cols
        out_df = out_df[ordered_cols]

        stem = Path(session["file_name"]).stem
        out_name = (stem + ".csv") if stem.endswith("_snapped") else (stem + "_snapped.csv")
        out_df.to_csv(snapped_out_dir / out_name, index=False)
        written += 1

    return written


def main() -> None:
    t0 = time.time()
    args = parse_args()
    log_step("Starting ETA training pipeline", t0)
    csv_dir = Path(args.csv_dir)
    out_dir = Path(args.out_dir)
    snapped_out_dir = Path(args.snapped_out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_step(f"Input CSV directory: {csv_dir.as_posix()}", t0)

    sessions = load_sessions(csv_dir)
    log_step(f"Loaded {len(sessions)} valid sessions", t0)
    if not sessions:
        raise RuntimeError("No valid sessions found with required columns and route naming.")

    morning_ref_session = next((s for s in sessions if s["session_id"] == args.morning_ref and s["route_type"] == "morning"), None)
    evening_ref_session = next((s for s in sessions if s["session_id"] == args.evening_ref and s["route_type"] == "evening"), None)

    if morning_ref_session is None:
        raise RuntimeError(f"Morning reference session {args.morning_ref} not found in morning (Home_to_Office) sessions.")
    if evening_ref_session is None:
        raise RuntimeError(f"Evening reference session {args.evening_ref} not found in evening (Office_to_Home) sessions.")

    log_step(
        f"Using references -> morning: {morning_ref_session['file_name']} | evening: {evening_ref_session['file_name']}",
        t0,
    )

    ref_map = {
        "morning": build_reference(morning_ref_session, args.bin_meters),
        "evening": build_reference(evening_ref_session, args.bin_meters),
    }
    log_step("Built route references and snap index", t0)

    match_rows = []
    session_match_map: dict[int, pd.DataFrame] = {}
    session_meta_rows = []

    total_sessions = len(sessions)
    for i, session in enumerate(sessions, start=1):
        route_type = session["route_type"]
        ref = ref_map[route_type]
        matched = match_session_to_reference(session, ref, args.bin_meters)

        observed_len_m = float(matched["progress_m"].max() - matched["progress_m"].min())
        coverage_ratio = observed_len_m / max(1.0, ref.total_m)

        matched = matched.assign(
            session_id=session["session_id"],
            file_name=session["file_name"],
            route_type=route_type,
            vehicle_class=session["vehicle_class"],
            start_ts=session["start_ts"],
            coverage_ratio=coverage_ratio,
        )

        match_rows.append(
            matched[
                [
                    "session_id",
                    "file_name",
                    "route_type",
                    "vehicle_class",
                    "start_ts",
                    "Timestamp",
                    "progress_m",
                    "bin_idx",
                    "offroute_m",
                    "speed_kph",
                    "eta_remaining_min",
                    "coverage_ratio",
                ]
            ]
        )
        session_match_map[session["session_id"]] = matched
        session_meta_rows.append(
            {
                "session_id": session["session_id"],
                "file_name": session["file_name"],
                "route_type": route_type,
                "coverage_ratio": coverage_ratio,
            }
        )

        if i % 3 == 0 or i == total_sessions:
            log_step(f"Snapped sessions: {i}/{total_sessions}", t0)

    all_matches = pd.concat(match_rows, ignore_index=True)
    session_meta_df = pd.DataFrame(session_meta_rows)
    log_step(f"Built matched table with {len(all_matches)} rows", t0)

    if csv_dir.resolve() == snapped_out_dir.resolve():
        snapped_written = 0
        log_step(
            f"Skipped snapped CSV export because input and output directory are the same: {csv_dir.as_posix()}",
            t0,
        )
    else:
        snapped_written = export_snapped_csvs(sessions, session_match_map, ref_map, snapped_out_dir)
        log_step(f"Exported {snapped_written} snapped CSV file(s) to {snapped_out_dir.as_posix()}", t0)

    profile_map = {}
    choke_rows = []
    for route_type in ["morning", "evening"]:
        ref = ref_map[route_type]
        subset = all_matches[all_matches["route_type"] == route_type].copy()
        profile = build_route_profiles(subset, ref, args.bin_meters)
        profile_map[route_type] = profile
        profile.to_csv(out_dir / f"route_profile_{route_type}.csv", index=False)
        log_step(f"Built profile for {route_type} with {len(profile)} bins", t0)

        if len(profile) > 0:
            route_chokes = profile[profile["session_support"] >= 3].copy()
            route_chokes = route_chokes.sort_values("congestion", ascending=False).head(15)
            route_chokes.insert(0, "route_type", route_type)
            choke_rows.append(route_chokes)

    train_df = build_training_table(all_matches, profile_map, ref_map)
    log_step(f"Built training table with {len(train_df)} rows", t0)
    if len(train_df) < 200:
        raise RuntimeError(
            f"Training table is too small ({len(train_df)} rows). Try collecting more sessions or lowering filters."
        )

    fitted_models, best_name, metrics_df, feature_cols, eval_artifacts = train_models(train_df, t0)
    log_step(f"Training complete. Best model: {best_name}", t0)

    baseline_metrics_df = evaluate_on_baseline_sessions(
        fitted_models,
        feature_cols,
        all_matches,
        profile_map,
        ref_map,
        args.morning_ref,
        args.evening_ref,
    )
    log_step("Evaluated models on baseline sessions", t0)

    written_plots = export_training_plots(metrics_df, eval_artifacts, out_dir)
    log_step(f"Exported {len(written_plots)} training plot(s)", t0)

    model_bundle = {
        "model": fitted_models[best_name],
        "best_model_name": best_name,
        "features": feature_cols,
        "route_references": {
            "morning": {
                "session_id": ref_map["morning"].session_id,
                "file_name": ref_map["morning"].file_name,
                "total_m": ref_map["morning"].total_m,
                "n_bins": ref_map["morning"].n_bins,
            },
            "evening": {
                "session_id": ref_map["evening"].session_id,
                "file_name": ref_map["evening"].file_name,
                "total_m": ref_map["evening"].total_m,
                "n_bins": ref_map["evening"].n_bins,
            },
        },
        "bin_meters": args.bin_meters,
    }

    joblib.dump(model_bundle, out_dir / "eta_model.joblib")
    metrics_df.to_csv(out_dir / "model_metrics.csv", index=False)
    baseline_metrics_df.to_csv(out_dir / "baseline_test_metrics.csv", index=False)
    train_df.to_csv(out_dir / "training_table.csv", index=False)
    log_step("Saved model and core metrics tables", t0)

    completed_df = complete_sessions_with_profile(
        session_match_map,
        session_meta_df,
        profile_map,
        ref_map,
        args.bin_meters,
    )
    completed_df.to_csv(out_dir / "sessions_completed_with_imputation.csv", index=False)
    log_step("Saved session completion table with imputation flags", t0)

    if choke_rows:
        choke_df = pd.concat(choke_rows, ignore_index=True)
    else:
        choke_df = pd.DataFrame(columns=["route_type", "bin_idx", "avg_speed_kph", "session_support", "congestion", "lat", "lng"])
    choke_df.to_csv(out_dir / "choke_points.csv", index=False)
    log_step("Saved choke point candidates", t0)

    summary = {
        "sessions_used": int(session_meta_df["session_id"].nunique()),
        "morning_sessions": int((session_meta_df["route_type"] == "morning").sum()),
        "evening_sessions": int((session_meta_df["route_type"] == "evening").sum()),
        "morning_reference": ref_map["morning"].file_name,
        "evening_reference": ref_map["evening"].file_name,
        "best_model": best_name,
        "metrics": metrics_df.to_dict(orient="records"),
        "baseline_test_metrics": baseline_metrics_df.to_dict(orient="records"),
        "outputs": {
            "model": str((out_dir / "eta_model.joblib").as_posix()),
            "metrics_csv": str((out_dir / "model_metrics.csv").as_posix()),
            "baseline_metrics_csv": str((out_dir / "baseline_test_metrics.csv").as_posix()),
            "training_table_csv": str((out_dir / "training_table.csv").as_posix()),
            "completed_sessions_csv": str((out_dir / "sessions_completed_with_imputation.csv").as_posix()),
            "choke_points_csv": str((out_dir / "choke_points.csv").as_posix()),
            "profile_morning_csv": str((out_dir / "route_profile_morning.csv").as_posix()),
            "profile_evening_csv": str((out_dir / "route_profile_evening.csv").as_posix()),
            "training_plots": written_plots,
            "snapped_csv_dir": str(snapped_out_dir.as_posix()),
        },
    }

    with open(out_dir / "training_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    log_step("Wrote training summary JSON", t0)
    print("Training complete.", flush=True)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
