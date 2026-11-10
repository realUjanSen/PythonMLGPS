const ROUTE_VARIANT_META = {
  route1: {
    label: "Route 1: Unforced left, forced right",
    description: "Unforced left at Chingrihata, forced right at Philips.",
    color: "#2d6f37"
  },
  route2: {
    label: "Route 2: Unforced left, unforced right",
    description: "Unforced left at Chingrihata, unforced right at Philips.",
    color: "#144f94"
  },
  route3: {
    label: "Route 3: Forced left, forced right",
    description: "Diversion where left at Chingrihata and right at Philips are both forced.",
    color: "#8f2d5d"
  }
};

const ROUTE_VARIANT_KEYS = Object.keys(ROUTE_VARIANT_META);

const TRAFFIC_BUCKET_COLORS = {
  green: "#2ca94f",
  yellow: "#e6b422",
  red: "#d62f2f"
};

function createDefaultRouteVariants() {
  const variants = {};
  ROUTE_VARIANT_KEYS.forEach((key) => {
    variants[key] = {
      ...ROUTE_VARIANT_META[key],
      points: []
    };
  });
  return variants;
}

const state = {
  map: null,
  sessions: [],
  dirtySessionIds: new Set(),
  csvSource: localStorage.getItem("csvSource") || "original",
  selectedId: null,
  showAll: true,
  renderLayers: new Map(),
  undoStack: [],
  shouldAutoFit: true,
  deletedSessionIds: new Set(),
  routeVariants: createDefaultRouteVariants(),
  selectedVariantKey: "route2",
  showVariants: false,
  waypointEditMode: false,
  midpointMode: false,
  showTraffic: true,
  trafficThreshold: 65,
  snapThresholdMeters: 18,
  currentTrafficInfo: null,
  isErasing: false,
  eraserPreview: null,
  inspectorMarker: null,
  pointInspectorMode: false,
  eraserLastEraseTime: 0,
  eraserThrottleMs: 350,
  renderDebounceTimer: null,
  renderDebounceMs: 150
};

function $(id) {
  return document.getElementById(id);
}

async function getCsvFileList(source = "original") {
  try {
    const response = await fetch(`/api/list-csv-files?source=${encodeURIComponent(source)}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    console.warn("Failed to fetch CSV file list:", error);
    return [];
  }
}

async function refreshNodeStatus() {
  const badge = $("nodeStatus");
  if (!badge) return;

  badge.textContent = "Node: Checking...";
  badge.classList.remove("online", "offline");
  badge.classList.add("checking");

  try {
    const response = await fetch("/api/list-csv-files?source=original", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    badge.textContent = "Node: Online";
    badge.classList.remove("checking", "offline");
    badge.classList.add("online");
  } catch (error) {
    badge.textContent = "Node: Offline";
    badge.classList.remove("checking", "online");
    badge.classList.add("offline");
  }
}

function setStatus(message, isWarn = false) {
  const box = $("statusBox");
  if (!box) return;
  box.textContent = message;
  box.classList.toggle("warn", isWarn);
}

function safeNum(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function parseTimeMs(value) {
  if (!value) return null;
  const t = Date.parse(value);
  return Number.isFinite(t) ? t : null;
}

function parseCsvLine(line) {
  const result = [];
  let token = "";
  let inQuotes = false;

  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];

    if (ch === '"') {
      const next = line[i + 1];
      if (inQuotes && next === '"') {
        token += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === "," && !inQuotes) {
      result.push(token);
      token = "";
    } else {
      token += ch;
    }
  }

  result.push(token);
  return result;
}

function rebuildRowIndex(session) {
  session.rowByIndex = new Map();
  session.rows.forEach((row) => {
    session.rowByIndex.set(row.index, row);
  });
}

function rebuildPointRows(session) {
  // Rebuild pointRows from rows that have valid coordinates
  session.pointRows = session.rows.filter((row) => row.hasCoords);
}

function parseCsv(text, fileName, source = "original") {
  const rows = text
    .replace(/\r/g, "")
    .split("\n")
    .filter((line) => line.trim().length > 0);

  if (rows.length < 2) {
    throw new Error(`CSV has no data rows: ${fileName}`);
  }

  const headers = parseCsvLine(rows[0]);
  const latIdx = headers.findIndex((h) => h.trim().toLowerCase() === "latitude");
  const lngIdx = headers.findIndex((h) => h.trim().toLowerCase() === "longitude");
  const timeIdx = headers.findIndex((h) => h.trim().toLowerCase() === "timestamp");
  const accIdx = headers.findIndex((h) => h.trim().toLowerCase().startsWith("accuracy"));

  if (latIdx === -1 || lngIdx === -1) {
    throw new Error(`Latitude/Longitude column missing in ${fileName}`);
  }

  const parsedRows = [];
  const pointRows = [];

  for (let i = 1; i < rows.length; i += 1) {
    const cells = parseCsvLine(rows[i]);
    const lat = safeNum(cells[latIdx]);
    const lng = safeNum(cells[lngIdx]);
    const row = {
      index: i - 1,
      cells,
      removed: false,
      hasCoords: lat !== null && lng !== null,
      lat,
      lng,
      timestamp: timeIdx >= 0 ? cells[timeIdx] || "" : "",
      timeMs: timeIdx >= 0 ? parseTimeMs(cells[timeIdx]) : null,
      accuracy: accIdx >= 0 ? safeNum(cells[accIdx]) : null
    };

    parsedRows.push(row);

    if (row.hasCoords) {
      pointRows.push(row);
    }
  }

  const session = {
    id: fileName,
    fileName,
    source,
    headers,
    rows: parsedRows,
    pointRows,
    rowByIndex: new Map(),
    classLabel: getSavedClass(fileName),
    morningVariant: getSavedMorningVariant(fileName),
    latIdx,
    lngIdx
  };

  rebuildRowIndex(session);
  return session;
}

function escapeCsv(value) {
  const str = value == null ? "" : String(value);
  if (str.includes(",") || str.includes('"') || str.includes("\n")) {
    return '"' + str.replace(/"/g, '""') + '"';
  }
  return str;
}

function getSavedClass(fileName) {
  const map = JSON.parse(localStorage.getItem("sessionClasses") || "{}");
  return map[fileName] || "";
}

function saveClass(fileName, value) {
  const map = JSON.parse(localStorage.getItem("sessionClasses") || "{}");
  map[fileName] = value;
  localStorage.setItem("sessionClasses", JSON.stringify(map));
}

function getSavedMorningVariant(fileName) {
  const map = JSON.parse(localStorage.getItem("sessionMorningVariants") || "{}");
  return map[fileName] || "";
}

function saveMorningVariant(fileName, value) {
  const map = JSON.parse(localStorage.getItem("sessionMorningVariants") || "{}");
  map[fileName] = value;
  localStorage.setItem("sessionMorningVariants", JSON.stringify(map));
}

function getMorningVariantLabel(value) {
  const labels = {
    v1_best_forced_right_philips: "V1 Best: Chingrihata allowed, forced right at Philips",
    v2_chingri_allowed_technopolis_forced: "V2: Chingrihata allowed, Technopolis forced",
    v3_forced_left_chingri_right_philips: "V3: Forced left Chingrihata, right at Philips allowed",
    v4_impossible_forced_left_and_technopolis: "V4 Impossible (not expected in reality)"
  };
  return labels[value] || "Unclassified";
}

function detectRouteName(fileName) {
  if (fileName.includes("Home_to_Office")) return "Home to Office";
  if (fileName.includes("Office_to_Home")) return "Office to Home";
  return "Unknown";
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function haversineMeters(a, b) {
  const lat1 = (a[0] * Math.PI) / 180;
  const lat2 = (b[0] * Math.PI) / 180;
  const dLat = lat2 - lat1;
  const dLng = ((b[1] - a[1]) * Math.PI) / 180;
  const sinDLat = Math.sin(dLat / 2);
  const sinDLng = Math.sin(dLng / 2);
  const aa = sinDLat * sinDLat + Math.cos(lat1) * Math.cos(lat2) * sinDLng * sinDLng;
  return 6371000 * 2 * Math.atan2(Math.sqrt(aa), Math.sqrt(1 - aa));
}

function calculatePathDistanceMeters(points) {
  if (!points || points.length < 2) return 0;
  let total = 0;
  for (let i = 1; i < points.length; i += 1) {
    total += haversineMeters(points[i - 1], points[i]);
  }
  return total;
}

function percentile(values, p) {
  if (!values || values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  if (sorted.length === 1) return sorted[0];
  const idx = (sorted.length - 1) * clamp(p, 0, 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  const weight = idx - lo;
  return sorted[lo] * (1 - weight) + sorted[hi] * weight;
}

function formatNumber(value, digits = 2) {
  if (!Number.isFinite(value)) return "N/A";
  return Number(value).toFixed(digits);
}

function formatDurationMin(mins) {
  if (!Number.isFinite(mins) || mins < 0) return "N/A";
  const whole = Math.round(mins);
  const h = Math.floor(whole / 60);
  const m = whole % 60;
  if (h <= 0) return `${m} min`;
  return `${h}h ${m}m`;
}

function getSelectedSession() {
  return state.sessions.find((s) => s.id === state.selectedId) || null;
}

function saveRouteVariantsToStorage() {
  const toStore = {};
  ROUTE_VARIANT_KEYS.forEach((key) => {
    toStore[key] = state.routeVariants[key].points;
  });
  localStorage.setItem("routeVariantsV1", JSON.stringify(toStore));
}

function loadRouteVariantsFromStorage() {
  const defaults = createDefaultRouteVariants();
  const stored = JSON.parse(localStorage.getItem("routeVariantsV1") || "null");

  if (!stored || typeof stored !== "object") {
    state.routeVariants = defaults;
    return;
  }

  ROUTE_VARIANT_KEYS.forEach((key) => {
    const points = Array.isArray(stored[key]) ? stored[key] : [];
    defaults[key].points = points
      .filter((p) => Array.isArray(p) && p.length >= 2 && Number.isFinite(Number(p[0])) && Number.isFinite(Number(p[1])))
      .map((p) => [Number(p[0]), Number(p[1])]);
  });

  state.routeVariants = defaults;
}

function getSegments(session) {
  const coords = session.pointRows.map((row) => [row.lat, row.lng]);
  return coords.length > 1 ? [coords] : [];
}

function renderSessionList() {
  const list = $("sessionList");
  if (!list) return;
  list.innerHTML = "";

  state.sessions.forEach((session) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "session-item" + (state.selectedId === session.id ? " active" : "");
    const sourceTag = session.source === "snapped" ? "snapped" : "original";
    button.innerHTML = `${session.fileName}<span class="session-sub">source: ${sourceTag} | rows: ${session.rows.length}, points: ${session.pointRows.length}</span>`;
    button.addEventListener("click", () => {
      // Clicking the same session toggles selection off so Show All can be used without a focused session.
      state.selectedId = state.selectedId === session.id ? null : session.id;
      state.shouldAutoFit = true;
      if (state.selectedId) {
        loadCleanedSessionIfAvailable();
      }
      renderSessionList();
      renderMeta();
      forceRenderMap();
    });
    list.appendChild(button);
  });
}

function renderMeta() {
  const meta = $("sessionMeta");
  const classSelect = $("classSelect");
  const morningVariantSelect = $("morningVariantSelect");
  const session = getSelectedSession();

  if (!meta || !classSelect || !morningVariantSelect) return;

  if (!session) {
    meta.textContent = "No session selected.";
    classSelect.value = "";
    morningVariantSelect.value = "";
    return;
  }

  const firstRow = session.rows[0];
  const lastRow = session.rows[session.rows.length - 1];

  meta.innerHTML = [
    "<table class='meta-table'>",
    `<tr><td>File</td><td>${session.fileName}</td></tr>`,
    `<tr><td>Route</td><td>${detectRouteName(session.fileName)}</td></tr>`,
    `<tr><td>Start Time</td><td>${firstRow?.timestamp || "N/A"}</td></tr>`,
    `<tr><td>End Time</td><td>${lastRow?.timestamp || "N/A"}</td></tr>`,
    `<tr><td>Total Rows</td><td>${session.rows.length}</td></tr>`,
    `<tr><td>GPS Points</td><td>${session.pointRows.length}</td></tr>`,
    `<tr><td>Morning Variant</td><td>${getMorningVariantLabel(session.morningVariant)}</td></tr>`,
    `<tr><td>Columns</td><td>${session.headers.join(", ")}</td></tr>`,
    "</table>"
  ].join("");

  classSelect.value = session.classLabel || "";
  morningVariantSelect.value = session.morningVariant || "";
}

function clearMapLayers() {
  state.renderLayers.forEach((layer) => layer.remove());
  state.renderLayers.clear();
}

function renderMapImmediate() {
  if (!state.map) return;

  clearMapLayers();
  const selected = getSelectedSession();
  let firstCenter = null;

  state.sessions.forEach((session) => {
    if (!state.showAll && session.id !== state.selectedId) return;

    const segments = getSegments(session);
    if (segments.length === 0) return;

    const isSelected = selected && session.id === selected.id;
    const showTrafficOnSelected = Boolean(isSelected && state.showTraffic);
    const color = isSelected ? (showTrafficOnSelected ? "#58667a" : "#bb1f1f") : "#4c7ec6";
    const weight = isSelected ? (showTrafficOnSelected ? 2 : 5) : 2;
    const opacity = isSelected ? (showTrafficOnSelected ? 0.5 : 0.95) : 0.6;

    const group = L.layerGroup();
    segments.forEach((coords) => {
      const line = L.polyline(coords, { color, weight, opacity });
      line.addTo(group);
      if (!firstCenter) firstCenter = coords[0];
    });

    if (isSelected) {
      const first = segments[0][0];
      const lastSeg = segments[segments.length - 1];
      const last = lastSeg[lastSeg.length - 1];
      L.circleMarker(first, { radius: 5, color: "#0a8f3e", fillOpacity: 1 }).bindTooltip("Start").addTo(group);
      L.circleMarker(last, { radius: 5, color: "#101820", fillOpacity: 1 }).bindTooltip("End").addTo(group);
    }

    group.addTo(state.map);
    state.renderLayers.set(session.id, group);
  });

  renderRouteVariants();
  renderTrafficOverlay(selected);
  renderAnalysisMarkers();

  if (selected) {
    const segments = getSegments(selected);
    if (segments.length > 0 && state.shouldAutoFit) {
      const bounds = L.latLngBounds(segments.flat());
      state.map.fitBounds(bounds.pad(0.08));
    }
  } else if (firstCenter && state.shouldAutoFit) {
    state.map.setView(firstCenter, 14);
  }

  renderRouteStats();
  renderTrafficStats(selected);
  state.shouldAutoFit = false;
}

function renderMap() {
  if (state.renderDebounceTimer !== null) {
    clearTimeout(state.renderDebounceTimer);
  }
  state.renderDebounceTimer = setTimeout(() => {
    state.renderDebounceTimer = null;
    renderMapImmediate();
  }, state.renderDebounceMs);
}

function forceRenderMap() {
  if (state.renderDebounceTimer !== null) {
    clearTimeout(state.renderDebounceTimer);
    state.renderDebounceTimer = null;
  }
  renderMapImmediate();
}

function renderAnalysisMarkers() {
  // Defect marking removed; eraser tool handles all point deletion
}

function renderRouteVariants() {
  if (!state.showVariants || !state.map) return;

  const group = L.layerGroup();
  const selectedVariant = state.routeVariants[state.selectedVariantKey];

  ROUTE_VARIANT_KEYS.forEach((key) => {
    const variant = state.routeVariants[key];
    if (!variant || variant.points.length < 2) return;

    const isSelected = key === state.selectedVariantKey;
    const line = L.polyline(variant.points, {
      color: variant.color,
      weight: isSelected ? 5 : 3,
      opacity: isSelected ? 0.95 : 0.65,
      dashArray: isSelected ? undefined : "8 8"
    });
    line.bindTooltip(variant.label);
    line.addTo(group);

    if (isSelected) {
      L.circleMarker(variant.points[0], {
        radius: 4,
        color: variant.color,
        fillColor: "#ffffff",
        fillOpacity: 1
      }).bindTooltip("Variant start").addTo(group);

      L.circleMarker(variant.points[variant.points.length - 1], {
        radius: 4,
        color: variant.color,
        fillColor: "#ffffff",
        fillOpacity: 1
      }).bindTooltip("Variant end").addTo(group);
    }
  });

  if (selectedVariant && selectedVariant.points.length >= 2 && state.waypointEditMode) {
    selectedVariant.points.forEach((point, idx) => {
      const marker = L.marker(point, {
        draggable: true,
        keyboard: false,
        icon: L.divIcon({
          className: "route-waypoint-icon",
          html: "<span></span>",
          iconSize: [12, 12],
          iconAnchor: [6, 6]
        })
      });

      marker.bindTooltip(`WP ${idx + 1}`);

      marker.on("dragend", (event) => {
        const latlng = event.target.getLatLng();
        selectedVariant.points[idx] = [latlng.lat, latlng.lng];
        saveRouteVariantsToStorage();
        state.shouldAutoFit = false;
        renderMap();
        setStatus(`Moved waypoint ${idx + 1} on ${selectedVariant.label}.`);
      });

      marker.on("contextmenu", () => {
        if (selectedVariant.points.length <= 2) {
          setStatus("A route variant needs at least 2 waypoints.", true);
          return;
        }
        selectedVariant.points.splice(idx, 1);
        saveRouteVariantsToStorage();
        state.shouldAutoFit = false;
        renderMap();
        setStatus(`Deleted waypoint ${idx + 1} from ${selectedVariant.label}.`);
      });

      marker.addTo(group);
    });

    if (state.midpointMode) {
      for (let i = 0; i < selectedVariant.points.length - 1; i += 1) {
        const a = selectedVariant.points[i];
        const b = selectedVariant.points[i + 1];
        const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
        const midMarker = L.circleMarker(mid, {
          radius: 4,
          color: "#1c2a3f",
          weight: 1,
          fillColor: "#ffffff",
          fillOpacity: 1
        });

        midMarker.bindTooltip("Insert waypoint here");
        midMarker.on("click", () => {
          selectedVariant.points.splice(i + 1, 0, mid);
          saveRouteVariantsToStorage();
          state.shouldAutoFit = false;
          renderMap();
          setStatus(`Inserted waypoint into ${selectedVariant.label}.`);
        });

        midMarker.addTo(group);
      }
    }
  }

  if (group.getLayers().length > 0) {
    group.addTo(state.map);
    state.renderLayers.set("__variants__", group);
  }
}

function renderRouteStats() {
  const box = $("routeStats");
  if (!box) return;

  const variant = state.routeVariants[state.selectedVariantKey];
  if (!variant) {
    box.textContent = "No route variant selected.";
    return;
  }

  const distanceKm = calculatePathDistanceMeters(variant.points) / 1000;
  const route2Km = calculatePathDistanceMeters(state.routeVariants.route2.points) / 1000;
  const delta = distanceKm - route2Km;

  box.innerHTML = [
    "<table>",
    `<tr><td>Variant</td><td>${variant.label}</td></tr>`,
    `<tr><td>Description</td><td>${variant.description}</td></tr>`,
    `<tr><td>Waypoints</td><td>${variant.points.length}</td></tr>`,
    `<tr><td>Distance</td><td>${formatNumber(distanceKm, 2)} km</td></tr>`,
    `<tr><td>Delta vs Route 2</td><td>${formatNumber(delta, 2)} km</td></tr>`,
    "</table>"
  ].join("");
}

function getTrafficBucket(congestionScore) {
  const score = clamp(congestionScore, 0, 1);
  const redThreshold = clamp((Number(state.trafficThreshold) || 65) / 100, 0.2, 0.95);
  const yellowThreshold = redThreshold * 0.62;

  if (score >= redThreshold) return "red";
  if (score >= yellowThreshold) return "yellow";
  return "green";
}

function congestionToColor(congestionScore) {
  const bucket = getTrafficBucket(congestionScore);
  return TRAFFIC_BUCKET_COLORS[bucket];
}

function buildTrafficInfo(session) {
  if (!session || session.pointRows.length < 2) {
    return {
      sessionId: session ? session.id : "",
      segments: [],
      stats: null
    };
  }

  const points = session.pointRows;
  const segments = [];
  const speedValues = [];
  let totalDistanceMeters = 0;

  for (let i = 1; i < points.length; i += 1) {
    const prev = points[i - 1];
    const cur = points[i];
    const start = [prev.lat, prev.lng];
    const end = [cur.lat, cur.lng];
    const distanceMeters = haversineMeters(start, end);
    const dtSec =
      Number.isFinite(prev.timeMs) && Number.isFinite(cur.timeMs) && cur.timeMs > prev.timeMs
        ? (cur.timeMs - prev.timeMs) / 1000
        : null;
    const speedKmh = dtSec && dtSec > 0 ? (distanceMeters / dtSec) * 3.6 : null;

    if (speedKmh !== null && Number.isFinite(speedKmh)) {
      speedValues.push(speedKmh);
    }

    totalDistanceMeters += distanceMeters;
    segments.push({
      start,
      end,
      distanceMeters,
      dtSec,
      speedKmh,
      congestion: 0,
      color: "#7abf2f"
    });
  }

  const freeFlowKmh = Math.max(12, percentile(speedValues, 0.85) || 32);

  segments.forEach((segment, segIdx) => {
    const pointIdx = segIdx + 1;
    const centerPoint = points[pointIdx];
    const from = Math.max(0, pointIdx - 5);
    const to = Math.min(points.length - 1, pointIdx + 5);
    let nearbyCount = 0;

    for (let j = from; j <= to; j += 1) {
      const d = haversineMeters([centerPoint.lat, centerPoint.lng], [points[j].lat, points[j].lng]);
      if (d <= 35) nearbyCount += 1;
    }

    const densityScore = clamp((nearbyCount - 1) / 10, 0, 1);
    const speedScore = segment.speedKmh === null ? 0.55 : clamp(segment.speedKmh / freeFlowKmh, 0, 1);
    const congestion = clamp(0.72 * (1 - speedScore) + 0.28 * densityScore, 0, 1);

    segment.congestion = congestion;
  });

  const smoothedCongestions = segments.map((segment, idx) => {
    const prev = segments[Math.max(0, idx - 1)].congestion;
    const cur = segment.congestion;
    const next = segments[Math.min(segments.length - 1, idx + 1)].congestion;
    return clamp((prev + 2 * cur + next) / 4, 0, 1);
  });

  smoothedCongestions.forEach((congestion, idx) => {
    const segment = segments[idx];
    segment.congestion = congestion;
    segment.bucket = getTrafficBucket(congestion);
    segment.color = congestionToColor(congestion);
  });

  let clusterCount = 0;
  let runLength = 0;
  segments.forEach((segment) => {
    const severe = segment.congestion > 0.66 || (segment.speedKmh !== null && segment.speedKmh < 7);
    if (severe) {
      runLength += 1;
    } else {
      if (runLength >= 3) clusterCount += 1;
      runLength = 0;
    }
  });

  if (runLength >= 3) {
    clusterCount += 1;
  }

  let durationMin = null;
  const firstTime = points[0].timeMs;
  const lastTime = points[points.length - 1].timeMs;

  if (Number.isFinite(firstTime) && Number.isFinite(lastTime) && lastTime > firstTime) {
    durationMin = (lastTime - firstTime) / 60000;
  } else {
    const sumDt = segments.reduce((acc, seg) => acc + (Number.isFinite(seg.dtSec) ? seg.dtSec : 0), 0);
    durationMin = sumDt > 0 ? sumDt / 60 : null;
  }

  const avgSpeedKmh =
    Number.isFinite(durationMin) && durationMin > 0
      ? (totalDistanceMeters / 1000) / (durationMin / 60)
      : null;

  const validSpeedSegments = segments.filter((seg) => Number.isFinite(seg.speedKmh));
  const slowSegments = validSpeedSegments.filter((seg) => seg.speedKmh < 4).length;
  const stopRatio = validSpeedSegments.length > 0 ? slowSegments / validSpeedSegments.length : 0;

  const congestionIndex =
    segments.length > 0
      ? segments.reduce((acc, seg) => acc + seg.congestion, 0) / segments.length
      : 0;

  return {
    sessionId: session.id,
    segments,
    stats: {
      distanceKm: totalDistanceMeters / 1000,
      durationMin,
      avgSpeedKmh,
      stopRatio,
      clusterCount,
      congestionIndex,
      freeFlowKmh
    }
  };
}

function renderTrafficOverlay(selected) {
  state.currentTrafficInfo = buildTrafficInfo(selected);

  if (!state.showTraffic || !selected) return;
  if (!state.currentTrafficInfo || !state.currentTrafficInfo.segments.length) return;

  const group = L.layerGroup();
  const segments = state.currentTrafficInfo.segments;

  const drawBucketRuns = (bucket) => {
    let run = [];

    const flushRun = () => {
      if (run.length < 2) {
        run = [];
        return;
      }
      L.polyline(run, {
        color: TRAFFIC_BUCKET_COLORS[bucket],
        weight: 6,
        opacity: 0.92,
        lineCap: "butt",
        lineJoin: "round"
      }).addTo(group);
      run = [];
    };

    segments.forEach((segment) => {
      if (segment.bucket !== bucket) {
        flushRun();
        return;
      }

      if (run.length === 0) {
        run.push(segment.start, segment.end);
      } else {
        run.push(segment.end);
      }
    });

    flushRun();
  };

  // Draw low congestion first and high congestion last so red stays on top.
  drawBucketRuns("green");
  drawBucketRuns("yellow");
  drawBucketRuns("red");

  if (group.getLayers().length > 0) {
    group.addTo(state.map);
    state.renderLayers.set("__traffic__", group);
  }
}

function renderTrafficStats(selected) {
  const box = $("trafficStats");
  if (!box) return;

  if (!selected) {
    box.textContent = "Select a session to compute speed, distance, congestion, and ETA.";
    return;
  }

  const info =
    state.currentTrafficInfo && state.currentTrafficInfo.sessionId === selected.id
      ? state.currentTrafficInfo
      : buildTrafficInfo(selected);

  if (!info.stats) {
    box.textContent = "Not enough points to compute traffic and ETA.";
    return;
  }

  const variant = state.routeVariants[state.selectedVariantKey];
  const variantDistanceKm = variant ? calculatePathDistanceMeters(variant.points) / 1000 : 0;
  const baseSpeed = info.stats.avgSpeedKmh || info.stats.freeFlowKmh || 15;
  const adjustedSpeedKmh = Math.max(7, baseSpeed * (1 - info.stats.congestionIndex * 0.5));

  let etaMin = null;
  if (variantDistanceKm > 0) {
    etaMin = (variantDistanceKm / adjustedSpeedKmh) * 60;
  } else if (Number.isFinite(info.stats.durationMin)) {
    etaMin = info.stats.durationMin;
  }

  box.innerHTML = [
    "<table>",
    `<tr><td>Observed Distance</td><td>${formatNumber(info.stats.distanceKm, 2)} km</td></tr>`,
    `<tr><td>Observed Duration</td><td>${formatDurationMin(info.stats.durationMin)}</td></tr>`,
    `<tr><td>Average Speed</td><td>${formatNumber(info.stats.avgSpeedKmh, 1)} km/h</td></tr>`,
    `<tr><td>Free-flow Speed (P85)</td><td>${formatNumber(info.stats.freeFlowKmh, 1)} km/h</td></tr>`,
    `<tr><td>Congestion Index</td><td>${formatNumber(info.stats.congestionIndex * 100, 1)}%</td></tr>`,
    `<tr><td>Low-speed Segment Ratio</td><td>${formatNumber(info.stats.stopRatio * 100, 1)}%</td></tr>`,
    `<tr><td>Traffic Clusters</td><td>${info.stats.clusterCount}</td></tr>`,
    `<tr><td>Variant Distance</td><td>${formatNumber(variantDistanceKm, 2)} km</td></tr>`,
    `<tr><td>Predicted ETA</td><td>${formatDurationMin(etaMin)}</td></tr>`,
    "</table>"
  ].join("");
}

function snapshotRemovedState(session) {
  return {
    kind: "single",
    sessionId: session.id,
    pointRows: JSON.parse(JSON.stringify(session.pointRows)),
    rows: JSON.parse(JSON.stringify(session.rows))
  };
}

function snapshotRemovedStateForSessions(sessions) {
  return {
    kind: "multi",
    sessions: sessions.map((session) => ({
      sessionId: session.id,
      pointRows: JSON.parse(JSON.stringify(session.pointRows)),
      rows: JSON.parse(JSON.stringify(session.rows))
    }))
  };
}

function restoreRemovedState(snapshot) {
  if (snapshot && snapshot.kind === "multi" && Array.isArray(snapshot.sessions)) {
    snapshot.sessions.forEach((item) => {
      const session = state.sessions.find((s) => s.id === item.sessionId);
      if (!session) return;
      session.pointRows = item.pointRows;
      session.rows = item.rows;
      rebuildRowIndex(session);
    });
    return;
  }

  const session = state.sessions.find((s) => s.id === snapshot.sessionId);
  if (!session) return;

  session.pointRows = snapshot.pointRows;
  session.rows = snapshot.rows;
  rebuildRowIndex(session);
}

function deleteRowsByCsvIndices(session, csvRowIndicesToDelete) {
  session.pointRows = session.pointRows.filter((row) => !csvRowIndicesToDelete.has(row.index));
  session.rows = session.rows.filter((row) => !csvRowIndicesToDelete.has(row.index));
  rebuildRowIndex(session);
}

function getEraseTargetSessions() {
  const selected = getSelectedSession();
  const eraseAllVisible = Boolean($("eraseAllVisible")?.checked);
  if (eraseAllVisible && state.showAll) {
    return state.sessions.filter((session) => session.pointRows.length > 0);
  }

  if (!selected) {
    return [];
  }

  if (!eraseAllVisible || !state.showAll) {
    return [selected];
  }

  return [selected];
}

function clearInspectorMarker() {
  if (state.inspectorMarker && state.map) {
    try {
      state.map.removeLayer(state.inspectorMarker);
    } catch (e) {}
    state.inspectorMarker = null;
  }
}

function inspectNearestPoint(latlng) {
  if (!state.map) return;

  const infoBox = $("pointInspectorInfo");
  const selected = getSelectedSession();
  const searchAcrossAll = Boolean($("eraseAllVisible")?.checked) && state.showAll;
  const visibleSessions = state.showAll
    ? state.sessions
    : state.sessions.filter((session) => session.id === state.selectedId);
  let candidates = [];
  if (selected && !searchAcrossAll) {
    candidates = [selected];
  } else {
    candidates = visibleSessions.length > 0 ? visibleSessions : state.sessions;
  }

  let best = null;
  for (const session of candidates) {
    for (const row of session.pointRows) {
      const d = state.map.distance(latlng, [row.lat, row.lng]);
      if (!best || d < best.distanceM) {
        best = { session, row, distanceM: d };
      }
    }
  }

  if (!best) {
    if (infoBox) infoBox.textContent = "No point rows available for inspection.";
    clearInspectorMarker();
    return;
  }

  clearInspectorMarker();
  state.inspectorMarker = L.circleMarker([best.row.lat, best.row.lng], {
    radius: 6,
    color: "#1f2933",
    weight: 2,
    fillColor: "#ffb020",
    fillOpacity: 1
  }).addTo(state.map);

  const sourceTag = best.session.source === "snapped" ? "snapped" : "original";
  state.inspectorMarker.bindPopup(
    `Nearest point<br>${best.session.fileName}<br>source=${sourceTag}<br>distance=${best.distanceM.toFixed(1)}m`
  ).openPopup();

  if (infoBox) {
    infoBox.innerHTML = [
      `<b>Session:</b> ${best.session.fileName}`,
      `<b>Source:</b> ${sourceTag}`,
      `<b>Row index:</b> ${best.row.index}`,
      `<b>Lat/Lng:</b> ${best.row.lat.toFixed(6)}, ${best.row.lng.toFixed(6)}`,
      `<b>Timestamp:</b> ${best.row.timestamp || "N/A"}`,
      `<b>Distance from click:</b> ${best.distanceM.toFixed(1)} m`
    ].join("<br>");
  }

  const scopeLabel = selected && !searchAcrossAll
    ? "selected session"
    : (state.showAll ? "all visible sessions" : "available sessions");
  setStatus(`Point investigator (${scopeLabel}): ${best.session.fileName} row ${best.row.index} (${best.distanceM.toFixed(1)}m from click).`);
}

function eraseAroundSession(session, latlng, radiusMeters, minChunk) {
  if (!session || session.pointRows.length === 0) return 0;

  const eraseSet = new Set();
  session.pointRows.forEach((row, idx) => {
    const d = state.map.distance(latlng, [row.lat, row.lng]);
    if (d <= radiusMeters) {
      eraseSet.add(idx);
    }
  });

  if (eraseSet.size === 0) return 0;

  const csvRowIndicesToDelete = new Set(
    Array.from(eraseSet)
      .map((idx) => session.pointRows[idx]?.index)
      .filter((idx) => idx !== undefined)
  );

  deleteRowsByCsvIndices(session, csvRowIndicesToDelete);
  return eraseSet.size;
}

function showEraserPreview(latlng) {
  removeEraserPreview();
  const radiusMeters = Math.max(2, Number($("eraserRadius")?.value) || 25);
  if (!state.map) return;
  state.eraserPreview = L.circle(latlng, {
    radius: radiusMeters,
    color: "#c9302c",
    weight: 2,
    fillColor: "#c9302c",
    fillOpacity: 0.06
  }).addTo(state.map);
}

function updateEraserPreview(latlng) {
  if (!state.map) return;
  const radiusMeters = Math.max(2, Number($("eraserRadius")?.value) || 25);
  if (state.eraserPreview) {
    state.eraserPreview.setLatLng(latlng);
    state.eraserPreview.setRadius(radiusMeters);
  } else {
    showEraserPreview(latlng);
  }
}

function removeEraserPreview() {
  if (state.eraserPreview && state.map) {
    try {
      state.map.removeLayer(state.eraserPreview);
    } catch (e) {}
    state.eraserPreview = null;
  }
}

function eraseAround(latlng, options = {}) {
  const targets = getEraseTargetSessions();
  if (targets.length === 0) {
    setStatus("Select a session before erasing.", true);
    return;
  }

  const radiusMeters = Math.max(2, Number($("eraserRadius")?.value) || 25);
  const minChunk = Math.max(1, Number($("eraserChunk")?.value) || 6);

  if (!options.suppressUndo) {
    const snapshot = targets.length === 1
      ? snapshotRemovedState(targets[0])
      : snapshotRemovedStateForSessions(targets);
    state.undoStack.push(snapshot);
  }

  let totalErased = 0;
  let touchedSessions = 0;
  targets.forEach((session) => {
    const erased = eraseAroundSession(session, latlng, radiusMeters, minChunk);
    if (erased > 0) {
      session.dirty = true;
      state.dirtySessionIds.add(session.id);
      touchedSessions += 1;
      totalErased += erased;
    }
  });

  if (totalErased === 0) return;

  state.shouldAutoFit = !options.suppressUndo;
  renderMeta();
  renderMap();
  const scopeText = touchedSessions > 1 ? `${touchedSessions} sessions` : targets[0].fileName;
  setStatus(`Erased ${totalErased} point(s) and removed matching CSV row(s) across ${scopeText}; routes reconnected.`);
}

function updateModeIndicators() {
  const eraserOn = Boolean($("eraserMode")?.checked);
  const editOn = Boolean($("waypointEditMode")?.checked);
  const midpointOn = Boolean($("midpointMode")?.checked);
  const inspectorOn = Boolean($("pointInspectorMode")?.checked);

  const wrap = document.querySelector(".map-wrap");
  const eraserBadge = $("eraserBadge");
  const modeText = $("mapModeIndicator");

  if (wrap) {
    wrap.classList.toggle("mode-erase", eraserOn);
  }

  if (eraserBadge) {
    eraserBadge.textContent = eraserOn ? "ERASER ON" : "ERASER OFF";
    eraserBadge.classList.toggle("active", eraserOn);
  }

  let text = "Normal mode";
  if (editOn && midpointOn) text = "Waypoint edit + midpoint insert";
  else if (editOn) text = "Waypoint edit mode";
  else if (inspectorOn) text = "Point investigator mode";
  else if (eraserOn) text = "Eraser mode";

  if (editOn && eraserOn) {
    text += " (map click tools paused)";
  }

  if (modeText) {
    modeText.textContent = text;
  }
}



async function deleteSelectedSession() {
  const session = getSelectedSession();
  if (!session) {
    setStatus("No session selected to delete.", true);
    return;
  }

  const ok = window.confirm(`Delete this session file?\n\n${session.fileName}`);
  if (!ok) return;

  try {
    const sourceQuery = session.source ? `&source=${encodeURIComponent(session.source)}` : "";
    const response = await fetch(`/api/delete-csv?file=${encodeURIComponent(session.fileName)}${sourceQuery}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    
    setStatus(`Deleted ${session.fileName} from disk.`);
    state.deletedSessionIds.add(session.id);
    localStorage.setItem("deletedSessionIds", JSON.stringify(Array.from(state.deletedSessionIds)));
    state.sessions = state.sessions.filter((s) => s.id !== session.id);
    state.undoStack = [];

    if (state.sessions.length === 0) {
      state.selectedId = null;
    } else if (state.selectedId === session.id) {
      state.selectedId = null;
      state.shouldAutoFit = true;
    }

    renderSessionList();
    renderMeta();
    forceRenderMap();
  } catch (error) {
    setStatus(`Failed to delete file: ${error.message}`, true);
  }
}

function undoErase() {
  const snapshot = state.undoStack.pop();
  if (!snapshot) {
    setStatus("Nothing to undo.", true);
    return;
  }

  restoreRemovedState(snapshot);
  state.shouldAutoFit = true;
  renderMeta();
  forceRenderMap();
  setStatus("Undo complete.");
}

function resetSelectedSession() {
  const session = getSelectedSession();
  if (!session) {
    setStatus("Select a session to reset.", true);
    return;
  }

  state.shouldAutoFit = true;
  renderMeta();
  forceRenderMap();
  setStatus(`Reset map focus for ${session.fileName}. Use Undo to restore erased points.`);
}

function handleRadiusChange() {
  const radiusInput = $("eraserRadius");
  const radiusValue = $("radiusValue");
  if (radiusInput && radiusValue) {
    radiusValue.textContent = radiusInput.value;
  }
  if (state.isErasing) {
    updateEraserPreview(state.map.getCenter());
  }
}

function getCleanedSessionsKey() {
  return "cleanedSessions_v2";
}

function isQuotaExceededError(err) {
  if (!err) return false;
  return err.name === "QuotaExceededError" || err.code === 22 || /quota/i.test(String(err.message || ""));
}

function persistCleanedSessionsWithPrune(cleanedSessions) {
  const key = getCleanedSessionsKey();
  let working = { ...cleanedSessions };

  while (true) {
    try {
      localStorage.setItem(key, JSON.stringify(working));
      return { ok: true, pruned: cleanedSessions && Object.keys(cleanedSessions).length - Object.keys(working).length };
    } catch (err) {
      if (!isQuotaExceededError(err)) {
        return { ok: false, error: err, pruned: 0 };
      }

      const entries = Object.entries(working);
      if (entries.length <= 1) {
        return { ok: false, error: err, pruned: 0, quota: true };
      }

      entries.sort((a, b) => (Number(a[1]?.timestamp) || 0) - (Number(b[1]?.timestamp) || 0));
      const [oldestKey] = entries[0];
      delete working[oldestKey];
    }
  }
}

function setRouteLabVisibility(visible) {
  const panel = $("routeLabPanel");
  if (!panel) return;
  panel.classList.toggle("is-hidden", !visible);
}

async function saveCleanedSession() {
  const session = getSelectedSession();
  try {
    const dirtyTargets = state.sessions.filter((target) => target.dirty || state.dirtySessionIds.has(target.id));
    const targets = dirtyTargets.length > 0 ? dirtyTargets : (session ? [session] : []);
    if (targets.length === 0) {
      setStatus("No edited sessions to save.", true);
      return;
    }

    const files = targets.map((target) => ({
      fileName: target.fileName,
      csvText: [
        target.headers.map(escapeCsv).join(","),
        ...target.rows.map((row) => row.cells.map(escapeCsv).join(","))
      ].join("\n")
    }));

    const response = await fetch("/api/save-csv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: state.csvSource, files })
    });
    const result = await response.json();
    if (!response.ok || !result.success) {
      throw new Error(result.error || `HTTP ${response.status}`);
    }

    const cleanedSessions = JSON.parse(localStorage.getItem(getCleanedSessionsKey()) || "{}");
    targets.forEach((target) => {
      delete cleanedSessions[target.fileName];
      target.dirty = false;
      state.dirtySessionIds.delete(target.id);
    });
    localStorage.setItem(getCleanedSessionsKey(), JSON.stringify(cleanedSessions));

    const folderLabel = state.csvSource === "snapped" ? "csv_snapped" : "csv";
    setStatus(`Saved cleaned CSV data for ${targets.length} session(s) to ${folderLabel}.`);
  } catch (err) {
    setStatus(`Error saving to disk: ${err.message}. Use Download cleaned CSV as a fallback.`, true);
  }
}

function loadCleanedSessionIfAvailable() {
  const session = getSelectedSession();
  return loadCleanedDataIntoSession(session);
}

function loadCleanedDataIntoSession(session) {
  if (!session) return false;
  try {
    const cleanedSessions = JSON.parse(localStorage.getItem(getCleanedSessionsKey()) || "{}");
    if (!cleanedSessions[session.fileName]) return false;
    const cleaned = cleanedSessions[session.fileName];
    session.headers = cleaned.headers;
    session.rows = cleaned.rows;
    rebuildRowIndex(session);
    rebuildPointRows(session);
    return true;
  } catch (err) {
    console.error("Error loading cleaned session:", err);
    return false;
  }
}

function loadAllCleanedSessionsIfAvailable() {
  state.sessions.forEach((session) => {
    loadCleanedDataIntoSession(session);
  });
}

function downloadCleanedCsv() {
  const session = getSelectedSession();
  if (!session) {
    setStatus("Select a session before downloading.", true);
    return;
  }

  const lines = [];
  lines.push(session.headers.map(escapeCsv).join(","));
  session.rows.forEach((row) => {
    lines.push(row.cells.map(escapeCsv).join(","));
  });

  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  const safeName = session.fileName.replace(/\.csv$/i, "") + "_cleaned.csv";
  link.href = URL.createObjectURL(blob);
  link.download = safeName;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(link.href);

  setStatus(`Downloaded cleaned file: ${safeName}`);
}

function toLocalXYMetersFromBase(base, point) {
  const latScale = 111320;
  const lngScale = Math.cos((base[0] * Math.PI) / 180) * 111320;
  return {
    x: (point[1] - base[1]) * lngScale,
    y: (point[0] - base[0]) * latScale
  };
}

function fromLocalXYMeters(base, pointXY) {
  const latScale = 111320;
  const lngScale = Math.cos((base[0] * Math.PI) / 180) * 111320;
  return [base[0] + pointXY.y / latScale, base[1] + pointXY.x / lngScale];
}

function projectPointToSegment(point, segA, segB) {
  const p = toLocalXYMetersFromBase(segA, point);
  const a = { x: 0, y: 0 };
  const b = toLocalXYMetersFromBase(segA, segB);

  const vx = b.x - a.x;
  const vy = b.y - a.y;
  const wx = p.x - a.x;
  const wy = p.y - a.y;
  const denom = vx * vx + vy * vy;

  if (denom <= 0.000001) {
    const distance = Math.hypot(wx, wy);
    return {
      projection: segA,
      t: 0,
      distance
    };
  }

  let t = (wx * vx + wy * vy) / denom;
  t = clamp(t, 0, 1);

  const projXY = {
    x: a.x + t * vx,
    y: a.y + t * vy
  };

  const distance = Math.hypot(p.x - projXY.x, p.y - projXY.y);
  const projection = fromLocalXYMeters(segA, projXY);

  return {
    projection,
    t,
    distance
  };
}

function nearestProjectionOnPolyline(point, polyline) {
  if (!polyline || polyline.length < 2) return null;

  let nearest = null;
  for (let i = 0; i < polyline.length - 1; i += 1) {
    const projected = projectPointToSegment(point, polyline[i], polyline[i + 1]);
    if (!nearest || projected.distance < nearest.distance) {
      nearest = {
        lat: projected.projection[0],
        lng: projected.projection[1],
        distance: projected.distance,
        segmentIndex: i
      };
    }
  }

  return nearest;
}

function updateSessionRowCoordinates(session, pointRow, lat, lng) {
  pointRow.lat = lat;
  pointRow.lng = lng;
  if (session.latIdx >= 0) pointRow.cells[session.latIdx] = lat.toFixed(7);
  if (session.lngIdx >= 0) pointRow.cells[session.lngIdx] = lng.toFixed(7);

  const row = session.rowByIndex.get(pointRow.index);
  if (row && row !== pointRow) {
    row.lat = lat;
    row.lng = lng;
    if (session.latIdx >= 0) row.cells[session.latIdx] = lat.toFixed(7);
    if (session.lngIdx >= 0) row.cells[session.lngIdx] = lng.toFixed(7);
  }
}

function snapSelectedSessionToVariant() {
  const session = getSelectedSession();
  if (!session) {
    setStatus("Select a session first.", true);
    return;
  }

  const variant = state.routeVariants[state.selectedVariantKey];
  if (!variant || variant.points.length < 2) {
    setStatus("Selected variant has too few points for snapping.", true);
    return;
  }

  const threshold = Math.max(2, Number($("snapThreshold")?.value) || state.snapThresholdMeters || 18);
  state.snapThresholdMeters = threshold;

  state.undoStack.push(snapshotRemovedState(session));

  let snappedCount = 0;
  session.pointRows.forEach((row) => {
    const nearest = nearestProjectionOnPolyline([row.lat, row.lng], variant.points);
    if (!nearest) return;
    if (nearest.distance <= threshold) {
      updateSessionRowCoordinates(session, row, nearest.lat, nearest.lng);
      snappedCount += 1;
    }
  });

  state.shouldAutoFit = false;
  renderMeta();
  renderMap();
  setStatus(`Snapped ${snappedCount}/${session.pointRows.length} points to ${variant.label} (threshold ${threshold}m).`);
}

function downsamplePoints(points, maxPoints = 260) {
  if (!Array.isArray(points)) return [];
  if (points.length <= maxPoints) return points.map((p) => [p[0], p[1]]);

  const result = [];
  const step = (points.length - 1) / (maxPoints - 1);
  let lastIdx = -1;

  for (let i = 0; i < maxPoints; i += 1) {
    const idx = Math.round(i * step);
    if (idx === lastIdx) continue;
    const p = points[idx];
    result.push([p[0], p[1]]);
    lastIdx = idx;
  }

  if (result.length > 0) {
    const lastSrc = points[points.length - 1];
    const lastDst = result[result.length - 1];
    if (lastDst[0] !== lastSrc[0] || lastDst[1] !== lastSrc[1]) {
      result.push([lastSrc[0], lastSrc[1]]);
    }
  }

  return result;
}

function captureSelectedSessionAsVariant() {
  const session = getSelectedSession();
  if (!session) {
    setStatus("Select a session first.", true);
    return;
  }

  const variant = state.routeVariants[state.selectedVariantKey];
  if (!variant) {
    setStatus("No route variant selected.", true);
    return;
  }

  const points = session.pointRows.map((r) => [r.lat, r.lng]);
  if (points.length < 2) {
    setStatus("Selected session has too few points.", true);
    return;
  }

  variant.points = downsamplePoints(points, 260);
  saveRouteVariantsToStorage();
  state.shouldAutoFit = false;
  renderMap();
  setStatus(`Saved ${variant.points.length} waypoint(s) into ${variant.label}.`);
}

function cloneBaselineToOthers() {
  const route2 = state.routeVariants.route2;
  if (!route2 || route2.points.length < 2) {
    setStatus("Load or create Route 2 first.", true);
    return;
  }

  ROUTE_VARIANT_KEYS.forEach((key) => {
    if (key === "route2") return;
    state.routeVariants[key].points = route2.points.map((p) => [p[0], p[1]]);
  });

  saveRouteVariantsToStorage();
  renderMap();
  setStatus("Cloned Route 2 into Route 1 and Route 3.");
}

function resetSelectedVariant() {
  const variant = state.routeVariants[state.selectedVariantKey];
  if (!variant) return;

  if (state.selectedVariantKey === "route2") {
    variant.points = [];
    saveRouteVariantsToStorage();
    renderMap();
    setStatus("Route 2 cleared.");
    return;
  }

  const route2 = state.routeVariants.route2;
  variant.points = route2.points.map((p) => [p[0], p[1]]);
  saveRouteVariantsToStorage();
  renderMap();
  setStatus(`Reset ${variant.label} from Route 2.`);
}

function orderPointsByNearestNeighbor(points, startPoint, endPoint) {
  if (!points || points.length < 3) return points.map((p) => [p[0], p[1]]);

  const remaining = points.map((p) => [p[0], p[1]]);
  let startIndex = 0;

  if (startPoint) {
    let minD = Infinity;
    for (let i = 0; i < remaining.length; i += 1) {
      const d = haversineMeters(startPoint, remaining[i]);
      if (d < minD) {
        minD = d;
        startIndex = i;
      }
    }
  }

  const ordered = [remaining.splice(startIndex, 1)[0]];

  while (remaining.length > 0) {
    const current = ordered[ordered.length - 1];
    let nextIndex = 0;
    let nextDist = Infinity;

    for (let i = 0; i < remaining.length; i += 1) {
      const d = haversineMeters(current, remaining[i]);
      if (d < nextDist) {
        nextDist = d;
        nextIndex = i;
      }
    }

    ordered.push(remaining.splice(nextIndex, 1)[0]);
  }

  if (endPoint && ordered.length > 1) {
    const forwardToEnd = haversineMeters(ordered[ordered.length - 1], endPoint);
    const reverseToEnd = haversineMeters(ordered[0], endPoint);
    if (reverseToEnd < forwardToEnd) {
      ordered.reverse();
    }
  }

  return ordered;
}

function ensureBaselineFromSelectedSession() {
  const route2 = state.routeVariants.route2;
  if (route2.points.length > 1) return;

  const selected = getSelectedSession();
  if (!selected || selected.pointRows.length < 2) return;

  route2.points = downsamplePoints(selected.pointRows.map((r) => [r.lat, r.lng]), 180);
  saveRouteVariantsToStorage();
}

async function loadSessions() {
  setStatus("Loading CSV sessions...");

  state.deletedSessionIds = new Set(JSON.parse(localStorage.getItem("deletedSessionIds") || "[]"));
  state.sessions = [];
  state.dirtySessionIds.clear();
  state.undoStack = [];
  state.shouldAutoFit = true;
  clearInspectorMarker();

  const CSV_FILES = await getCsvFileList(state.csvSource);
  const skipped = [];

  for (const fileEntry of CSV_FILES) {
    const fileName = typeof fileEntry === "string"
      ? fileEntry
      : (fileEntry?.fileName || fileEntry?.urlPath || String(fileEntry || ""));
    const source = typeof fileEntry === "object" && fileEntry !== null && fileEntry.source
      ? String(fileEntry.source)
      : state.csvSource;
    const sourceFolder = source === "snapped" ? "csv_snapped" : "csv";
    const fileUrl = typeof fileEntry === "object" && fileEntry !== null && fileEntry.urlPath
      ? fileEntry.urlPath
      : `${sourceFolder}/${fileName}`;

    if (!fileName) {
      continue;
    }

    try {
      const response = await fetch(fileUrl);
      if (!response.ok) {
        skipped.push(fileName);
        continue;
      }

      const text = await response.text();
      const session = parseCsv(text, fileName, source);
      if (!state.deletedSessionIds.has(session.id)) {
        state.sessions.push(session);
      }
    } catch {
      skipped.push(fileName);
    }
  }

  if (state.sessions.length === 0) {
    renderSessionList();
    renderMeta();
    renderMap();
    setStatus("No CSV sessions loaded. Run from a local web server.", true);
    return;
  }

  if (state.selectedId && !state.sessions.some((s) => s.id === state.selectedId)) {
    state.selectedId = null;
  }

  loadAllCleanedSessionsIfAvailable();

  renderSessionList();
  renderMeta();
  ensureBaselineFromSelectedSession();
  renderMap();

  const skippedMsg = skipped.length ? ` Skipped ${skipped.length} missing/unreadable file(s).` : "";
  const sourceLabel = state.csvSource === "snapped" ? "snapped" : "original";
  setStatus(`Loaded ${state.sessions.length} ${sourceLabel} session file(s).${skippedMsg}`);
}

async function loadFromPickedFiles(fileList) {
  const files = Array.from(fileList || []).filter((f) => f.name.toLowerCase().endsWith(".csv"));
  if (files.length === 0) {
    setStatus("No CSV files selected.", true);
    return;
  }

  state.sessions = [];
  state.undoStack = [];
  state.shouldAutoFit = true;

  for (const file of files) {
    try {
      const text = await file.text();
      const session = parseCsv(text, file.name);
      state.sessions.push(session);
    } catch (err) {
      setStatus(`Could not parse ${file.name}: ${err.message}`, true);
    }
  }

  if (state.sessions.length === 0) {
    renderSessionList();
    renderMeta();
    renderMap();
    return;
  }

  state.sessions.sort((a, b) => a.fileName.localeCompare(b.fileName));
  state.selectedId = null;

  loadAllCleanedSessionsIfAvailable();

  renderSessionList();
  renderMeta();
  ensureBaselineFromSelectedSession();
  renderMap();
  setStatus(`Loaded ${state.sessions.length} selected CSV file(s).`);
}

function initMap() {
  state.map = L.map("map", {
    zoomControl: true,
    preferCanvas: true
  }).setView([22.5209, 88.3696], 13);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 19
  }).addTo(state.map);

  state.map.on("click", (event) => {
    if (state.pointInspectorMode) {
      inspectNearestPoint(event.latlng);
      return;
    }

    if (state.waypointEditMode) return;
    if (!$("eraserMode")?.checked) return;
    if (event.originalEvent?.ctrlKey) return; // Ctrl+click: pan, not erase
    // simple click erase (records undo)
    eraseAround(event.latlng);
  });

  // Drag-to-erase: mousedown starts erasing and disables map dragging
  // Ctrl+drag: pan the map normally, don't erase
  state.map.on("mousedown", (event) => {
    if (state.waypointEditMode) return;
    if (!$("eraserMode")?.checked) return;
    if (event.originalEvent?.ctrlKey) return; // Ctrl+drag: allow map panning

    const targets = getEraseTargetSessions();
    if (targets.length === 0) return;

    state.isErasing = true;
    // Record one undo snapshot for this drag sweep.
    const snapshot = targets.length === 1
      ? snapshotRemovedState(targets[0])
      : snapshotRemovedStateForSessions(targets);
    state.undoStack.push(snapshot);

    try {
      if (state.map.dragging && state.map.dragging.enabled()) state.map.dragging.disable();
    } catch (e) {}

    // initial erase and preview
    eraseAround(event.latlng, { suppressUndo: true });
    showEraserPreview(event.latlng);
  });

  state.map.on("mousemove", (event) => {
    // live preview when hovering eraser mode
    if (!$("eraserMode")?.checked) return;
    if (!state.isErasing) {
      // show preview following cursor
      updateEraserPreview(event.latlng);
      return;
    }

    const now = Date.now();
    if (now - state.eraserLastEraseTime < state.eraserThrottleMs) {
      updateEraserPreview(event.latlng);
      return;
    }
    state.eraserLastEraseTime = now;

    eraseAround(event.latlng, { suppressUndo: true });
    updateEraserPreview(event.latlng);
  });

  state.map.on("mouseup", () => {
    if (!state.isErasing) return;
    state.isErasing = false;
    try {
      if (state.map.dragging && !state.map.dragging.enabled()) state.map.dragging.enable();
    } catch (e) {}
    removeEraserPreview();
    forceRenderMap();
  });
}

function wireEvents() {
  $("reloadBtn")?.addEventListener("click", loadSessions);
  $("csvSourceSelect")?.addEventListener("change", (e) => {
    state.csvSource = e.target.value === "snapped" ? "snapped" : "original";
    localStorage.setItem("csvSource", state.csvSource);
    loadSessions();
  });
  $("undoBtn")?.addEventListener("click", undoErase);
  $("resetBtn")?.addEventListener("click", resetSelectedSession);
  $("saveCleanedBtn")?.addEventListener("click", saveCleanedSession);
  $("downloadBtn")?.addEventListener("click", downloadCleanedCsv);
  $("deleteSessionBtn")?.addEventListener("click", deleteSelectedSession);

  $("showAllToggle")?.addEventListener("change", (e) => {
    state.showAll = e.target.checked;
    state.shouldAutoFit = true;
    forceRenderMap();
  });

  $("eraserRadius")?.addEventListener("input", handleRadiusChange);
  $("eraserMode")?.addEventListener("change", updateModeIndicators);
  $("pointInspectorMode")?.addEventListener("change", (e) => {
    state.pointInspectorMode = Boolean(e.target.checked);
    if (!state.pointInspectorMode) {
      clearInspectorMarker();
      const infoBox = $("pointInspectorInfo");
      if (infoBox) infoBox.textContent = "Point inspector idle. Click on the map to inspect nearest point.";
    }
    updateModeIndicators();
  });

  $("classSelect")?.addEventListener("change", (e) => {
    const session = getSelectedSession();
    if (!session) return;

    session.classLabel = e.target.value;
    saveClass(session.fileName, e.target.value);
    setStatus(`Saved class '${session.classLabel || "Unclassified"}' for ${session.fileName}.`);
  });

  $("morningVariantSelect")?.addEventListener("change", (e) => {
    const session = getSelectedSession();
    if (!session) return;

    session.morningVariant = e.target.value;
    saveMorningVariant(session.fileName, e.target.value);
    renderMeta();
    setStatus(`Saved morning variant '${getMorningVariantLabel(session.morningVariant)}' for ${session.fileName}.`);
  });

  $("filePicker")?.addEventListener("change", (e) => {
    loadFromPickedFiles(e.target.files);
  });

  $("routeVariantSelect")?.addEventListener("change", (e) => {
    state.selectedVariantKey = e.target.value;
    state.shouldAutoFit = false;
    renderMap();
  });

  $("showVariantsToggle")?.addEventListener("change", (e) => {
    state.showVariants = e.target.checked;
    state.shouldAutoFit = false;
    renderMap();
  });

  $("showRouteLabToggle")?.addEventListener("change", (e) => {
    setRouteLabVisibility(Boolean(e.target.checked));
  });

  $("waypointEditMode")?.addEventListener("change", (e) => {
    state.waypointEditMode = e.target.checked;
    if (!state.waypointEditMode) {
      const mid = $("midpointMode");
      if (mid) {
        mid.checked = false;
      }
      state.midpointMode = false;
    }
    updateModeIndicators();
    state.shouldAutoFit = false;
    renderMap();
  });

  $("midpointMode")?.addEventListener("change", (e) => {
    state.midpointMode = e.target.checked;
    if (state.midpointMode && !state.waypointEditMode) {
      const edit = $("waypointEditMode");
      if (edit) {
        edit.checked = true;
      }
      state.waypointEditMode = true;
    }
    updateModeIndicators();
    state.shouldAutoFit = false;
    renderMap();
  });

  $("snapThreshold")?.addEventListener("change", (e) => {
    state.snapThresholdMeters = Math.max(2, Number(e.target.value) || 18);
  });

  $("showTrafficToggle")?.addEventListener("change", (e) => {
    state.showTraffic = e.target.checked;
    state.shouldAutoFit = false;
    renderMap();
  });

  $("trafficThreshold")?.addEventListener("input", (e) => {
    state.trafficThreshold = Math.max(20, Math.min(95, Number(e.target.value) || 65));
    $("thresholdValue").textContent = `${Math.round(state.trafficThreshold)}%`;
    state.shouldAutoFit = false;
    renderMap();
  });

  $("captureVariantBtn")?.addEventListener("click", captureSelectedSessionAsVariant);
  $("cloneBaselineBtn")?.addEventListener("click", cloneBaselineToOthers);
  $("resetVariantBtn")?.addEventListener("click", resetSelectedVariant);
  $("snapToVariantBtn")?.addEventListener("click", snapSelectedSessionToVariant);
}

async function bootstrap() {
  loadRouteVariantsFromStorage();

  const routeSelect = $("routeVariantSelect");
  if (routeSelect) {
    routeSelect.value = state.selectedVariantKey;
  }

  const showVariantsToggle = $("showVariantsToggle");
  if (showVariantsToggle) {
    showVariantsToggle.checked = state.showVariants;
  }

  const showRouteLabToggle = $("showRouteLabToggle");
  if (showRouteLabToggle) {
    showRouteLabToggle.checked = false;
  }
  setRouteLabVisibility(false);

  const showTrafficToggle = $("showTrafficToggle");
  if (showTrafficToggle) {
    showTrafficToggle.checked = state.showTraffic;
  }

  const snapThreshold = $("snapThreshold");
  if (snapThreshold) {
    snapThreshold.value = String(state.snapThresholdMeters);
  }

  const trafficThreshold = $("trafficThreshold");
  if (trafficThreshold) {
    trafficThreshold.value = String(state.trafficThreshold);
    $("thresholdValue").textContent = `${Math.round(state.trafficThreshold)}%`;
  }

  const sourceSelect = $("csvSourceSelect");
  if (sourceSelect) {
    sourceSelect.value = state.csvSource === "snapped" ? "snapped" : "original";
  }

  initMap();
  wireEvents();
  updateModeIndicators();
  renderRouteStats();
  refreshNodeStatus();
  setInterval(refreshNodeStatus, 15000);
  loadSessions();
}

bootstrap();
