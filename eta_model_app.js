const map = L.map("map", { zoomControl: true }).setView([22.54, 88.4], 12);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors"
}).addTo(map);

let routeLayer = L.layerGroup().addTo(map);
let selectedMarker = null;
let selectedPoint = null;
let currentProfile = [];

const statusBar = document.getElementById("statusBar");
const routeSelect = document.getElementById("routeSelect");
const vehicleSelect = document.getElementById("vehicleSelect");
const startTimeInput = document.getElementById("startTime");
const resultBox = document.getElementById("resultBox");
const chokeList = document.getElementById("chokeList");

function congestionColor(v) {
  if (v <= 0.33) return "#2ca94f";
  if (v <= 0.66) return "#d9aa1f";
  return "#d73434";
}

function toHtmlEscape(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function loadProfile() {
  const route = routeSelect.value;
  statusBar.textContent = `Loading ${route} profile...`;
  routeLayer.clearLayers();

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
    const color = congestionColor(Number(b.congestion));
    L.polyline([[a.lat, a.lng], [b.lat, b.lng]], {
      color,
      weight: 4,
      opacity: 0.9
    }).addTo(routeLayer);
  }

  const bounds = L.latLngBounds(profile.map((p) => [p.lat, p.lng]));
  map.fitBounds(bounds.pad(0.08));
  statusBar.textContent = `Loaded ${route} profile with ${profile.length} bins.`;

  // Set default vehicle by route.
  vehicleSelect.value = route === "morning" ? "Shuttle" : "Public Bus";
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
  const vehicleClass = vehicleSelect.value;

  const url = `/api/predict-eta?route=${encodeURIComponent(route)}&startTime=${encodeURIComponent(startTime)}&vehicleClass=${encodeURIComponent(vehicleClass)}&lat=${encodeURIComponent(selectedPoint.lat)}&lng=${encodeURIComponent(selectedPoint.lng)}`;
  resultBox.textContent = "Predicting...";

  const res = await fetch(url);
  const data = await res.json();

  if (!res.ok || data.error) {
    resultBox.textContent = `Prediction failed: ${data.error || "Unknown error"}`;
    chokeList.textContent = "No choke points.";
    return;
  }

  resultBox.innerHTML = [
    `<b>ETA:</b> ${toHtmlEscape(data.estimated_eta_min)} min`,
    `<b>Arrival:</b> ${toHtmlEscape(data.estimated_arrival_time)}`,
    `<b>Model:</b> ${toHtmlEscape(data.model)}`,
    `<b>Progress Ratio:</b> ${(Number(data.progress_ratio) * 100).toFixed(1)}%`,
    `<b>Point-to-baseline:</b> ${toHtmlEscape(data.selected_point_to_baseline_m ?? 0)} m`
  ].join("<br>");

  renderChokes(data.choke_points_ahead || []);
}

map.on("click", (e) => {
  selectedPoint = { lat: e.latlng.lat, lng: e.latlng.lng };
  if (selectedMarker) selectedMarker.remove();
  selectedMarker = L.circleMarker(e.latlng, {
    radius: 6,
    color: "#000",
    fillColor: "#14a44d",
    fillOpacity: 1
  }).addTo(map).bindTooltip("Selected ETA query point", { permanent: false });
  statusBar.textContent = `Selected point: ${e.latlng.lat.toFixed(6)}, ${e.latlng.lng.toFixed(6)}`;
});

document.getElementById("predictBtn").addEventListener("click", predictEta);
document.getElementById("clearPointBtn").addEventListener("click", () => {
  selectedPoint = null;
  if (selectedMarker) {
    selectedMarker.remove();
    selectedMarker = null;
  }
  resultBox.textContent = "Point cleared. Select a point on map to query ETA.";
  chokeList.textContent = "No prediction yet.";
});

routeSelect.addEventListener("change", loadProfile);

loadProfile().catch((err) => {
  statusBar.textContent = "Failed loading profile.";
  console.error(err);
});
