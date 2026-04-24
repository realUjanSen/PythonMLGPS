import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd


SESSION_PATTERN = re.compile(r"session_(\d+)_")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate snapped copies for all session CSV files.")
    parser.add_argument("--csv-dir", default="csv", help="Input CSV folder.")
    parser.add_argument("--out-dir", default="csv_snapped", help="Output snapped CSV folder.")
    parser.add_argument("--morning-ref", type=int, default=43, help="Morning reference session id.")
    parser.add_argument("--evening-ref", type=int, default=35, help="Evening reference session id.")
    return parser.parse_args()


def session_id_from_name(name: str) -> int | None:
    m = SESSION_PATTERN.search(name)
    return int(m.group(1)) if m else None


def infer_route_type(file_name: str) -> str | None:
    lower = file_name.lower()
    if "home_to_office" in lower:
        return "morning"
    if "office_to_home" in lower:
        return "evening"
    return None


def read_csv_robust(path: Path) -> pd.DataFrame | None:
    for enc in ["utf-8", "utf-8-sig", "latin1", "cp1252"]:
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    return None


def build_reference_points(csv_dir: Path, ref_id: int) -> np.ndarray:
    candidates = sorted(csv_dir.glob(f"session_{ref_id:03d}_*.csv"))
    if not candidates:
        raise RuntimeError(f"Reference session {ref_id} not found in {csv_dir}.")

    df = read_csv_robust(candidates[0])
    if df is None:
        raise RuntimeError(f"Could not read reference CSV: {candidates[0].name}")

    if not {"Latitude", "Longitude"}.issubset(df.columns):
        raise RuntimeError(f"Missing Latitude/Longitude in reference CSV: {candidates[0].name}")

    ref = df[["Latitude", "Longitude"]].copy()
    ref["Latitude"] = pd.to_numeric(ref["Latitude"], errors="coerce")
    ref["Longitude"] = pd.to_numeric(ref["Longitude"], errors="coerce")
    ref = ref.dropna().drop_duplicates()

    if len(ref) < 2:
        raise RuntimeError(f"Reference CSV has too few valid points: {candidates[0].name}")

    return ref.to_numpy()


def cumulative_lengths(xy: np.ndarray) -> np.ndarray:
    if len(xy) < 2:
        return np.array([0.0])
    steps = np.sqrt(np.sum(np.diff(xy, axis=0) ** 2, axis=1))
    return np.concatenate([[0.0], np.cumsum(steps)])


def project_point_to_polyline(px: float, py: float, ref_xy: np.ndarray, cum_m: np.ndarray) -> tuple[float, float]:
    best_d2 = float("inf")
    best_along = 0.0

    for j in range(len(ref_xy) - 1):
        a = ref_xy[j]
        b = ref_xy[j + 1]
        ab = b - a
        ab2 = float(np.dot(ab, ab))

        if ab2 <= 1e-12:
            t = 0.0
            snap = a
        else:
            t = float(np.dot(np.array([px, py]) - a, ab) / ab2)
            t = max(0.0, min(1.0, t))
            snap = a + t * ab

        d2 = float(np.dot(np.array([px, py]) - snap, np.array([px, py]) - snap))
        if d2 < best_d2:
            best_d2 = d2
            best_along = float(cum_m[j] + t * (cum_m[j + 1] - cum_m[j]))

    return best_along, float(np.sqrt(best_d2))


def interpolate_xy_from_along(along_m: float, ref_xy: np.ndarray, cum_m: np.ndarray) -> tuple[float, float]:
    if len(ref_xy) == 0:
        return 0.0, 0.0
    if len(ref_xy) == 1:
        return float(ref_xy[0, 0]), float(ref_xy[0, 1])

    along_m = float(np.clip(along_m, 0.0, float(cum_m[-1])))
    idx = int(np.searchsorted(cum_m, along_m, side="right") - 1)
    idx = max(0, min(idx, len(ref_xy) - 2))

    a = ref_xy[idx]
    b = ref_xy[idx + 1]
    seg_start = float(cum_m[idx])
    seg_end = float(cum_m[idx + 1])
    seg_len = max(1e-9, seg_end - seg_start)
    t = (along_m - seg_start) / seg_len
    p = a + t * (b - a)
    return float(p[0]), float(p[1])


def rolling_median(values: np.ndarray, window: int = 7) -> np.ndarray:
    if len(values) == 0:
        return values
    window = max(3, int(window) | 1)
    half = window // 2
    out = np.empty_like(values, dtype=float)
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        out[i] = float(np.median(values[lo:hi]))
    return out


def elastic_progress_assignment(raw_along: np.ndarray, raw_dist: np.ndarray, total_m: float) -> np.ndarray:
    if len(raw_along) == 0:
        return raw_along

    smooth = rolling_median(raw_along, window=9)
    smooth = np.maximum.accumulate(smooth)

    q05 = float(np.quantile(smooth, 0.05))
    q95 = float(np.quantile(smooth, 0.95))
    if q95 - q05 < max(30.0, total_m * 0.05):
        q05 = float(np.min(smooth))
        q95 = float(np.max(smooth))
    q05 = max(0.0, min(q05, total_m))
    q95 = max(q05, min(q95, total_m))

    rank_line = np.linspace(q05, q95, len(smooth))

    # Lower-confidence points (farther from baseline) rely more on rank-based stretch.
    conf = np.exp(-np.clip(raw_dist, 0.0, 120.0) / 25.0)
    blended = conf * smooth + (1.0 - conf) * rank_line

    blended = np.maximum.accumulate(blended)
    blended = np.clip(blended, 0.0, total_m)
    return blended


def snap_points_to_reference(lat: np.ndarray, lng: np.ndarray, ref: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    # Elastic snapping to nearest polyline with sequence-aware monotonic stretch/compression.
    lat0 = float(np.nanmean(ref[:, 0]))
    meters_per_lat = 111320.0
    meters_per_lng = 111320.0 * max(0.2, np.cos(np.deg2rad(lat0)))

    ref_x = (ref[:, 1]) * meters_per_lng
    ref_y = (ref[:, 0]) * meters_per_lat
    ref_xy = np.column_stack([ref_x, ref_y])
    cum_m = cumulative_lengths(ref_xy)
    total_m = float(cum_m[-1]) if len(cum_m) > 0 else 0.0

    in_x = lng * meters_per_lng
    in_y = lat * meters_per_lat

    snapped_lat = np.array(lat, copy=True)
    snapped_lng = np.array(lng, copy=True)
    offroute_m = np.full(len(lat), np.nan)

    valid_mask = np.isfinite(lat) & np.isfinite(lng)
    valid_indices = np.where(valid_mask)[0]

    if len(ref) < 2:
        return snapped_lat, snapped_lng, offroute_m

    raw_along = np.full(len(lat), np.nan, dtype=float)
    raw_dist = np.full(len(lat), np.nan, dtype=float)

    for i in valid_indices:
        px = float(in_x[i])
        py = float(in_y[i])
        along, dist_m = project_point_to_polyline(px, py, ref_xy, cum_m)
        raw_along[i] = along
        raw_dist[i] = dist_m

    valid_mask2 = np.isfinite(raw_along)
    if not np.any(valid_mask2):
        return snapped_lat, snapped_lng, offroute_m

    assigned = elastic_progress_assignment(raw_along[valid_mask2], raw_dist[valid_mask2], total_m)
    idxs = np.where(valid_mask2)[0]
    for k, i in enumerate(idxs):
        sx, sy = interpolate_xy_from_along(float(assigned[k]), ref_xy, cum_m)
        snapped_lng[i] = sx / meters_per_lng
        snapped_lat[i] = sy / meters_per_lat
        offroute_m[i] = float(raw_dist[i])

    return snapped_lat, snapped_lng, offroute_m


def main() -> None:
    args = parse_args()
    csv_dir = Path(args.csv_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    morning_ref = build_reference_points(csv_dir, args.morning_ref)
    evening_ref = build_reference_points(csv_dir, args.evening_ref)

    files = sorted(csv_dir.glob("session_*.csv"))
    written = 0

    for idx, path in enumerate(files, start=1):
        route_type = infer_route_type(path.name)
        if route_type is None:
            continue

        df = read_csv_robust(path)
        if df is None:
            print(f"[{idx}/{len(files)}] SKIP decode failure: {path.name}")
            continue

        if not {"Latitude", "Longitude"}.issubset(df.columns):
            print(f"[{idx}/{len(files)}] SKIP missing lat/lng: {path.name}")
            continue

        out_df = df.copy()
        out_df["Latitude"] = pd.to_numeric(out_df["Latitude"], errors="coerce")
        out_df["Longitude"] = pd.to_numeric(out_df["Longitude"], errors="coerce")

        ref = morning_ref if route_type == "morning" else evening_ref
        snapped_lat, snapped_lng, offroute_m = snap_points_to_reference(
            out_df["Latitude"].to_numpy(), out_df["Longitude"].to_numpy(), ref
        )

        out_df["Latitude"] = snapped_lat
        out_df["Longitude"] = snapped_lng
        out_df["SnapReferenceSessionId"] = args.morning_ref if route_type == "morning" else args.evening_ref
        out_df["SnapRouteType"] = route_type
        out_df["SnapOffrouteM"] = offroute_m.round(3)

        out_name = path.stem + "_snapped.csv"
        out_df.to_csv(out_dir / out_name, index=False)
        written += 1

        if idx % 10 == 0 or idx == len(files):
            print(f"[{idx}/{len(files)}] processed, written={written}")

    print(f"Done. Snapped CSVs written: {written} -> {out_dir.as_posix()}")


if __name__ == "__main__":
    main()
