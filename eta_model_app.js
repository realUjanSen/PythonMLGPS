const map = L.map("map", { zoomControl: true }).setView([22.54, 88.4], 12);
const lightTileLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors"
});
const darkTileLayer = L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors &copy; CARTO"
});
let activeBaseLayer = lightTileLayer.addTo(map);

let routeLayer = L.layerGroup().addTo(map);
let selectedMarker = null;
let selectedPoint = null;
let destinationMarker = null;
let destinationPoint = null;
let currentProfile = [];
let selectionMode = "current"; // "current" or "destination"
let trafficColorMode = "banded";

const statusBar = document.getElementById("statusBar");
const routeSelect = document.getElementById("routeSelect");
const startTimeInput = document.getElementById("startTime");
const resultBox = document.getElementById("resultBox");
const chokeList = document.getElementById("chokeList");
const locationStatus = document.getElementById("locationStatus");
const destinationStatus = document.getElementById("destinationStatus");
const predictTraceBox = document.getElementById("predictTraceBox");
const modeCurrentBtn = document.getElementById("modeCurrentBtn");
const modeDestinationBtn = document.getElementById("modeDestinationBtn");
const mapThemeSelect = document.getElementById("mapThemeSelect");
const trafficColorModeSelect = document.getElementById("trafficColorMode");
let predictTraceTimer = null;
let predictTraceStartedAt = 0;

function congestionColor(v) {
  if (v <= 0.33) return "#2ca94f";
  if (v <= 0.66) return "#d9aa1f";
  return "#d73434";
}

function gradientCongestionColor(v) {
  const c = Math.max(0, Math.min(1, Number(v) || 0));
  let r;
  let g;
  let b = 52;
  if (c <= 0.5) {
    const t = c / 0.5;
    r = Math.round(44 + (217 - 44) * t);
    g = Math.round(169 + (170 - 169) * t);
  } else {
    const t = (c - 0.5) / 0.5;
    r = Math.round(217 + (215 - 217) * t);
    g = Math.round(170 + (52 - 170) * t);
  }
  return `rgb(${r}, ${g}, ${b})`;
}

function toHtmlEscape(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatMinutesToMinSec(totalMinutes) {
  const minutesFloat = Number(totalMinutes);
  if (!Number.isFinite(minutesFloat) || minutesFloat < 0) {
    return "N/A";
  }
  const totalSeconds = Math.max(0, Math.round(minutesFloat * 60));
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${mins} min ${String(secs).padStart(2, "0")} sec`;
}

function renderPredictTrace(state) {
  const pct = Math.max(0, Math.min(100, Number(state.progressPct) || 0));
  const title = state.title || "Idle";
  const stage = state.stage || "Waiting";
  const elapsed = state.elapsedSec || "0.0";
  const meta = state.meta || "Ready.";
  predictTraceBox.innerHTML = [
    `<div class="trace-row"><span class="trace-title">${toHtmlEscape(title)}</span><span>${toHtmlEscape(`${pct.toFixed(0)}%`)}</span></div>`,
    `<div class="trace-stage">${toHtmlEscape(stage)}</div>`,
    `<div class="trace-bar"><div class="trace-fill" style="width:${pct}%;"></div></div>`,
    `<div class="trace-meta">${toHtmlEscape(meta)} | elapsed ${toHtmlEscape(`${elapsed}s`)}</div>`
  ].join("");
}

function startPredictTrace({ route, startTime, hasDestination }) {
  if (predictTraceTimer) {
    clearInterval(predictTraceTimer);
    predictTraceTimer = null;
  }

  predictTraceStartedAt = Date.now();
  const stages = [
    "Validating selected route, time, and points",
    "Projecting start point onto baseline bins",
    "Building model feature vector",
    "Running Python inference (predict_eta.py)",
    "Applying destination-aware ETA scaling",
    "Preparing arrival time and choke points"
  ];

  renderPredictTrace({
    title: "Prediction Running",
    stage: stages[0],
    progressPct: 2,
    elapsedSec: "0.0",
    meta: `route=${route}, start=${startTime}, destination=${hasDestination ? "yes" : "no"}`
  });

  predictTraceTimer = setInterval(() => {
    const elapsedMs = Date.now() - predictTraceStartedAt;
    const elapsedSec = (elapsedMs / 1000).toFixed(1);
    const eased = 1 - Math.exp(-elapsedMs / 1800);
    const progressPct = Math.min(92, 3 + eased * 89);
    const stageIdx = Math.min(stages.length - 1, Math.floor((progressPct / 100) * stages.length));
    renderPredictTrace({
      title: "Prediction Running",
      stage: stages[stageIdx],
      progressPct,
      elapsedSec,
      meta: "Backend request in-flight"
    });
  }, 250);
}

function finishPredictTrace({ ok, model, destinationApplied, errorMsg }) {
  if (predictTraceTimer) {
    clearInterval(predictTraceTimer);
    predictTraceTimer = null;
  }
  const elapsedSec = ((Date.now() - predictTraceStartedAt) / 1000).toFixed(1);
  if (ok) {
    renderPredictTrace({
      title: "Prediction Complete",
      stage: "Model inference finished successfully",
      progressPct: 100,
      elapsedSec,
      meta: `model=${model || "unknown"}, destinationApplied=${destinationApplied ? "yes" : "no"}`
    });
  } else {
    renderPredictTrace({
      title: "Prediction Failed",
      stage: "Backend returned an error",
      progressPct: 100,
      elapsedSec,
      meta: errorMsg || "Unknown error"
    });
  }
}

function setMapTheme(theme) {
  if (activeBaseLayer) {
    map.removeLayer(activeBaseLayer);
  }
  activeBaseLayer = theme === "dark" ? darkTileLayer : lightTileLayer;
  activeBaseLayer.addTo(map);
}

function updateModeButtons() {
  if (selectionMode === "current") {
    modeCurrentBtn.style.background = "#14a44d";
    modeDestinationBtn.style.background = "#7a8797";
  } else {
    modeCurrentBtn.style.background = "#7a8797";
    modeDestinationBtn.style.background = "#d73434";
  }
}

async function loadProfile() {
  const route = routeSelect.value;
  statusBar.textContent = `Loading ${route} profile...`;
  routeLayer.clearLayers();
  destinationPoint = null;
  if (destinationMarker) {
    destinationMarker.remove();
    destinationMarker = null;
  }
  destinationStatus.textContent = "Click map to set.";

  const res = await fetch(`/api/route-profile?route=${encodeURIComponent(route)}`);
  const profile = await res.json();
  currentProfile = profile;

  if (!Array.isArray(profile) || profile.length < 2) {
    statusBar.textContent = "Route profile unavailable.";
    return;
  }

  for (let i = 1; i < profile.length; i += 1) {
    const a = profile[i - 1];
    const b = profile[i];
    const color = trafficColorMode === "gradient"
      ? gradientCongestionColor(Number(b.congestion))
      : congestionColor(Number(b.congestion));
    const segment = [[a.lat, a.lng], [b.lat, b.lng]];

    // Draw a minimal black outline first to make traffic colors readable on bright map tiles.
    L.polyline(segment, {
      color: "#000000",
      weight: 5,
      opacity: 0.95,
      lineCap: "round",
      lineJoin: "round"
    }).addTo(routeLayer);

    L.polyline(segment, {
      color,
      weight: 4,
      opacity: 0.95,
      lineCap: "round",
      lineJoin: "round"
    }).addTo(routeLayer);
  }

  const bounds = L.latLngBounds(profile.map((p) => [p.lat, p.lng]));
  map.fitBounds(bounds.pad(0.08));
  statusBar.textContent = `Loaded ${route} profile with ${profile.length} bins.`;

  // Vehicle class is now derived from route (ghost feature removed)
}

function renderChokes(items) {
  if (!Array.isArray(items) || items.length === 0) {
    chokeList.textContent = "No choke points returned.";
    return;
  }
  chokeList.innerHTML = items.map((c, idx) => {
    const pct = (Number(c.congestion) * 100).toFixed(1);
    return `${idx + 1}. Bin ${toHtmlEscape(c.bin_idx)} | congestion ${pct}% | speed ${Number(c.avg_speed_kph).toFixed(1)} km/h`;
  }).join("<br>");
}

async function predictEta() {
  if (!selectedPoint) {
    resultBox.textContent = "Select a point on the map first.";
    return;
  }

  const route = routeSelect.value;
  const startTime = startTimeInput.value || "08:15";

  let urlParams = `route=${encodeURIComponent(route)}&startTime=${encodeURIComponent(startTime)}&lat=${encodeURIComponent(selectedPoint.lat)}&lng=${encodeURIComponent(selectedPoint.lng)}`;
  
  if (destinationPoint) {
    urlParams += `&dest_lat=${encodeURIComponent(destinationPoint.lat)}&dest_lng=${encodeURIComponent(destinationPoint.lng)}`;
  }

  const url = `/api/predict-eta?${urlParams}`;
  resultBox.textContent = "Predicting...";
  startPredictTrace({ route, startTime, hasDestination: Boolean(destinationPoint) });

  const res = await fetch(url);
  const data = await res.json();

  if (!res.ok || data.error) {
    resultBox.textContent = `Prediction failed: ${data.error || "Unknown error"}`;
    chokeList.textContent = "No choke points.";
    finishPredictTrace({ ok: false, errorMsg: data.error || "Unknown error" });
    return;
  }

  // Format times
  const startTimeFormatted = toHtmlEscape(startTime);
  const arrivalTime = toHtmlEscape(data.estimated_arrival_time);
  const startPosPct = (Number(data.progress_ratio) * 100).toFixed(1);
  const destPosPct = data.destination_progress_ratio !== undefined
    ? `${(Number(data.destination_progress_ratio) * 100).toFixed(1)}%`
    : "N/A";
  const tripSpanPct = data.requested_trip_span_ratio !== undefined
    ? `${(Number(data.requested_trip_span_ratio) * 100).toFixed(1)}%`
    : `${(Number(data.remaining_ratio_to_route_end ?? 0) * 100).toFixed(1)}%`;
  const directionText = data.destination_ahead === undefined
    ? "N/A"
    : (data.destination_ahead ? "Up" : "Down");

  resultBox.innerHTML = [
    `<b>Start Time:</b> ${startTimeFormatted}`,
    `<b>Arrival Time:</b> ${arrivalTime}`,
    `<b>ETA:</b> ${toHtmlEscape(formatMinutesToMinSec(data.estimated_eta_min))}`,
    `<b>Model:</b> ${toHtmlEscape(data.model)}`,
    `<b>Start Position on Route:</b> ${startPosPct}%`,
    `<b>Destination Position on Route:</b> ${destPosPct}`,
    `<b>Requested Trip Span:</b> ${tripSpanPct}`,
    `<b>Destination Direction:</b> ${directionText}`,
    `<b>Point-to-baseline:</b> ${toHtmlEscape(data.selected_point_to_baseline_m ?? 0)} m`
  ].join("<br>");

  renderChokes(data.choke_points_ahead || []);
  finishPredictTrace({ ok: true, model: data.model, destinationApplied: data.destination_applied });
}

// Handle map clicks based on current mode
map.on("click", (e) => {
  if (selectionMode === "current") {
    // Set start point
    selectedPoint = { lat: e.latlng.lat, lng: e.latlng.lng };
    if (selectedMarker) selectedMarker.remove();
    selectedMarker = L.circleMarker(e.latlng, {
      radius: 6,
      color: "#000",
      fillColor: "#14a44d",
      fillOpacity: 1
    }).addTo(map).bindTooltip("Start point", { permanent: false });
    locationStatus.textContent = `${e.latlng.lat.toFixed(4)}, ${e.latlng.lng.toFixed(4)}`;
    statusBar.textContent = `Start point set: ${e.latlng.lat.toFixed(6)}, ${e.latlng.lng.toFixed(6)}`;
  } else {
    // Set destination point
    destinationPoint = { lat: e.latlng.lat, lng: e.latlng.lng };
    if (destinationMarker) destinationMarker.remove();
    destinationMarker = L.circleMarker(e.latlng, {
      radius: 6,
      color: "#000",
      fillColor: "#d73434",
      fillOpacity: 1
    }).addTo(map).bindTooltip("Destination point", { permanent: false });
    destinationStatus.textContent = `${e.latlng.lat.toFixed(4)}, ${e.latlng.lng.toFixed(4)}`;
    statusBar.textContent = `Destination point set: ${e.latlng.lat.toFixed(6)}, ${e.latlng.lng.toFixed(6)}`;
  }
});

// Mode toggle buttons
modeCurrentBtn.addEventListener("click", () => {
  selectionMode = "current";
  updateModeButtons();
  statusBar.textContent = "Mode: Click on map to set START POINT";
});

modeDestinationBtn.addEventListener("click", () => {
  selectionMode = "destination";
  updateModeButtons();
  statusBar.textContent = "Mode: Click on map to set DESTINATION POINT";
});

document.getElementById("predictBtn").addEventListener("click", predictEta);

document.getElementById("clearPointBtn").addEventListener("click", () => {
  selectedPoint = null;
  if (selectedMarker) {
    selectedMarker.remove();
    selectedMarker = null;
  }
  locationStatus.textContent = "Click map to set.";
  resultBox.textContent = "Start point cleared. Select a point on map to query ETA.";
  chokeList.textContent = "No prediction yet.";
});

document.getElementById("clearDestinationBtn").addEventListener("click", () => {
  destinationPoint = null;
  if (destinationMarker) {
    destinationMarker.remove();
    destinationMarker = null;
  }
  destinationStatus.textContent = "Click map to set.";
  statusBar.textContent = "Destination point cleared. Using default (route end).";
});

routeSelect.addEventListener("change", loadProfile);
mapThemeSelect.addEventListener("change", () => {
  setMapTheme(mapThemeSelect.value);
});
trafficColorModeSelect.addEventListener("change", () => {
  trafficColorMode = trafficColorModeSelect.value;
  loadProfile().catch((err) => {
    statusBar.textContent = "Failed loading profile.";
    console.error(err);
  });
});

updateModeButtons();
loadProfile().catch((err) => {
  statusBar.textContent = "Failed loading profile.";
  console.error(err);
});
