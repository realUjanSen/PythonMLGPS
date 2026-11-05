A Route-Aware Framework for Estimating Travel Time from GPS Trajectories
# ETA Prediction and GPS Session Analysis Pipeline

This project builds a machine learning pipeline for estimating remaining travel time (ETA) from GPS session data. It ingests raw route records, snaps noisy traces onto a route baseline, builds congestion-aware route profiles, trains a regression model, and exposes predictions through a Python CLI and a small web dashboard.

The system is designed for commute routes such as morning home-to-office and evening office-to-home journeys, with a model trained to estimate the remaining time until the end of the trip using route progress, speed, time-of-day, congestion, and off-route distance.

---

## Project purpose

The project answers a practical question:

> Given a vehicle's current GPS position, route, and departure time, how much time remains until it reaches the destination or route end?

The solution combines:

- GPS trace cleaning and snapping to a learned route reference
- route-level profiling by distance bin and congestion level
- session-aware aggregation of historical route behavior
- machine learning regression for ETA estimation
- visualization and prediction UI for analysis and operator use

---

## High-level architecture

The repository combines Python data science workflow with a lightweight Node.js web layer.

1. Data collection
   - Raw CSV sessions live under `csv/`.
   - Each file contains GPS points with timestamps and coordinates.

2. Route baseline creation
   - A representative session is selected for each route type.
   - The baseline route is projected into a dense polyline and converted to distance bins.

3. Session snapping
   - Every session is aligned onto the route baseline.
   - GPS drift and minor misalignment are corrected by projecting points onto the route polyline.
   - `progress_m`, `offroute_m`, and `bin_idx` are derived for every tracing point.

4. Route profiling
   - The model aggregates speed and congestion by distance bin.
   - This produces `route_profile_morning.csv` and `route_profile_evening.csv`.

5. Training
   - A supervised regression dataset is built from route progress and conditions.
   - Multiple models are compared: Random Forest, HistGradientBoostingRegressor, and optionally XGBoost.
   - The best performing model is saved as `model_outputs/eta_model.joblib`.

6. Prediction
   - `predict_eta.py` loads the trained bundle and computes ETA from current route state.
   - It can integrate route progress, current location, destination, off-route distance, and session-aware blending.

7. Visualization / UI
   - `server.js` serves the app and exposes API endpoints.
   - `index.html` and companion frontend scripts render a route map, profile, and prediction output.

---

## Repository structure

```text
.
├── README.md
├── app.js
├── server.js
├── index.html
├── styles.css
├── eta_model_app.html
├── eta_model_app.css
├── eta_model_app.js
├── eta_model_presentation.html
├── model_documentation.html
├── train_eta_model.py
├── predict_eta.py
├── fetch_recent_sessions.py
├── generate_snapped_csvs.py
├── package.json
├── package-lock.json
├── csv/
│   ├── session_...csv
│   └── ...
├── csv_snapped/
│   ├── session_..._snapped.csv
│   └── ...
├── model_outputs/
│   ├── eta_model.joblib
│   ├── route_profile_morning.csv
│   ├── route_profile_evening.csv
│   ├── training_summary.json
│   ├── model_metrics.csv
│   ├── baseline_test_metrics.csv
│   ├── training_table.csv
│   ├── choke_points.csv
│   ├── session_statistics.csv
│   └── *.png
└── node_modules/
```

---

## Core machine learning workflow

### 1) Loading raw GPS sessions

The training pipeline starts in `train_eta_model.py` with `load_sessions()`.

It scans the `csv/` folder for files matching `session_*.csv`, reads each file, and keeps only valid sessions that contain:

- `Timestamp`
- `Latitude`
- `Longitude`

The code normalizes timestamps, drops invalid rows, sorts records chronologically, and infers route type from the filename or from time-of-day heuristics.

Example route labels:

- `Home_to_Office` => morning route
- `Office_to_Home` => evening route

The project also tries to infer vehicle class and defaults to route-specific classes if no explicit class is available.

### 2) Building a route reference

Each route type has a reference session chosen from a known-good example (in the code, default references are morning session `43` and evening session `35`).

`build_reference()` does the following:

- reads the reference session's coordinates
- converts latitude/longitude to a local XY coordinate frame centered on the route's mean location
- computes cumulative route distance along the polyline
- creates a KD-tree for nearest-fit lookup when projecting other points onto the route

This gives a canonical route geometry for the morning and evening trips.

### 3) Projecting points onto the baseline route

For every session, the model runs `project_point_to_polyline()` and `match_session_to_reference()`.

This step:

- takes each GPS point
- projects it onto the nearest segment of the baseline route
- computes the along-route distance, `progress_m`
- computes `offroute_m`, the perpendicular deviation from the route
- assigns each point a `bin_idx` based on distance traveled along the route

This is crucial because raw GPS traces are noisy and may drift or deviate from the actual road centerline. The snapping logic stabilizes the route geometry before model fitting.

### 4) Elastic route progress assignment

The code uses `elastic_progress_assignment()` to smooth the raw progression metrics and avoid teleportation or regressive jumps caused by noisy GPS tracks.

The logic does the following:

- computes a rolling median over progress values
- rescales extreme points using a rank-based mapping
- enforces monotonic forward progress with a cumulative maximum clamp
- keeps the route-ordering logic consistent even when the user deviates slightly from the expected path

This makes the model more robust to short detours, GPS drift, and internal noise.

### 5) Route profiles and congestion features

After snapping is finished, `build_route_profiles()` aggregates speed by route bin.

For each route type and each distance bin:

- median speed is estimated across sessions
- session support is counted
- congestion is computed from speed relative to a free-flow baseline
- latitude/longitude for the bin is interpolated onto the route polyline

This creates route-level traffic features that the model can use to estimate time-to-go in each region.

The route profile is stored as:

- `route_profile_morning.csv`
- `route_profile_evening.csv`

The same script also writes `choke_points.csv`, which highlights bins with the strongest congestion risk.

### 6) Training dataset construction

`build_training_table()` creates a supervised learning dataset.

Each row represents a sampled point from a session and contains features such as:

- `route_type`
- `start_minute`
- `weekday`
- `progress_ratio`
- `offroute_m`
- `speed_kph`
- `global_bin_speed_kph`
- `bin_session_support`

The target label is:

- `target_eta_min` = ETA remaining in minutes at that point in the trip

The model also applies a sample weighting strategy so that points earlier in a journey matter more than very short future segments.

### 7) Model training

The training process in `train_models()` compares several regressors:

- RandomForestRegressor
- HistGradientBoostingRegressor
- XGBoostRegressor when available

The data is split using `GroupShuffleSplit`, which keeps session groups together across train/test boundaries. That helps prevent data leakage because points from the same trip should stay in the same partition.

The metrics recorded in `model_metrics.csv` include:

- MAE (mean absolute error)
- RMSE
- R²

The best model is selected by weighted MAE and then saved into the model bundle.

### 8) Output artifacts

The training run writes all of these files to `model_outputs/`:

- `eta_model.joblib` — trained model + metadata bundle
- `training_summary.json` — full JSON summary of training and outputs
- `model_metrics.csv` — per-model regression metrics
- `baseline_test_metrics.csv` — metrics on the route reference sessions
- `training_table.csv` — all model rows used for fitting
- `route_profile_morning.csv`
- `route_profile_evening.csv`
- `choke_points.csv`
- `session_statistics.csv`
- `sessions_completed_with_imputation.csv`
- `training_metrics.png`
- `pred_vs_actual.png`
- `residuals_hist.png`
- `random_forest_learning_curve.png`
- `hist_gradient_boosting_learning_curve.png`
- `rf_group_learning_curve.png`
- `accuracy_details.txt`

---

## Prediction logic

The runtime prediction code is in `predict_eta.py`.

`main()` loads:

- the trained joblib bundle from `model_outputs/eta_model.joblib`
- the route profile for the selected route
- route metadata for the baseline geometry

It then builds a feature row from the current state:

- route type
- start minute of the day
- weekday
- progress ratio or progress in meters
- off-route distance
- live or profile-based speed
- session support

This feature vector is passed to the trained regressor to predict the total remaining ETA for the route.

### Destination-aware ETA

If a destination point is supplied, the script computes:

- the destination's progress ratio along the route
- the remaining distance ratio to the destination
- a local ETA based on the route profile between current position and destination
- a blended ETA using a local profile weighting scheme

This is useful when the user wants ETA to a specific stop instead of full route completion.

### Session-aware blending

If a `--session-id` is provided, the script looks for a matching row in `session_statistics.csv` and blends the model's estimate with the historical table's session mean ETA. This is a lightweight personalization step that helps anchor predictions to a known route history.

### Example CLI usage

Predict full route ETA for morning route:

```bash
python predict_eta.py --route morning --start-time 08:15 --progress-ratio 0.30
```

Predict ETA to a destination:

```bash
python predict_eta.py \
  --route evening \
  --start-time 17:40 \
  --lat 22.5721 \
  --lng 88.4332 \
  --dest-lat 22.5988 \
  --dest-lng 88.3950
```

---

## Web app and dashboard

The Node.js layer provides a browser-based front end and API endpoints for interacting with the system.

### `server.js`

This Express server:

- serves static content from the workspace root
- exposes CSV discovery endpoints for the `csv/` and `csv_snapped/` directories
- returns route profile data in JSON
- exposes model summary information for frontend rendering
- supports CSV save, delete, and health-check operations

Relevant endpoints include:

- `GET /api/list-csv-files`
- `GET /api/health`
- `GET /api/model-summary`
- `GET /api/route-profile`
- `GET /api/dataset-info`
- `POST /api/save-csv`
- `GET /api/delete-csv`

### Frontend behavior

The JavaScript files build a route visualization dashboard for inspecting sessions and predictions:

- `app.js` — general app logic for CSV listing, filtering, and session interaction
- `eta_model_app.js` — route-map-based ETA prediction / route profiling UI
- `eta_model_app.html` — main ETA prediction dashboard

This UI can:

- load session CSV files
- render route geometry and traffic bins on a map
- select a current location and optional destination
- run ETA prediction via the Python backend
- display choke points and prediction details

---

## Data and preprocessing assumptions

The project expects GPS CSVs with a structure similar to this:

```csv
Timestamp,Latitude,Longitude,Accuracy
2026-09-15 16:36:04,22.581234,88.390112,12.0
2026-09-15 16:36:14,22.581310,88.390081,11.5
...
```

The training pipeline normalizes the data and assumes the route is repeated across multiple sessions with similar road geometry. This is a route-aware regression model rather than a generic global trip predictor.

---

## Setup and installation

### Python dependencies

Install the required packages:

```bash
pip install pandas numpy scikit-learn joblib matplotlib scipy xgboost
```

If you want a more complete environment setup, install:

```bash
pip install pandas numpy scikit-learn joblib matplotlib scipy xgboost tqdm
```

### Node.js dependencies

```bash
npm install
```

---

## Running the project

### Train the ETA model

From the project root:

```bash
python train_eta_model.py --csv-dir csv --morning-ref 43 --evening-ref 35 --bin-meters 120 --out-dir model_outputs --snapped-out-dir csv_snapped --workers 8
```

This will:

- load session files
- snap them to the route baseline
- generate route profiles and choke-point summaries
- train the regression models
- save outputs under `model_outputs/`

### Predict ETA with the trained model

```bash
python predict_eta.py --route morning --start-time 08:15 --progress-ratio 0.35
```

Or with more specific location-based inputs:

```bash
python predict_eta.py --route evening --start-time 17:45 --lat 22.572 --lng 88.423 --dest-lat 22.600 --dest-lng 88.395
```

### Start the web application

```bash
npm start
```

Then open:

```text
http://localhost:8000
```

---

## Model interpretation

This is not a black-box map model; it is a structured ETA regression system built around route geometry.

The key concept is that route progress is mapped to a common baseline. Once each trace is aligned to that route, the model learns relationships like:

- the later along the route you are, the less time remains
- more congestion increases the remaining travel time
- off-route distance and local speed are important correction factors
- time-of-day matters because traffic patterns differ between morning and evening commute windows

The model therefore works best when the route is repeated often enough to learn a stable geometry and congestion profile.

---

## Limitations and practical notes

- The model is route-specific: it is trained for morning/evening commute patterns and assumes a consistent route layout.
- Large route deviations or changed road conditions may require re-training.
- Performance depends on data quality, timestamp consistency, and session coverage.
- The snapped baseline generation and route profile estimation are both critical preprocessing steps; if these fail, prediction quality drops sharply.

---

## Summary

This repository implements a real-world GPS ETA prediction workflow:

- raw commute data is cleaned and aligned to a baseline route
- route congestion is modeled by distance bin
- multiple regression models are trained and compared
- the best model is saved and reused for inference
- a web visualization layer makes the data and predictions accessible

It is a complete, end-to-end machine learning project for temporal route estimation in a commuter mobility setting.

---

## Quick commands

```bash
# Train model
python train_eta_model.py --csv-dir csv --out-dir model_outputs --snapped-out-dir csv_snapped

# Predict ETA
python predict_eta.py --route morning --start-time 08:15 --progress-ratio 0.30

# Start dashboard
npm start
```
