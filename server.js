const express = require("express");
const fs = require("fs");
const path = require("path");
const { execFile } = require("child_process");

const app = express();
const PORT = 8000;
const CSV_FOLDERS = {
  original: path.join(__dirname, "csv"),
  snapped: path.join(__dirname, "csv_snapped")
};

function getSourceFolder(sourceRaw) {
  const source = String(sourceRaw || "original").toLowerCase();
  if (source === "snapped") return { source: "snapped", folder: CSV_FOLDERS.snapped };
  return { source: "original", folder: CSV_FOLDERS.original };
}

// Serve static files
app.use(express.static(__dirname));
app.use(express.json({ limit: "50mb" }));

function readCsvAsObjects(filePath) {
  if (!fs.existsSync(filePath)) return [];
  const raw = fs.readFileSync(filePath, "utf8").replace(/\r/g, "").trim();
  if (!raw) return [];
  const lines = raw.split("\n");
  if (lines.length < 2) return [];
  const headers = lines[0].split(",").map((h) => h.trim());
  const rows = [];
  for (let i = 1; i < lines.length; i += 1) {
    const cols = lines[i].split(",");
    if (cols.length === 0) continue;
    const obj = {};
    headers.forEach((h, idx) => {
      obj[h] = cols[idx] ?? "";
    });
    rows.push(obj);
  }
  return rows;
}

function readModelSummary() {
  const filePath = path.join(__dirname, "model_outputs", "training_summary.json");
  if (!fs.existsSync(filePath)) return null;
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

// List all CSV files in the csv/ folder
app.get("/api/list-csv-files", (req, res) => {
  try {
    const { source, folder } = getSourceFolder(req.query.source);

    if (!fs.existsSync(folder)) {
      return res.json([]);
    }

    const files = fs.readdirSync(folder)
      .filter(file => file.endsWith(".csv"))
      .sort()
      .map((fileName) => ({
        source,
        fileName,
        urlPath: `${source === "snapped" ? "csv_snapped" : "csv"}/${fileName}`
      }));

    res.json(files);
  } catch (error) {
    console.error("Error listing CSV files:", error);
    res.status(500).json({ error: "Failed to list CSV files" });
  }
});

app.get("/api/health", (req, res) => {
  try {
    const csvCount = fs.existsSync(CSV_FOLDERS.original)
      ? fs.readdirSync(CSV_FOLDERS.original).filter((file) => file.endsWith(".csv")).length
      : 0;
    const snappedCount = fs.existsSync(CSV_FOLDERS.snapped)
      ? fs.readdirSync(CSV_FOLDERS.snapped).filter((file) => file.endsWith(".csv")).length
      : 0;

    res.json({
      status: "online",
      pid: process.pid,
      killCommand: `Stop-Process -Id ${process.pid} -Force`,
      uptimeSeconds: Math.round(process.uptime()),
      csvCount,
      snappedCount,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    console.error("Health check failed:", error);
    res.status(500).json({ status: "offline" });
  }
});

// Delete a CSV file
app.get("/api/delete-csv", (req, res) => {
  try {
    const { source, folder } = getSourceFolder(req.query.source);
    const fileName = req.query.file;
    if (!fileName || fileName.includes("..") || fileName.includes("/")) {
      return res.status(400).json({ error: "Invalid file name" });
    }

    const filePath = path.join(folder, fileName);
    
    // Ensure the file is in the csv folder
    if (!filePath.startsWith(folder)) {
      return res.status(400).json({ error: "Invalid file path" });
    }

    if (!fs.existsSync(filePath)) {
      return res.status(404).json({ error: "File not found" });
    }

    // Delete the raw file
    fs.unlinkSync(filePath);

    // If deleting from original (raw) folder, also delete the corresponding snapped file
    if (source === "original") {
      const stem = fileName.replace(/\.csv$/i, "");
      const snappedFileName = stem + "_snapped.csv";
      const snappedPath = path.join(CSV_FOLDERS.snapped, snappedFileName);
      
      if (fs.existsSync(snappedPath)) {
        try {
          fs.unlinkSync(snappedPath);
          res.json({ success: true, message: `Deleted ${fileName} and corresponding snapped file` });
        } catch (err) {
          console.warn(`Could not delete snapped file ${snappedFileName}:`, err.message);
          res.json({ success: true, message: `Deleted ${fileName} but could not delete snapped file` });
        }
      } else {
        res.json({ success: true, message: `Deleted ${fileName}` });
      }
    } else {
      res.json({ success: true, message: `Deleted ${fileName}` });
    }
  } catch (error) {
    console.error("Error deleting file:", error);
    res.status(500).json({ error: "Failed to delete file" });
  }
});

app.post("/api/save-csv", (req, res) => {
  try {
    const payload = req.body || {};
    const files = Array.isArray(payload.files)
      ? payload.files
      : payload.fileName && payload.csvText
        ? [{ fileName: payload.fileName, csvText: payload.csvText }]
        : [];

    if (files.length === 0) {
      return res.status(400).json({ error: "No CSV files provided" });
    }

    const saved = [];
    for (const file of files) {
      const fileName = String(file.fileName || "");
      const csvText = String(file.csvText || "");

      if (!fileName || fileName.includes("..") || fileName.includes("/") || fileName.includes("\\")) {
        return res.status(400).json({ error: `Invalid file name: ${fileName}` });
      }

      const filePath = path.join(CSV_FOLDERS.original, fileName);
      if (path.dirname(filePath) !== CSV_FOLDERS.original) {
        return res.status(400).json({ error: `Invalid file path: ${fileName}` });
      }

      fs.writeFileSync(filePath, csvText, "utf8");
      saved.push(fileName);
    }

    res.json({ success: true, saved });
  } catch (error) {
    console.error("Error saving CSV file(s):", error);
    res.status(500).json({ error: "Failed to save CSV file(s)" });
  }
});

app.get("/api/model-summary", (req, res) => {
  try {
    const summary = readModelSummary();
    if (!summary) {
      return res.status(404).json({ error: "Model summary not found. Train model first." });
    }
    res.json(summary);
  } catch (error) {
    console.error("Error reading model summary:", error);
    res.status(500).json({ error: "Failed to read model summary" });
  }
});

app.get("/api/route-profile", (req, res) => {
  try {
    const route = String(req.query.route || "morning").toLowerCase();
    if (!["morning", "evening"].includes(route)) {
      return res.status(400).json({ error: "route must be morning or evening" });
    }

    const filePath = path.join(__dirname, "model_outputs", `route_profile_${route}.csv`);
    const rows = readCsvAsObjects(filePath).map((r) => ({
      bin_idx: Number(r.bin_idx),
      avg_speed_kph: Number(r.avg_speed_kph),
      session_support: Number(r.session_support),
      congestion: Number(r.congestion),
      lat: Number(r.lat),
      lng: Number(r.lng),
    }));
    res.json(rows);
  } catch (error) {
    console.error("Error reading route profile:", error);
    res.status(500).json({ error: "Failed to read route profile" });
  }
});

app.get("/api/dataset-info", (req, res) => {
  try {
    const csvDir = CSV_FOLDERS.original;
    const snappedDir = CSV_FOLDERS.snapped;

    const originalFiles = fs.existsSync(csvDir)
      ? fs.readdirSync(csvDir).filter((f) => f.endsWith(".csv"))
      : [];
    const snappedFiles = fs.existsSync(snappedDir)
      ? fs.readdirSync(snappedDir).filter((f) => f.endsWith(".csv"))
      : [];

    const sampleFile = originalFiles[0] ? path.join(csvDir, originalFiles[0]) : null;
    const sampleRows = sampleFile ? readCsvAsObjects(sampleFile) : [];
    const headers = sampleRows.length > 0 ? Object.keys(sampleRows[0]) : [];

    res.json({
      collected_counts: {
        morning: 13,
        evening: 10,
      },
      file_counts: {
        original_csv_files: originalFiles.length,
        snapped_csv_files: snappedFiles.length,
      },
      baseline_sessions: {
        morning_home_to_office: 43,
        evening_office_to_home: 35,
      },
      csv_columns: headers,
      extracted_features_for_training: [
        "route_type",
        "vehicle_class",
        "start_minute",
        "weekday",
        "progress_ratio",
        "offroute_m",
        "speed_kph",
        "global_bin_speed_kph",
        "bin_session_support",
        "target_eta_min",
      ],
      rejected_or_non_training_fields: [
        "Satellite",
        "Country",
        "Altitude(m)",
        "Bearing(*)",
        "raw un-snapped lat/lng for final model training",
      ],
    });
  } catch (error) {
    console.error("Error reading dataset info:", error);
    res.status(500).json({ error: "Failed to read dataset info" });
  }
});

app.get("/api/predict-eta", (req, res) => {
  try {
    const route = String(req.query.route || "").toLowerCase();
    const startTime = String(req.query.startTime || "");
    if (!["morning", "evening"].includes(route)) {
      return res.status(400).json({ error: "route must be morning or evening" });
    }
    if (!/^\d{2}:\d{2}$/.test(startTime)) {
      return res.status(400).json({ error: "startTime must be HH:MM" });
    }

    const args = [
      "predict_eta.py",
      "--route",
      route,
      "--start-time",
      startTime,
      "--model",
      "model_outputs/eta_model.joblib",
      "--profiles-dir",
      "model_outputs",
    ];

    if (req.query.progressRatio !== undefined && req.query.progressRatio !== "") {
      args.push("--progress-ratio", String(req.query.progressRatio));
    }
    if (req.query.progressM !== undefined && req.query.progressM !== "") {
      args.push("--progress-m", String(req.query.progressM));
    }
    if (req.query.weekday !== undefined && req.query.weekday !== "") {
      args.push("--weekday", String(req.query.weekday));
    }
    if (req.query.lat !== undefined && req.query.lng !== undefined && req.query.lat !== "" && req.query.lng !== "") {
      args.push("--lat", String(req.query.lat), "--lng", String(req.query.lng));
    }
    if (req.query.dest_lat !== undefined && req.query.dest_lng !== undefined && req.query.dest_lat !== "" && req.query.dest_lng !== "") {
      args.push("--dest-lat", String(req.query.dest_lat), "--dest-lng", String(req.query.dest_lng));
    }

    execFile("C:/Python313/python.exe", args, { cwd: __dirname, timeout: 20000 }, (error, stdout, stderr) => {
      if (error) {
        console.error("Predict ETA error:", error, stderr);
        return res.status(500).json({ error: "Failed to run prediction", detail: stderr || error.message });
      }
      try {
        const payload = JSON.parse(stdout);
        res.json(payload);
      } catch (parseErr) {
        res.status(500).json({ error: "Prediction output parse failed", detail: stdout });
      }
    });
  } catch (error) {
    console.error("Error in /api/predict-eta:", error);
    res.status(500).json({ error: "Prediction request failed" });
  }
});

app.listen(PORT, () => {
  console.log(`GPS Session Cleaner server running at http://localhost:${PORT}`);
  console.log(`Serving files from: ${__dirname}`);
  console.log(`CSV files location (original): ${CSV_FOLDERS.original}`);
  console.log(`CSV files location (snapped): ${CSV_FOLDERS.snapped}`);
});
