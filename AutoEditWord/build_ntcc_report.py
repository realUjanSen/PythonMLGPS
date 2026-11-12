from __future__ import annotations

import copy
import zipfile
from pathlib import Path
from lxml import etree

NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSMAP = {"w": NS}
W = f"{{{NS}}}"

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "Minor Project Report Template.docx"
OUTPUT = ROOT / "NTCC_GPS_ETA_Project_Report_Formatted_v2.docx"


def paragraph_text(paragraph):
    return "".join(paragraph.xpath(".//w:t/text()", namespaces=NSMAP))


def set_paragraph_text(paragraph, text):
    runs = paragraph.xpath("./w:r", namespaces=NSMAP)
    if runs:
        first_run = runs[0]
        for child in list(first_run):
            if child.tag != W + "rPr":
                first_run.remove(child)
        text_node = etree.SubElement(first_run, W + "t")
        if text[:1].isspace() or text[-1:].isspace():
            text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        text_node.text = text
        for run in runs[1:]:
            paragraph.remove(run)
        return

    run = etree.SubElement(paragraph, W + "r")
    text_node = etree.SubElement(run, W + "t")
    text_node.text = text


def replace_paragraphs(root, replacements, repeated=None):
    repeated = repeated or {}
    seen = {}
    paragraphs = root.xpath(".//w:body/w:p", namespaces=NSMAP)
    for paragraph in paragraphs:
        old = paragraph_text(paragraph)
        if old in repeated:
            index = seen.get(old, 0)
            values = repeated[old]
            if index < len(values):
                set_paragraph_text(paragraph, values[index])
                seen[old] = index + 1
                continue
        if old in replacements:
            set_paragraph_text(paragraph, replacements[old])


def replace_table_cells(root, replacements, repeated=None):
    repeated = repeated or {}
    seen = {}
    for cell in root.xpath(".//w:tc", namespaces=NSMAP):
        text = "".join(cell.xpath(".//w:t/text()", namespaces=NSMAP))
        replacement = None
        if text in repeated:
            index = seen.get(text, 0)
            values = repeated[text]
            if index < len(values):
                replacement = values[index]
                seen[text] = index + 1
        elif text in replacements:
            replacement = replacements[text]
        if replacement is not None:
            paragraphs = cell.xpath("./w:p", namespaces=NSMAP)
            if paragraphs:
                set_paragraph_text(paragraphs[0], replacement)
                for paragraph in paragraphs[1:]:
                    cell.remove(paragraph)


def set_run_font(run, size_half_points=24, keep_bold=True):
    rpr = run.find("./w:rPr", namespaces=NSMAP)
    if rpr is None:
        rpr = etree.Element(W + "rPr")
        run.insert(0, rpr)

    for tag in ("rFonts", "color", "sz", "szCs", "i", "iCs"):
        node = rpr.find(f"./w:{tag}", namespaces=NSMAP)
        if node is not None:
            rpr.remove(node)

    fonts = etree.Element(W + "rFonts")
    for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(W + attr, "Times New Roman")
    rpr.insert(0, fonts)

    size = etree.Element(W + "sz")
    size.set(W + "val", str(size_half_points))
    rpr.append(size)
    size_cs = etree.Element(W + "szCs")
    size_cs.set(W + "val", str(size_half_points))
    rpr.append(size_cs)

    if not keep_bold:
        for tag in ("b", "bCs"):
            node = rpr.find(f"./w:{tag}", namespaces=NSMAP)
            if node is not None:
                rpr.remove(node)


def apply_academic_formatting(root):
    paragraphs = root.xpath(".//w:body/w:p", namespaces=NSMAP)
    for index, paragraph in enumerate(paragraphs):
        ppr = paragraph.find("./w:pPr", namespaces=NSMAP)
        has_instruction_shading = bool(
            ppr is not None and ppr.find("./w:shd", namespaces=NSMAP) is not None
        )
        if ppr is None:
            ppr = etree.Element(W + "pPr")
            paragraph.insert(0, ppr)

        shading = ppr.find("./w:shd", namespaces=NSMAP)
        if shading is not None:
            ppr.remove(shading)

        if has_instruction_shading:
            spacing = ppr.find("./w:spacing", namespaces=NSMAP)
            if spacing is None:
                spacing = etree.SubElement(ppr, W + "spacing")
            spacing.set(W + "before", "0")
            spacing.set(W + "after", "120")
            spacing.set(W + "line", "360")
            spacing.set(W + "lineRule", "auto")
            for run in paragraph.xpath("./w:r", namespaces=NSMAP):
                set_run_font(run, 24, keep_bold=False)

    for cell in root.xpath(".//w:body/w:tbl/w:tr/w:tc", namespaces=NSMAP):
        for run in cell.xpath(".//w:r", namespaces=NSMAP):
            set_run_font(run, 22, keep_bold=True)


paragraph_replacements = {
    "MINOR PROJECT - I REPORT (ETMN101)": "NTCC PROJECT REPORT",
    "A Route-Aware Framework for Estimating Travel Time from GPS Trajectories": "A Route-Aware Machine Learning Framework for GPS-Based ETA Prediction",
    "A914138123021Under the guidance of": "A914138123021\nUnder the guidance of",
    "[DESIGNATION]": "Assistant Professor",
    "[INSTITUTE NAME]": "Amity Institute of Information Technology",
    "[UNIVERSITY NAME]": "Amity University Kolkata",
    "[ Write a comprehensive abstract of 300–500 words summarizing: (1) Background and problem statement, (2) Objectives of the study, (3) Methodology and tools/models used, (4) Key results and findings, (5) Conclusion and significance of the work. ]": (
        "This project presents a route-aware machine learning system for estimating the remaining travel time of recurring bus and shuttle journeys. "
        "Raw GPS recordings are affected by location noise, duplicate points, off-road drift, stale timestamps, and incomplete sessions. "
        "The project therefore treats route alignment and data quality as first-class parts of the prediction problem rather than sending raw coordinates directly to a regressor. "
        "Sessions are collected as CSV records containing timestamps and latitude/longitude coordinates, classified as morning Home-to-Office or evening Office-to-Home journeys, and aligned to a representative baseline route. "
        "The preprocessing pipeline projects each point onto the route polyline, calculates along-route progress and off-route distance, enforces monotonic progress, derives speed, and aggregates traffic behavior into fixed distance bins. "
        "A filename-anchored temporal quality filter removes stale points and truncates traces after long recording gaps. "
        "The resulting training table uses route type, departure minute, weekday, progress ratio, off-route distance, local speed, profile speed, and session support as features, with remaining travel time in minutes as the regression target. "
        "Random Forest, HistGradientBoosting, and XGBoost regressors are trained and compared using a session-aware GroupShuffleSplit. "
        "In the cleaned run, XGBoost was selected by weighted mean absolute error, achieving a test MAE of 16.35 minutes, RMSE of 29.97 minutes, and R² of 0.029. "
        "The result demonstrates a complete practical workflow from GPS collection through route visualization and ETA inference, while also showing that broader validation across route sessions remains necessary before deployment as a safety-critical navigation service."
    ),
    "Keywords: [keyword1], [keyword2], [keyword3], [keyword4], [keyword5]": "Keywords: GPS trajectory, ETA prediction, route snapping, regression, intelligent transportation systems",
    "1.1 Background of Stock Market Prediction2": "1.1 Background of GPS-Based ETA Prediction2",
    "1.2 Importance and Challenges of Forecasting3": "1.2 Importance and Challenges of GPS Route Estimation3",
    "1.3 Objective of the Research4": "1.3 Objectives of the Research4",
    "1.4 Scope and Contributions of the Study5": "1.4 Scope and Contributions of the Study5",
    "2.1 Review of Traditional Statistical Models (Sarima)8": "2.1 Review of GPS Data Preprocessing and Trajectory Cleaning8",
    "2.2 Review of Machine Learning Techniques (Xgboost)9": "2.2 Review of Traditional Machine Learning in Mobility Analysis9",
    "2.3 Review of Deep Learning Models (Lstm, Cnn)10": "2.3 Review of Deep Learning Models for Trajectory Sequence Modeling10",
    "2.3.1 Long Short-Term Memory (Lstm) Networks10": "2.3.1 Recurrent Sequence Models10",
    "2.3.2 Convolutional Neural Networks (Cnns)11": "2.3.2 Spatial Representation Models11",
    "2.4 Emerging Techniques (Gnns, Hybrid Models)13": "2.4 Emerging Techniques: Graph Neural Networks and Attention Mechanisms13",
    "2.4.1 Graph Neural Networks (Gnns)13": "2.4.1 Graph-Based Road Representations13",
    "2.4.2 Hybrid Models14": "2.4.2 Hybrid Spatial and Tabular Models14",
    "2.5 Research Gaps Identified16": "2.5 Research Gaps Identified16",
    "3.3 Model Architectures19": "3.3 Route-Aware Models and Inference Architecture19",
    "3.3  MODEL / APPROACH ARCHITECTURES": "3.3  ROUTE-AWARE MODELS AND INFERENCE ARCHITECTURE",
    "3.3.1 SARIMA19": "3.3.1 Route Baseline and GPS Snapping19",
    "3.3.2 LSTM20": "3.3.2 Random Forest Regression20",
    "3.3.3 CNN21": "3.3.3 Histogram Gradient Boosting21",
    "3.3.4 XGBoost21": "3.3.4 XGBoost Regression21",
    "3.3.5 GNN22": "3.3.5 Destination-Aware ETA Blending22",
    "3.3.6 Hybrid Model (CNN+XGBoost)23": "3.3.6 Session-Aware Blending and Choke Points23",
    "4.1 Hardware and Software Environment26": "4.1 Hardware and Software Environment26",
    "5.1 Performance Metrics29": "5.1 Performance Metrics29",
    "5.2 Comparison of Models29": "5.2 Comparison of Regression Models29",
    "5.2  COMPARISON OF MODELS / APPROACHES": "5.2  COMPARISON OF REGRESSION MODELS",
    "5.3.1  [Model/Approach 1] Output": "5.3.1  Random Forest Output",
    "5.3.2  [Model/Approach 2] Output": "5.3.2  Histogram Gradient Boosting Output",
    "5.3.3  [Model/Approach 3] Output": "5.3.3  XGBoost Output",
    "5.3.4  [Model/Approach 4] Output": "5.3.4  Validation and Data-Quality Findings",
    "5.3.5  [Model/Approach 5] Output": "5.3.5  Route Profile and Choke-Point Findings",
    "5.3.6  [Model/Approach 6] Output": "5.3.6  End-to-End Inference Output",
    "5.3.1 CNN Model Output31": "5.3.1 Random Forest Output31",
    "5.3.2 LSTM Model Output32": "5.3.2 Histogram Gradient Boosting Output32",
    "5.3.3 GNN Model Output33": "5.3.3 XGBoost Output33",
    "5.3.4 SARIMA Model Output34": "5.3.4 Validation and Data-Quality Findings34",
    "5.3.5 XGBoost Model Output34": "5.3.5 Route Profile and Choke-Point Findings34",
    "5.3.6 Hybrid CNN + XGBoost Output35": "5.3.6 End-to-End Inference Output35",
    "5.3.7 Synthesis of Insights36": "5.3.7 Synthesis of Insights36",
    "6.1 Real-World Use Cases38": "6.1 Real-World Use Cases38",
    "6.2 Potential Improvements39": "6.2 Potential Improvements39",
    "6.3 Limitations and How to Overcome Them40": "6.3 Limitations and How to Overcome Them40",
    "7.1 Summary of Findings42": "7.1 Summary of Findings42",
    "7.2 Contribution to Research and Practice43": "7.2 Contribution to Research and Practice43",
    "7.3 Final Thoughts43": "7.3 Final Thoughts43",
    "[ Provide the background of the study — context, domain overview, and motivation. (Approx. 400–600 words) ]": (
        "Urban commute ETA is a practical prediction problem in intelligent transportation systems. A passenger or operator needs more than a map position: the system must understand where the vehicle is along a recurring route, how quickly it is moving, and how traffic conditions differ across route segments. Raw GPS data is not immediately suitable for this purpose because satellite measurements can drift, repeat the same location, jump off-road, arrive at irregular intervals, or contain points from a later recording period.\n\n"
        "This project studies a route-aware approach for repeated Home-to-Office and Office-to-Home journeys. Instead of learning a global relationship between latitude and time, it creates a common route coordinate system. Each observation is projected onto a representative route baseline, giving it a meaningful distance-from-start value. Historical sessions are then aggregated into route profiles that describe typical speed, session coverage, and congestion for each distance bin.\n\n"
        "The central motivation is interpretability and robustness. A prediction can be explained in terms of route progress, observed speed, off-route distance, departure time, weekday, and known slow segments. The system also provides a map interface for examining and pruning noisy GPS traces before retraining."
    ),
    "[ Insert Figure 1.1 here — [Figure Caption] ]": "Figure 1.1. End-to-end GPS collection, route alignment, profile construction, and ETA inference workflow.",
    "[ Discuss the importance of the problem domain and key challenges faced. (Approx. 300–500 words) ]": (
        "Reliable ETA estimation supports passenger information, fleet monitoring, route planning, and retrospective analysis of service quality. For a repeated commute, even a modest improvement in ETA quality can reduce waiting uncertainty and help identify recurring congestion locations. The project is also a useful machine learning case study because the target is continuous, route-dependent, and derived from temporal observations.\n\n"
        "The principal challenges are data quality, route variation, and validation. GPS noise can create false movement or false stops. A recorder may remain active after reaching the destination, creating an artificially long target duration. A phone reset can also restart session numbering, making filename IDs unsafe for incremental imports. Route variants around junctions make nearest-point matching ambiguous, while incomplete sessions create missing coverage in some bins. Finally, randomly splitting individual GPS rows would leak information from the same journey into both training and testing. The implementation addresses these issues through filename-anchored temporal filtering, monotonic route snapping, profile-based gap filling, and session-level group splitting."
    ),
    "[ Insert Figure 1.2 here — [Figure Caption] ]": "Figure 1.2. Sources of GPS noise and their effect on route progress and ETA targets.",
    "2.1  [LITERATURE SUB-SECTION TITLE]": "2.1  REVIEW OF GPS DATA PREPROCESSING AND TRAJECTORY CLEANING",
    "[ Review existing literature on sub-topic 1. Cite key papers, summarize findings, compare approaches, and note limitations. (Approx. 400–700 words) ]": "Raw GPS trajectories cannot be fed directly into machine learning models because they contain jitter, duplicate observations, irregular sampling, off-road drift, and stale records. Trajectory research commonly segments continuous paths into meaningful subtrajectories using changes in speed, direction, or time. Spatial filtering methods such as Kalman filtering and Douglas-Peucker simplification can reduce noise while preserving the general geometry of movement. For route ETA, however, aggressive simplification must not remove the temporal evidence needed to estimate remaining travel time. This project therefore combines temporal quality checks with route projection: points are anchored to the filename timestamp, traces are bounded to a realistic session window, long recording gaps are truncated, and remaining points are projected onto a representative route baseline. The approach is designed for repeated commute traces where consistent route progress is more useful than isolated raw coordinate accuracy.",
    "2.2  [LITERATURE SUB-SECTION TITLE]": "2.2  REVIEW OF TRADITIONAL MACHINE LEARNING IN MOBILITY ANALYSIS",
    "[ Review existing literature on sub-topic 2. Cite key papers, summarize findings, compare approaches, and note limitations. (Approx. 400–700 words) ]": "Classical machine learning models are widely used for tabularized mobility features such as speed distributions, acceleration, heading variation, route position, and time-of-day. Random Forest and Support Vector Machine methods are attractive because they are computationally practical and can handle heterogeneous features. Gradient-boosted trees extend this capability by learning nonlinear feature interactions and are effective for structured transportation data. Their limitation is that temporal structure is not learned automatically from a raw sequence; it must be represented through engineered variables such as progress ratio, local speed, route-bin speed, and session support. This project adopts that tabular approach because the target is remaining ETA on a known recurring route, not unrestricted next-coordinate generation. Grouped session validation is used to avoid treating adjacent points from one journey as independent evidence.",
    "2.3  [LITERATURE SUB-SECTION TITLE]": "2.3  REVIEW OF DEEP LEARNING MODELS FOR TRAJECTORY SEQUENCE MODELING",
    "[ Review existing literature on sub-topic 3. Cite key papers, summarize findings, compare approaches, and note limitations. (Approx. 400–700 words) ]": "Recurrent Neural Networks and Long Short-Term Memory networks are frequently used for sequential movement modelling because they can represent temporal dependencies across ordered observations. Convolutional and attention-based architectures can also learn local or long-range sequence patterns. These approaches are relevant when the research objective is next-location prediction, long-horizon trajectory forecasting, or learning across many unrelated road networks. They also require larger and more consistently sampled datasets than are currently available in this project. The present system deliberately uses route-aligned tabular regression instead: route geometry is made explicit through snapping and distance bins, while temporal effects are represented through departure minute, weekday, speed, and remaining progress. Deep sequence models remain a future extension rather than an implemented experiment in this report.",
    "2.4  RESEARCH GAPS IDENTIFIED": "2.4  RESEARCH GAPS IDENTIFIED",
    "Despite rapid methodological advances, several critical gaps remain:": "Despite rapid methodological advances, several critical gaps remain for a practical route-specific ETA system:",
    "[Research Gap 1 — describe the unresolved problem or limitation in existing literature]": "Robustness to severe urban GPS noise and fused-location bias remains difficult when repeated points or off-road jumps appear in a trace.",
    "[Research Gap 2 — describe the unresolved problem or limitation in existing literature]": "Irregular time gaps and recorder restarts can corrupt the target unless session boundaries are explicitly validated.",
    "[Research Gap 3 — describe the unresolved problem or limitation in existing literature]": "Heavy graph and deep models may be unnecessary or impractical for a small route-specific dataset and local edge deployment.",
    "[Research Gap 4 — describe the unresolved problem or limitation in existing literature]": "Many evaluations split individual rows rather than sessions, allowing highly correlated observations from one journey to leak across partitions.",
    "[Research Gap 5 — describe the unresolved problem or limitation in existing literature]": "Few lightweight workflows combine human route pruning, reproducible snapping, congestion profiles, and ETA inference in one tool.",
    "The primary objectives of this research are:": "The primary objectives of this project are:",
    "a)  Objective 1 — [describe]": "a) Build a repeatable pipeline for collecting and importing GPS session CSV files.",
    "b)  Objective 2 — [describe]": "b) Clean and align noisy GPS traces to route-specific baseline polylines.",
    "c)  Objective 3 — [describe]": "c) Construct speed, congestion, progress, and coverage features for ETA regression.",
    "d)  Objective 4 — [describe]": "d) Compare Random Forest, HistGradientBoosting, and XGBoost using session-aware validation.",
    "e)  Objective 5 — [describe]": "e) Deliver a browser interface for route inspection, pruning, profile visualization, and inference.",
    "[ Define the scope of the study (data domain, methodological breadth, evaluation framework, implementation). List the key contributions of this research. (Approx. 300–500 words) ]": (
        "The project scope covers recurring bus and shuttle journeys represented by timestamped GPS points. The implementation includes raw CSV ingestion, route classification, temporal quality control, baseline construction, polyline projection, elastic progress assignment, speed calculation, route-bin profiling, supervised regression, evaluation, command-line inference, and a Node.js/Leaflet web interface. The work focuses on remaining travel time to the route end or to a selected destination along the baseline.\n\n"
        "The main contributions are: (1) a route-aware representation that converts noisy latitude/longitude traces into comparable along-route progress; (2) a practical data-quality policy for stale points, long gaps, and post-arrival recording tails; (3) congestion-aware profile features with session support and choke-point reporting; (4) leakage-resistant model evaluation at the session level; and (5) a usable inspection workflow in which an operator can erase noise and save edited data back to the selected CSV source. The project does not claim city-wide routing, turn-by-turn navigation, or safety-critical autonomy."
    ),
    "[ Describe the dataset: source, time range, variables collected (e.g., Open, High, Low, Close, Volume). Include sample data snapshot. (Approx. 200–400 words) ]": (
        "The dataset consists of repeated commute GPS sessions stored as CSV files under csv/. Each file is named with a session number, date, time, and direction, for example session_216_20261008_162055_Office_to_Home.csv. The raw schema includes Timestamp, Latitude, Longitude, Accuracy, Speed, Bearing, Altitude, Satellite, and Country fields. The model requires Timestamp, Latitude, and Longitude; other fields are retained for analysis and traceability.\n\n"
        "The project uses two route types: morning Home-to-Office and evening Office-to-Home. The training run used 175 valid sessions after temporal quality filtering. Morning and evening reference sessions were selected by ID 43 and 35 respectively. The imported data is not a public benchmark; it is a project-specific longitudinal collection. This makes careful validation and documentation particularly important because coverage, route choice, and recording quality vary between sessions."
    ),
    "[ Insert Figure 3.1.1 — Sample data snapshot ]": "Figure 3.1.1. Example GPS session CSV schema.",
    "[ Insert Figure 3.1.2 — Historical trend chart ]": "Figure 3.1.2. Repeated morning and evening route traces.",
    "[ Detail: missing value handling, normalization/scaling, feature engineering (technical indicators, lag features, etc.). (Approx. 300–500 words) ]": (
        "Preprocessing begins by reading session files with fallback encodings, parsing mixed timestamp formats, coercing coordinates to numeric values, dropping invalid GPS rows, and sorting by timestamp. The filename timestamp anchors the expected session start. Points more than 30 minutes before that anchor or more than 180 minutes after it are excluded. The trace is also truncated at the first gap longer than 20 minutes, preventing overnight points or post-arrival recording tails from creating impossible remaining-time targets.\n\n"
        "For route alignment, latitude and longitude are converted to a local metre-based coordinate system. Every point is projected to the nearest baseline polyline segment. The pipeline records along-route progress, perpendicular off-route distance, distance bin, and speed derived from successive progress and timestamp differences. Elastic progress assignment applies rolling-median smoothing, rank-based compression for low-confidence points, and a monotonic cumulative maximum. Missing speed observations are filled from the relevant route-bin profile when constructing training rows.\n\n"
        "The target is eta_remaining_min, calculated as the time from each observation to the final valid timestamp in that cleaned session. Features include route type, start minute, weekday, progress ratio, offroute_m, speed_kph, global_bin_speed_kph, and bin_session_support."
    ),
    "[ Insert Figure 3.2 — Data Preprocessing Pipeline ]": "Figure 3.2. Temporal filtering, route snapping, feature engineering, and profile generation pipeline.",
    "The following approaches were implemented and evaluated:": "The system combines route geometry, statistical profiles, and three supervised regression models:",
    "3.3.1  [Model / Approach 1]": "3.3.1  Route Baseline and GPS Snapping",
    "[ Describe the architecture, working principle, hyper-parameters, and rationale for selecting this approach. (Approx. 200–350 words) ]": (
        "A representative morning and evening session defines a route baseline. Coordinates are transformed into a local Cartesian frame and cumulative polyline distances are calculated. Each point from every session is projected onto this baseline. The projection produces progress in metres and off-route distance, while the elastic assignment and monotonic clamp reduce regressions caused by GPS noise. A bin index is generated using a 120-metre interval. This is not a predictive model by itself; it is the geometric representation that makes the regression features comparable across sessions."
    ),
    "[ Insert Figure 3.2.1 — Architecture / Process diagram ]": "Figure 3.2.1. Projection of noisy GPS observations onto a route baseline.",
    "3.3.2  [Model / Approach 2]": "3.3.2  Random Forest Regression",
    "[ Insert Figure 3.2.2 — Architecture / Process diagram ]": "Figure 3.2.2. Random Forest ensemble regression for remaining ETA.",
    "3.3.3  [Model / Approach 3]": "3.3.3  Histogram Gradient Boosting",
    "[ Insert Figure 3.2.3 — Architecture / Process diagram ]": "Figure 3.2.3. Histogram Gradient Boosting regression workflow.",
    "3.3.4  [Model / Approach 4]": "3.3.4  XGBoost Regression",
    "[ Insert Figure 3.2.4 — Architecture / Process diagram ]": "Figure 3.2.4. XGBoost feature-to-ETA regression workflow.",
    "3.3.5  [Model / Approach 5]": "3.3.5  Destination-Aware ETA Blending",
    "[ Insert Figure 3.2.5 — Architecture / Process diagram ]": "Figure 3.2.5. Full-route model ETA blended with local destination-segment ETA.",
    "3.3.6  [Hybrid / Combined Approach]": "3.3.6  Session-Aware Blending and Choke Points",
    "[ Insert Figure 3.2.6 — Architecture / Process diagram ]": "Figure 3.2.6. Session statistics and congestion choke-point outputs.",
    "[ Describe train/test split strategy (e.g., 80/20 chronological split), cross-validation method (e.g., TimeSeriesSplit), hyperparameter tuning approach, and loss function. (Approx. 300–400 words) ]": (
        "The supervised table is split with GroupShuffleSplit using session_id as the group. A session is therefore kept entirely in either the training or held-out partition, reducing leakage from highly correlated adjacent GPS rows. The split uses a fixed random state of 42 and a 25 percent test fraction. Each candidate regressor is trained with sample weights that emphasize rows earlier in a journey, where remaining ETA is more consequential.\n\n"
        "The candidate models are RandomForestRegressor with 300 trees, HistGradientBoostingRegressor with max depth 8, learning rate 0.05, 500 iterations, and minimum leaf size 20, and XGBRegressor with 200 estimators, depth 8, learning rate 0.04, subsampling, and column subsampling. Models are compared using MAE, RMSE, R², and weighted variants of those metrics. The selected model is the model with the lowest weighted MAE. Additional diagnostics include prediction scatter plots, residual histograms, training-progress curves, and baseline-session evaluation."
    ),
    "[ Insert Figure 3.4 — Training and Validation Workflow ]": "Figure 3.4. Session-grouped training, validation, model selection, and artifact export.",
    "All experiments were conducted on a system with the following specifications:": "The project was developed and executed on a Windows workstation using VS Code. The pipeline is CPU-compatible and uses parallel workers for session snapping and ensemble training; no dedicated GPU is required for the baseline workflow. The exact hardware is intentionally not claimed because it is not recorded as a controlled experiment variable. Reproducibility is based on the source code, command-line parameters, fixed random seed, raw CSV data, and generated output tables.",
    "[ List all libraries and frameworks with version numbers and their specific purpose in the project. ]": "The main tools are Python with pandas and NumPy for tabular and numerical processing; scikit-learn for regression, metrics, and grouped splitting; XGBoost for gradient boosting; SciPy cKDTree for spatial indexing; joblib for model serialization and parallel work; Matplotlib for diagnostics; Node.js with Express for the local web server; and Leaflet in the browser for route maps. The package manifest pins Express to the 4.18.x series, while Python package versions should be captured with pip freeze for a formally reproducible release.",
    "[ Insert Figure 4.2 — Libraries and Frameworks summary diagram ]": "Figure 4.2. Python ML pipeline and Node.js/Leaflet application stack.",
    "Environment Management: Document all library versions (e.g., requirements.txt / conda export).": "Environment Management: Keep a Python requirements file and the existing package-lock.json for Node dependencies.",
    "Random Seeds: Set seeds for Python random, NumPy, and all deep learning frameworks.": "Random Seeds: The model candidates use fixed random_state=42 where supported; NumPy operations are deterministic for the recorded pipeline.",
    "Data Splits: Use fixed chronological indices for train/validation/test splits.": "Data Splits: Use the fixed GroupShuffleSplit session partition and report the session IDs or seed with each experiment.",
    "[ Define each evaluation metric used (e.g., MAE, RMSE, R², MAPE, Accuracy, F1-Score). Justify the choice of metrics for this problem type. (Approx. 200–300 words) ]": (
        "MAE is the primary operational metric because it reports the average absolute ETA error directly in minutes and is easy to interpret. RMSE is also reported because it penalizes large mistakes more heavily, making it useful for detecting unstable predictions and outlier targets. R² measures the proportion of target variance explained relative to a mean predictor, although it can be negative when held-out generalization is poor. Weighted metrics use the training sample weights so earlier journey observations receive more emphasis. Classification metrics such as accuracy, precision, recall, and F1 are not applicable because the target is continuous remaining time."
    ),
    "[ Present the performance comparison table below and provide a high-level summary of findings. ]": "The cleaned held-out results show that XGBoost achieved the lowest weighted MAE and was selected as the final model. The three regressors remain close in MAE, so model selection should be interpreted together with route coverage and session-level diagnostics rather than as evidence of universal superiority.",
    "[ Describe model 1 predictions vs. actuals: visual trends, error patterns, strengths, weaknesses. (Approx. 150–250 words) ]": "Random Forest provides a strong non-parametric baseline and handles mixed route and traffic features without scaling. In the cleaned run it achieved MAE 16.72 minutes and RMSE 31.42 minutes. Its ensemble averages can produce stable predictions, but it may form horizontal bands when many observations have similar feature combinations. The model is also sensitive to the coverage and representativeness of the sessions used to build the trees.",
    "[ Insert Figure 5.3.1.1 — Predicted vs. Actual ]": "Figure 5.3.1.1. Random Forest predicted versus actual remaining ETA.",
    "[ Insert Figure 5.3.1.2 — Forecast Chart ]": "Figure 5.3.1.2. Random Forest residual and training-progress diagnostics.",
    "[ Describe model 2 predictions vs. actuals: visual trends, error patterns, strengths, weaknesses. (Approx. 150–250 words) ]": "Histogram Gradient Boosting achieved MAE 17.73 minutes and RMSE 32.13 minutes. It models nonlinear feature interactions efficiently and provides staged training diagnostics. Its performance was slightly weaker than XGBoost and Random Forest on the grouped test partition. The results emphasize that a sophisticated learner cannot compensate for route sessions that do not represent the deployment conditions.",
    "[ Insert Figure 5.3.2.1 — Predicted vs. Actual ]": "Figure 5.3.2.1. Histogram Gradient Boosting predicted versus actual remaining ETA.",
    "[ Insert Figure 5.3.2.2 — Forecast Chart ]": "Figure 5.3.2.2. Histogram Gradient Boosting training-progress diagnostics.",
    "[ Describe model 3 predictions vs. actuals: visual trends, error patterns, strengths, weaknesses. (Approx. 150–250 words) ]": "XGBoost was selected in the cleaned run with MAE 16.35 minutes, RMSE 29.97 minutes, weighted MAE 18.03 minutes, and R² 0.029. Its regularized boosting structure captures interactions between progress, speed, route type, and profile context. The positive but modest held-out R² indicates improvement over the original corrupted-target experiment, while also showing that more representative sessions are still needed.",
    "[ Insert Figure 5.3.3.1 — Predicted vs. Actual ]": "Figure 5.3.3.1. XGBoost predicted versus actual remaining ETA.",
    "[ Insert Figure 5.3.3.2 — Forecast Chart ]": "Figure 5.3.3.2. XGBoost learning curve and validation diagnostics.",
    "[ Describe model 4 predictions vs. actuals: visual trends, error patterns, strengths, weaknesses. (Approx. 150–250 words) ]": "The data-quality investigation found that the original graphs were dominated by corrupted session boundaries. A recovered session contained a stale point from a different date, while other sessions continued across multi-hour gaps. Because the target was computed from the final timestamp, these errors created targets as large as approximately 28,794 minutes. Filename anchoring, a 180-minute session window, and 20-minute gap truncation removed these impossible targets before the final clean run.",
    "[ Insert Figure 5.3.4.1 — Predicted vs. Actual ]": "Figure 5.3.4.1. Original diagnostic plot showing corrupted-target patterns.",
    "[ Insert Figure 5.3.4.2 — Forecast Chart ]": "Figure 5.3.4.2. Cleaned-target validation diagnostics.",
    "[ Describe model 5 predictions vs. actuals: visual trends, error patterns, strengths, weaknesses. (Approx. 150–250 words) ]": "The route profiles summarize median speed and session support for each 120-metre bin. Congestion is computed relative to a free-flow speed percentile, and choke_points.csv reports high-congestion bins with sufficient session support. These outputs make the model more inspectable: a prediction can be accompanied by the route sections most likely to slow the trip rather than appearing as an unexplained scalar.",
    "[ Insert Figure 5.3.5.1 — Predicted vs. Actual ]": "Figure 5.3.5.1. Route profile speed and congestion by distance bin.",
    "[ Insert Figure 5.3.5.2 — Forecast Chart ]": "Figure 5.3.5.2. Choke-point locations and session support.",
    "[ Describe model 6 predictions vs. actuals: visual trends, error patterns, strengths, weaknesses. (Approx. 150–250 words) ]": "The deployed inference path combines the full-route model estimate with a local route-profile ETA. When a destination coordinate is supplied, both current and destination points are projected to route bins and the model estimate is scaled to the requested span. A session-aware option can blend a known session baseline with the model result. The command-line predictor and browser map therefore expose both a practical ETA and supporting route context.",
    "[ Insert Figure 5.3.6.1 — Predicted vs. Actual ]": "Figure 5.3.6.1. Browser route map with current position, destination, and congestion coloring.",
    "[ Insert Figure 5.3.6.2 — Forecast Chart ]": "Figure 5.3.6.2. Example JSON ETA inference output with choke points.",
    "[ Summarize cross-model themes: which approach excelled, patterns in deep vs. statistical methods, key takeaways for the domain. (Approx. 200–350 words) ]": "The main cross-model finding is that data representation and session quality matter at least as much as the choice among tree regressors. All three models improved materially after stale timestamps and long recording tails were removed. XGBoost achieved the best weighted MAE and was selected, but Random Forest remained competitive. Baseline-session metrics were much stronger than grouped held-out metrics, demonstrating why session-level validation is essential. The route profile and choke-point outputs improve transparency by connecting predictions to measurable route conditions. The system is therefore best understood as an end-to-end route analytics pipeline, not merely a standalone regressor.",
    "1)  [Use Case 1 — Title]": "1) Passenger ETA information",
    "[ Describe how the system/model can be deployed for this use case, its benefits and practical impact. (Approx. 150–250 words) ]": "A local or mobile client can use the current route position and departure time to display remaining travel time and expected arrival. The destination-aware mode supports estimates to a selected stop or point rather than only the full route end.",
    "2)  [Use Case 2 — Title]": "2) Fleet and route monitoring",
    "3)  [Use Case 3 — Title]": "3) Historical congestion analysis",
    "4)  [Use Case 4 — Title]": "4) GPS data quality operations",
    "[ Insert Figure 6.1 — Real World Applications Diagram ]": "Figure 6.1. Applications of route-aware ETA prediction and GPS quality monitoring.",
    "1)  [Improvement 1 — e.g., Transformer Architectures]": "1) More route and context data",
    "2)  [Improvement 2 — e.g., Reinforcement Learning Integration]": "2) Probabilistic ETA intervals",
    "3)  [Improvement 3 — e.g., Alternative / Multi-Modal Data Sources]": "3) External traffic and weather signals",
    "4)  [Improvement 4 — e.g., Automated Hyperparameter Optimization]": "4) Automated experiment tracking",
    "[ Describe this potential improvement, the expected benefit, and implementation pathway. (Approx. 100–200 words) ]": "Future experiments should add more route sessions, explicit route variants, stop locations, weather, calendar effects, and live traffic. These additions can improve generalization and help distinguish congestion from route geometry. A model registry and automated experiment metadata would make repeated retraining easier to audit.",
    "1)  [Limitation 1 — e.g., Sensitivity to Exogenous Shocks]": "1) Route-specific generalization",
    "2)  [Limitation 2 — e.g., Overfitting in Deep Models]": "2) GPS uncertainty and missing coverage",
    "3)  [Limitation 3 — e.g., Interpretability Challenges]": "3) Validation error remains material",
    "4)  [Limitation 4 — e.g., Data Snooping / Information Leakage]": "4) Generated profile dependence",
    "[ Describe this limitation and the proposed mitigation or overcoming strategy. (Approx. 100–200 words) ]": "The model is designed for repeated routes and may not transfer to unseen roads, unusual detours, or major disruptions. GPS fusion errors and incomplete recordings can still reduce quality. The mitigation is to monitor off-route distance, session support, data freshness, and residuals; collect more representative sessions; preserve grouped validation; and expose uncertainty or a low-confidence status when support is weak.",
    "[ Provide a concise, numerical summary of each model/approach performance. Reference the comparison table (Table 5.2.1). State which approach emerged as the best and why. (Approx. 300–400 words) ]": "The cleaned experiment used 175 valid sessions and 131,989 training rows. XGBoost achieved the best weighted MAE at 18.03 minutes and an unweighted MAE of 16.35 minutes, with RMSE 29.97 minutes and R² 0.029. Random Forest achieved MAE 16.72 minutes and RMSE 31.42 minutes. Histogram Gradient Boosting achieved MAE 17.73 minutes and RMSE 32.13 minutes. XGBoost was selected because it minimized weighted MAE, although the close scores indicate that better data coverage is likely to yield more benefit than changing algorithms alone. The cleaned target distribution contained no values above 180 minutes, eliminating the extreme labels that distorted the earlier graphs.",
    "[ Insert Figure 7.1 — Performance Comparison Summary Chart ]": "Figure 7.1. Cleaned model MAE and RMSE comparison.",
    "Fig 1.1  [Figure Caption — Chapter 1]  ........................................  X": "Fig 1.1  GPS ETA pipeline workflow  ........................................  X",
    "Fig 1.2  [Figure Caption — Chapter 1]  ........................................  X": "Fig 1.2  GPS noise and route-estimation challenges  ........................................  X",
    "Fig 2.1  [Figure Caption — Chapter 2]  ........................................  X": "Fig 2.1  Literature review figure  ........................................  X",
    "Fig 3.1  [Figure Caption — Chapter 3]  ........................................  X": "Fig 3.1  GPS session data schema  ........................................  X",
    "Fig 3.2  [Figure Caption — Chapter 3]  ........................................  X": "Fig 3.2  Data preprocessing pipeline  ........................................  X",
    "Fig 4.1  [Figure Caption — Chapter 4]  ........................................  X": "Fig 4.1  Software and library stack  ........................................  X",
    "Fig 5.1  [Figure Caption — Results]  ........................................  X": "Fig 5.1  Predicted versus actual ETA results  ........................................  X",
    "Fig 5.2  [Figure Caption — Results]  ........................................  X": "Fig 5.2  Model error comparison  ........................................  X",
    "Fig 6.1  [Figure Caption — Applications]  ........................................  X": "Fig 6.1  Operational applications  ........................................  X",
    "Fig 7.1  [Figure Caption — Conclusion]  ........................................  X": "Fig 7.1  Final model comparison  ........................................  X",
    "Table 1.1  [Table Caption]  ........................................  X": "Table 1.1  Project objectives and contributions  ........................................  X",
    "Table 2.1  [Table Caption]  ........................................  X": "Table 2.1  Literature review table  ........................................  X",
    "Table 3.1  [Table Caption]  ........................................  X": "Table 3.1  Training features and target  ........................................  X",
    "[1]  Author(s), \"Title of Paper,\" Journal/Conference Name, vol. X, no. Y, pp. ZZZ–ZZZ, Year.": "[1] Scikit-learn Developers, \"Scikit-learn User Guide: Supervised Learning,\" documentation, accessed November 2026.",
    "[2]  Author(s), Title of Book, Edition, Publisher, Year.": "[2] T. Chen and C. Guestrin, \"XGBoost: A Scalable Tree Boosting System,\" Proceedings of the 22nd ACM SIGKDD, 2016.",
    "[3]  Author(s), \"Title of Paper,\" arXiv:XXXX.XXXXX, Year.": "[3] W. McKinney, \"pandas: A Foundational Python Library for Data Analysis and Statistics,\" documentation, accessed November 2026.",
    "[4]  Author(s), \"Title of Paper,\" in Proc. Conference Name (CONF), Year, pp. XX–XX.": "[4] V. Agafonkin, \"Leaflet JavaScript Library Documentation,\" accessed November 2026.",
    "[5]  Website Name, \"Article Title,\" accessed [Month Year]. [Online]. Available: https://[URL]": "[5] Express.js Contributors, \"Express Web Framework Documentation,\" accessed November 2026.",
    "[ Highlight the academic and practical contributions: benchmarking novelty, hybrid model innovation, practical deployment guidance, and reproducibility. (Approx. 300–400 words) ]": "Academically, the project demonstrates how route representation and grouped validation affect a practical ETA regression task. Practically, it delivers a reproducible pipeline that imports sessions, cleans temporal anomalies, snaps routes, builds congestion profiles, compares models, and serves map-based predictions. The browser cleaner provides a human-in-the-loop quality-control step, while the CLI and JSON artifacts support repeatable inference. The work also documents an important negative result: apparently sophisticated model comparisons are not meaningful when session boundaries and target construction are corrupted.",
    "[ Offer forward-looking commentary: the evolving landscape of the field, adaptive ensemble strategies, future directions, and the importance of model transparency and continuous monitoring. (Approx. 300–400 words) ]": "The next stage is to move from a route-specific prototype toward a monitored mobility service. More sessions can support route variants, probabilistic intervals, calibration, and separate models for route segments. Online monitoring should detect drift in GPS quality, congestion, and prediction residuals. The current design is deliberately transparent: route progress, speed, profile support, and choke points can be inspected alongside the ETA. That transparency should remain central as richer models and external data sources are added.",
}

table_replacements = {
    "LSTM": "GPS",
    "Long Short-Term Memory": "Global Positioning System",
    "GNN": "ETA",
    "Graph Neural Networks": "Estimated Time of Arrival",
    "CNN": "CSV",
    "Convolutional Neural Networks": "Comma-Separated Values",
    "XGB": "XGBoost",
    "Extreme Gradient Boosting": "Extreme Gradient Boosting",
    "SARIMA": "MAE",
    "Seasonal Autoregressive Integrated Moving Average": "Mean Absolute Error",
    "ARIMA": "RMSE",
    "Autoregressive Integrated Moving Average": "Root Mean Square Error",
    "ML": "ML",
    "Machine Learning": "Machine Learning",
    "AI": "ITS",
    "Artificial Intelligence": "Intelligent Transportation Systems",
    "EMH": "ETA",
    "Efficient Market Hypothesis": "Estimated Time of Arrival",
    "SHAP": "GPS",
    "SHapley Additive exPlanations": "Global Positioning System",
    "RNN": "RF",
    "Recurrent neural networks": "Random Forest",
    "LRP": "GB",
    "Layer-Wise Relevance Propagation": "Gradient Boosting",
    "PACF": "CSV",
    "Partial Autocorrelation": "Comma-Separated Values",
    "RSI": "RMSE",
    "Relative Strength Index": "Root Mean Square Error",
    "MACD": "MAE",
    "Moving Average Convergence Divergence": "Mean Absolute Error",
    "RIL": "GPS",
    "Reliance Industries Limited": "Global Positioning System",
    "ReLU": "API",
    "Rectified Linear Unit": "Application Programming Interface",
    "AIC": "R²",
    "Akaike Information Criterion": "Coefficient of Determination",
    "GCN": "CLI",
    "Graph Convolutional Network": "Command-Line Interface",
    "VaR": "CSV",
    "Value-at-Risk": "Comma-Separated Values",
    "RL": "UI",
    "Reinforcement Learning": "User Interface",
    "[e.g., AMD Ryzen 7 / Intel Core i7]": "Multi-core CPU workstation",
    "[e.g., 16 GB DDR4]": "System-dependent; not used as a model input",
    "[e.g., 512 GB SSD]": "Local SSD storage",
    "[e.g., NVIDIA GTX 1650 / Integrated]": "Not required; CPU-compatible workflow",
    "[e.g., Windows 11 / Ubuntu 22.04]": "Windows",
    "[e.g., Anaconda, Jupyter Notebook / VS Code]": "VS Code, Python, Node.js",
    "[Library 1]": "pandas / NumPy",
    "[Version]": "Python environment",
    "[Purpose]": "Dataframes and numerical processing",
    "[Library 2]": "scikit-learn",
    "[Library 3]": "XGBoost",
    "[Library 4]": "Matplotlib / SciPy",
    "[Library 5]": "Node.js / Express / Leaflet",
    "[MSE]": "898.00",
    "[RMSE]": "29.97",
    "[MAE]": "16.35",
    "[R²]": "0.029",
    "[Model 1]": "XGBoost",
    "[Model 2]": "Random Forest",
    "[Model 3]": "HistGradientBoosting",
    "[Model 4]": "Not used",
    "[Model 5]": "Not used",
}

repeated_paragraph_replacements = {
    "[ Describe the architecture, working principle, hyper-parameters, and rationale for selecting this approach. (Approx. 200–350 words) ]": [
        "A representative morning and evening session defines a route baseline. Coordinates are transformed into a local Cartesian frame and cumulative polyline distances are calculated. Every point from each session is projected onto this baseline. The projection produces progress in metres and off-route distance, while elastic assignment and a monotonic clamp reduce regressions caused by GPS noise. A bin index is generated using a 120-metre interval. This geometric representation makes observations comparable across sessions before regression begins.",
        "RandomForestRegressor uses an ensemble of 300 decision trees with fixed random state 42 and parallel fitting. Each tree learns nonlinear relationships between route progress, speed, time-of-day, route type, and profile context. The ensemble is a robust baseline for mixed numerical features and does not require feature scaling. It was included because it is interpretable through feature behavior and resistant to isolated noisy rows, although it can average predictions into horizontal bands when feature combinations repeat.",
        "HistGradientBoostingRegressor uses histogram-based gradient boosting with maximum depth 8, learning rate 0.05, up to 500 iterations, and minimum leaf size 20. It builds trees sequentially, reducing residual error from previous stages. The method is efficient for large tabular datasets and captures nonlinear interactions without requiring neural-network infrastructure. Its staged predictions are also exported for training-progress diagnostics.",
        "XGBRegressor uses 200 boosted trees, depth 8, learning rate 0.04, 0.85 row subsampling, and 0.85 feature subsampling with a squared-error objective. XGBoost was selected for its regularized boosting behavior and its ability to model interactions between progress, speed, route type, and congestion context. It achieved the lowest weighted MAE in the cleaned experiment.",
        "Destination-aware inference is a deterministic blending layer rather than a fourth learned model. The current and destination coordinates are projected onto the route profile, the full-route model ETA is scaled to the requested progress span, and a local profile ETA is calculated segment by segment. Short destinations receive greater local-profile weight so local congestion is not washed out by the full-route estimate.",
        "Session-aware inference optionally reads session_statistics.csv and blends a matching session baseline with the model/local estimate. The system also returns choke_points.csv entries ahead of the current bin, including speed, congestion, coordinates, and session support. These outputs improve operational interpretability without changing the trained feature contract."
    ],
    "[ Describe how the system/model can be deployed for this use case, its benefits and practical impact. (Approx. 150–250 words) ]": [
        "A passenger-facing application can call the prediction endpoint with the current GPS position, route, departure time, and optional destination. It can display remaining minutes, arrival time, route support, and upcoming congestion points. This reduces uncertainty while keeping the result understandable to a user.",
        "An operator can compare sessions, route profiles, speed bins, and choke points to identify recurring delays. The session-aware output can support route review and service monitoring without requiring a separate fleet-management platform.",
        "The generated route profiles and session statistics can be used to compare morning and evening conditions, identify high-congestion bins, and measure how route performance changes over time. This supports data-informed decisions about departure windows and route variants.",
        "The browser cleaner provides human-in-the-loop quality control. An operator can overlay sessions, erase GPS noise, save all edited sessions to disk, and regenerate snapped data and model outputs. This makes data maintenance part of the application workflow rather than an opaque manual preprocessing step."
    ],
    "[ Describe this potential improvement, the expected benefit, and implementation pathway. (Approx. 100–200 words) ]": [
        "Collecting more complete sessions across weekdays, weather conditions, route variants, and traffic states would improve coverage and reduce uncertainty. The existing session-grouped pipeline can accept the additional files without changing its public prediction interface.",
        "A probabilistic regressor or conformal calibration layer could return an ETA interval alongside the point estimate. This would communicate confidence based on route support, distance from the baseline, and historical residuals.",
        "Traffic APIs, weather, calendar events, and road-closure information could be joined by timestamp and route bin. These features may explain conditions that cannot be inferred from historical GPS speed alone.",
        "Automated experiment tracking could record data fingerprints, session IDs, feature definitions, random seeds, metrics, and artifact paths for every run. This would improve reproducibility and make model regression easier to detect."
    ],
    "[ Describe this limitation and the proposed mitigation or overcoming strategy. (Approx. 100–200 words) ]": [
        "The model is route-specific and may not transfer to unseen roads or major diversions. The mitigation is to maintain separate route references and collect representative sessions for each supported route variant.",
        "GPS fusion can create clusters, off-road drift, missing points, and irregular sampling. The current snapping and temporal filters reduce these effects; future work should add explicit duplicate detection, uncertainty flags, and map-matched road data.",
        "The grouped test MAE remains about 16 minutes, so the system should not be treated as safety-critical navigation. More sessions, calibrated intervals, and time-based validation across future collection periods are needed.",
        "Route profiles and support features are derived from the available historical sessions, so sparse or biased coverage can affect predictions. The application should expose support counts and trigger retraining when route conditions drift."
    ]
}

repeated_table_replacements = {
    "[Version]": ["Python environment", "Python environment", "Python environment", "Python environment", "Node package versions"],
    "[Purpose]": [
        "Dataframes and numerical processing",
        "Regression, metrics, and grouped validation",
        "Gradient boosting regression",
        "Plots, spatial indexing, serialization, and parallel work",
        "Web server, browser map, and API delivery"
    ]
}


def main():
    with zipfile.ZipFile(TEMPLATE, "r") as source:
        document = etree.fromstring(source.read("word/document.xml"))
        replace_paragraphs(document, paragraph_replacements, repeated_paragraph_replacements)
        replace_table_cells(document, table_replacements, repeated_table_replacements)
        apply_academic_formatting(document)
        document_xml = etree.tostring(document, xml_declaration=True, encoding="UTF-8", standalone="yes")

        with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                data = document_xml if info.filename == "word/document.xml" else source.read(info.filename)
                target.writestr(info, data)

    print(OUTPUT)


if __name__ == "__main__":
    main()
