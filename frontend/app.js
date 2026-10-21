// ===================================================================
// NDMA SMART DISASTER RESPONSE COORDINATION SYSTEM - FRONTEND CORE
// Powered by DuckDB Columnar Vector Engine
// ===================================================================

let gisMap = null;
let mapMarkers = [];
let telemetryChart = null;
let currentActiveSensorId = 'SNS-OD-FL-01';

const PRESET_QUERIES = {
  spatial: `-- 1. Pure SQL Haversine Distance: Compute nearest relief camps to Puri Cyclone Epicenter
SELECT 
    c.camp_id,
    c.camp_name,
    c.latitude,
    c.longitude,
    c.max_capacity,
    c.current_occupancy,
    (c.max_capacity - c.current_occupancy) AS available_beds,
    ROUND(
        2 * 6371 * ASIN(SQRT(
            POWER(SIN(RADIANS(c.latitude - 19.8135) / 2), 2) +
            COS(RADIANS(19.8135)) * COS(RADIANS(c.latitude)) *
            POWER(SIN(RADIANS(c.longitude - 85.8312) / 2), 2)
        )), 2
    ) AS distance_km
FROM relief_camps c
ORDER BY distance_km ASC;`,

  occupancy: `-- 2. Multi-Camp Capacity Utilization & Risk Rollup
SELECT 
    c.camp_id,
    c.camp_name,
    c.max_capacity,
    c.current_occupancy,
    (c.max_capacity - c.current_occupancy) AS available_beds,
    ROUND((c.current_occupancy * 100.0) / c.max_capacity, 1) AS occupancy_pct,
    CASE 
        WHEN (c.current_occupancy * 100.0) / c.max_capacity >= 90.0 THEN 'CRITICAL OVERFLOW'
        WHEN (c.current_occupancy * 100.0) / c.max_capacity >= 75.0 THEN 'HIGH ALERT'
        ELSE 'STABLE'
    END AS risk_level,
    c.medical_support
FROM relief_camps c
ORDER BY occupancy_pct DESC;`,

  window: `-- 3. DuckDB Window Function: 3-Period Moving Average & Telemetry Surge
WITH MovingAvgCTE AS (
    SELECT 
        t.sensor_id,
        s.sensor_type,
        s.location_name,
        s.threshold_limit,
        t.recorded_at,
        t.reading_value,
        t.alert_flag,
        ROUND(AVG(t.reading_value) OVER (
            PARTITION BY t.sensor_id 
            ORDER BY t.recorded_at 
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ), 2) AS moving_avg_3p
    FROM sensor_telemetry t
    JOIN iot_sensors s ON t.sensor_id = s.sensor_id
)
SELECT * FROM MovingAvgCTE
ORDER BY recorded_at DESC, sensor_id ASC
LIMIT 15;`,

  burn: `-- 4. Relief Supplies Burn-Rate & Estimated Days of Inventory Remaining
SELECT 
    c.camp_name,
    r.item_name,
    r.category,
    i.quantity_available,
    i.reorder_threshold,
    c.current_occupancy,
    CASE 
        WHEN r.category = 'Water' THEN ROUND(i.quantity_available / GREATEST(1, c.current_occupancy * 0.15), 1)
        WHEN r.category = 'Food' THEN ROUND(i.quantity_available / GREATEST(1, c.current_occupancy * 2), 1)
        ELSE ROUND(i.quantity_available / GREATEST(1, c.current_occupancy * 0.1), 1)
    END AS est_days_remaining
FROM camp_inventory i
JOIN relief_camps c ON i.camp_id = c.camp_id
JOIN relief_items r ON i.item_id = r.item_id
ORDER BY est_days_remaining ASC;`,

  triage: `-- 5. Casualty Demographic & Triage Rollup Analysis
SELECT 
    d.name AS disaster_name,
    r.triage_priority,
    COUNT(r.individual_id) AS total_rescued,
    SUM(CASE WHEN r.age < 18 THEN 1 ELSE 0 END) AS minors,
    SUM(CASE WHEN r.age BETWEEN 18 AND 60 THEN 1 ELSE 0 END) AS adults,
    SUM(CASE WHEN r.age > 60 THEN 1 ELSE 0 END) AS elderly,
    SUM(CASE WHEN r.gender = 'Female' THEN 1 ELSE 0 END) AS females,
    SUM(CASE WHEN r.gender = 'Male' THEN 1 ELSE 0 END) AS males
FROM rescued_individuals r
JOIN disaster_events d ON r.disaster_id = d.disaster_id
GROUP BY d.name, r.triage_priority
ORDER BY d.name, r.triage_priority;`,

  assessments: `-- 6. Post-Disaster Damage Loss vs Casualties by Event
SELECT 
    d.disaster_id,
    d.name,
    d.disaster_type,
    d.severity_level,
    COALESCE(SUM(a.estimated_loss_usd), 0) AS total_damage_usd,
    COALESCE(SUM(a.houses_destroyed), 0) AS total_houses_destroyed,
    (SELECT COUNT(*) FROM rescued_individuals r WHERE r.disaster_id = d.disaster_id) AS total_rescued
FROM disaster_events d
LEFT JOIN damage_assessments a ON d.disaster_id = a.disaster_id
GROUP BY d.disaster_id, d.name, d.disaster_type, d.severity_level
ORDER BY total_damage_usd DESC;`
};

document.addEventListener('DOMContentLoaded', () => {
  initClock();
  initTabs();
  initMap();
  loadAllData();
  loadPresetQuery();
  loadAllTablesList();

  // Periodic refresh
  setInterval(loadKpis, 10000);
});

// ==================== CLOCK ====================
function initClock() {
  function update() {
    const now = new Date();
    document.getElementById('istClock').textContent = now.toLocaleTimeString('en-US', {
      timeZone: 'Asia/Kolkata',
      hour12: false
    }) + ' IST';
  }
  update();
  setInterval(update, 1000);
}

// ==================== TABS ====================
function initTabs() {
  const tabs = document.querySelectorAll('.nav-tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

      tab.classList.add('active');
      const targetId = tab.getAttribute('data-tab');
      const targetPane = document.getElementById(targetId);
      if (targetPane) {
        targetPane.classList.add('active');
      }

      // Invalidate map size if map tab selected
      if (targetId === 'tab-map' && gisMap) {
        setTimeout(() => gisMap.invalidateSize(), 200);
      }
      // Re-render chart if sensors tab
      if (targetId === 'tab-sensors') {
        setTimeout(() => loadSensorChart(currentActiveSensorId), 200);
      }
    });
  });
}

// ==================== LEAFLET MAP ====================
function initMap() {
  const mapElement = document.getElementById('gisMap');
  if (!mapElement) return;

  // Center on India
  gisMap = L.map('gisMap', {
    zoomControl: true,
    attributionControl: false
  }).setView([22.5, 82.5], 5);

  // Multi-layer support without requiring any API keys
  const darkCanvas = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Esri &mdash; NDMA Tactical GIS',
    maxZoom: 16
  });

  const darkLabels = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 16
  });

  const darkTacticalGroup = L.layerGroup([darkCanvas, darkLabels]).addTo(gisMap);

  const satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Esri World Imagery',
    maxZoom: 18
  });

  const osmLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 19
  });

  const baseMaps = {
    "Tactical Dark (Esri)": darkTacticalGroup,
    "Satellite Imagery": satelliteLayer,
    "Street Map (OSM)": osmLayer
  };

  L.control.layers(baseMaps, null, { position: 'topright' }).addTo(gisMap);
}

function clearMapMarkers() {
  mapMarkers.forEach(m => gisMap.removeLayer(m));
  mapMarkers = [];
}

function renderMapMarkers(disasters, camps, sensors) {
  if (!gisMap) return;
  clearMapMarkers();

  // 1. Render Disasters
  disasters.forEach(d => {
    // Outer blast/impact circle
    const circle = L.circle([d.latitude, d.longitude], {
      color: '#ef4444',
      fillColor: '#ef4444',
      fillOpacity: d.status === 'Active' ? 0.18 : 0.05,
      radius: (d.impact_radius_km || 50) * 1000,
      weight: 1.5,
      dashArray: d.status === 'Active' ? '4, 4' : null
    }).addTo(gisMap);
    mapMarkers.push(circle);

    // Center Epicenter Marker
    const iconHtml = `<div style="
      width: 22px; height: 22px; border-radius: 50%;
      background: #ef4444; border: 2px solid #ffffff;
      box-shadow: 0 0 12px #ef4444; display: flex; align-items: center; justify-content: center;
      color: white; font-size: 11px; font-weight: bold;">!</div>`;
    
    const customIcon = L.divIcon({
      className: 'disaster-map-icon',
      html: iconHtml,
      iconSize: [22, 22],
      iconAnchor: [11, 11]
    });

    const marker = L.marker([d.latitude, d.longitude], { icon: customIcon }).addTo(gisMap);
    marker.bindPopup(`
      <div style="font-family: sans-serif; min-width: 200px;">
        <h4 style="color: #ef4444; margin-bottom: 4px;">${d.name}</h4>
        <p style="font-size: 12px; margin: 2px 0;"><strong>Type:</strong> ${d.disaster_type} (Severity: ${d.severity_level}/5)</p>
        <p style="font-size: 12px; margin: 2px 0;"><strong>Status:</strong> ${d.status}</p>
        <p style="font-size: 12px; margin: 2px 0;"><strong>Impact Radius:</strong> ${d.impact_radius_km} km</p>
        <p style="font-size: 12px; margin: 2px 0;"><strong>Evacuated:</strong> ${d.total_evacuated} victims</p>
      </div>
    `);
    mapMarkers.push(marker);
  });

  // 2. Render Relief Camps
  camps.forEach(c => {
    const isCritical = c.occupancy_pct >= 90;
    const color = isCritical ? '#ef4444' : (c.occupancy_pct >= 75 ? '#f59e0b' : '#10b981');

    const iconHtml = `<div style="
      width: 20px; height: 20px; border-radius: 4px;
      background: ${color}; border: 2px solid #ffffff;
      box-shadow: 0 0 10px ${color}; display: flex; align-items: center; justify-content: center;
      color: white; font-size: 10px; font-weight: bold;">H</div>`;

    const campIcon = L.divIcon({
      className: 'camp-map-icon',
      html: iconHtml,
      iconSize: [20, 20],
      iconAnchor: [10, 10]
    });

    const marker = L.marker([c.latitude, c.longitude], { icon: campIcon }).addTo(gisMap);
    marker.bindPopup(`
      <div style="font-family: sans-serif; min-width: 200px;">
        <h4 style="color: #10b981; margin-bottom: 4px;">${c.camp_name}</h4>
        <p style="font-size: 12px; margin: 2px 0;"><strong>In-Charge:</strong> ${c.in_charge_name}</p>
        <p style="font-size: 12px; margin: 2px 0;"><strong>Occupancy:</strong> ${c.current_occupancy} / ${c.max_capacity} (${c.occupancy_pct}%)</p>
        <p style="font-size: 12px; margin: 2px 0;"><strong>Available Beds:</strong> ${c.available_beds}</p>
        <p style="font-size: 12px; margin: 2px 0;"><strong>Medical Unit:</strong> ${c.medical_support ? 'Yes' : 'No'}</p>
      </div>
    `);
    mapMarkers.push(marker);
  });

  // 3. Render IoT Sensors
  sensors.forEach(s => {
    const isAlert = s.status === 'Critical' || s.status === 'Warning';
    const color = isAlert ? '#ef4444' : '#06b6d4';

    const iconHtml = `<div style="
      width: 14px; height: 14px; border-radius: 50%;
      background: ${color}; border: 1.5px solid #ffffff;
      box-shadow: 0 0 8px ${color};"></div>`;

    const sensorIcon = L.divIcon({
      className: 'sensor-map-icon',
      html: iconHtml,
      iconSize: [14, 14],
      iconAnchor: [7, 7]
    });

    const marker = L.marker([s.latitude, s.longitude], { icon: sensorIcon }).addTo(gisMap);
    marker.bindPopup(`
      <div style="font-family: sans-serif; min-width: 180px;">
        <h4 style="color: #06b6d4; margin-bottom: 4px;">${s.sensor_id}</h4>
        <p style="font-size: 12px; margin: 2px 0;"><strong>Location:</strong> ${s.location_name}</p>
        <p style="font-size: 12px; margin: 2px 0;"><strong>Type:</strong> ${s.sensor_type}</p>
        <p style="font-size: 12px; margin: 2px 0;"><strong>Latest:</strong> ${s.latest_reading || '--'} ${s.unit_of_measure}</p>
        <p style="font-size: 12px; margin: 2px 0;"><strong>Threshold:</strong> ${s.threshold_limit} ${s.unit_of_measure}</p>
        <p style="font-size: 12px; margin: 2px 0;"><strong>Status:</strong> ${s.status}</p>
      </div>
    `);
    mapMarkers.push(marker);
  });
}

// ==================== DATA LOADING ====================
async function loadAllData() {
  await Promise.all([
    loadKpis(),
    loadDisasters(),
    loadCamps(),
    loadTeams(),
    loadVictims(),
    loadSensors(),
    loadInventory()
  ]);
}

async function loadKpis() {
  try {
    const res = await fetch('/api/kpi');
    const data = await res.json();
    document.getElementById('kpiActiveDisasters').textContent = data.active_disasters;
    document.getElementById('kpiTotalEvacuees').textContent = data.total_evacuees;
    document.getElementById('kpiDeployedTeams').textContent = data.deployed_teams;
    document.getElementById('kpiCampOccupancy').textContent = `${data.occupancy_rate_pct}%`;
    document.getElementById('kpiCampSub').textContent = `${data.camp_occupancy} / ${data.camp_capacity} beds occupied`;
    document.getElementById('kpiActiveAlerts').textContent = data.active_iot_alerts;

    document.getElementById('badgeDisasters').textContent = data.active_disasters;
    document.getElementById('badgeRescue').textContent = data.deployed_teams;
    document.getElementById('badgeCamps').textContent = data.camp_occupancy;
    document.getElementById('badgeAlerts').textContent = data.active_iot_alerts;
  } catch (err) {
    console.error('Failed to load KPIs:', err);
  }
}

async function loadDisasters() {
  try {
    const status = document.getElementById('filterDisasterStatus')?.value || '';
    const url = status ? `/api/disasters?status=${status}` : '/api/disasters';
    const res = await fetch(url);
    const data = await res.json();

    renderDisastersTable(data);
    renderQuickDisasterFeed(data);
    populateDisasterDropdowns(data);

    // Refresh map if camps and sensors ready
    refreshMapData();
  } catch (err) {
    console.error('Failed to load disasters:', err);
  }
}

function renderDisastersTable(data) {
  const tbody = document.getElementById('disastersTableBody');
  if (!tbody || !data) return;

  tbody.innerHTML = data.map(d => {
    const statusBadge = d.status === 'Active' 
      ? '<span class="badge badge-danger">Active</span>' 
      : (d.status === 'Contained' ? '<span class="badge badge-warning">Contained</span>' : '<span class="badge badge-emerald">Resolved</span>');

    const subtype = d.meteorological_category || d.hazardous_material_type || d.disaster_type;

    return `
      <tr>
        <td><code>${d.disaster_id}</code></td>
        <td><strong>${d.name}</strong></td>
        <td><span class="badge badge-info">${subtype}</span></td>
        <td><span class="badge ${d.severity_level >= 4 ? 'badge-danger' : 'badge-warning'}">Cat ${d.severity_level}/5</span></td>
        <td>${statusBadge}</td>
        <td>${d.latitude.toFixed(3)}, ${d.longitude.toFixed(3)} <span class="text-muted">(${d.impact_radius_km} km)</span></td>
        <td>${d.estimated_affected_pop.toLocaleString()}</td>
        <td><span class="badge badge-primary">${d.teams_deployed} Deployed</span></td>
        <td><strong>${d.total_evacuated}</strong></td>
        <td>
          <button class="btn btn-outline" style="padding: 4px 8px; font-size: 0.72rem;" onclick="focusOnDisaster(${d.latitude}, ${d.longitude})">Center Map</button>
        </td>
      </tr>
    `;
  }).join('');
}

function renderQuickDisasterFeed(data) {
  const feed = document.getElementById('quickDisasterFeed');
  if (!feed) return;

  const active = data.filter(d => d.status === 'Active').slice(0, 4);
  feed.innerHTML = active.map(d => `
    <div class="feed-card">
      <div class="feed-top">
        <span class="feed-title">${d.name}</span>
        <span class="badge ${d.severity_level >= 4 ? 'badge-danger' : 'badge-warning'}">Lvl ${d.severity_level}</span>
      </div>
      <div class="feed-desc">${d.disaster_type} • Radius: ${d.impact_radius_km} km • Pop: ${d.estimated_affected_pop.toLocaleString()}</div>
      <div class="feed-meta">
        <span>Teams Deployed: ${d.teams_deployed}</span>
        <span>Evacuated: ${d.total_evacuated}</span>
      </div>
    </div>
  `).join('');
}

function focusOnDisaster(lat, lon) {
  // Switch to map tab and pan
  document.querySelector('.nav-tab[data-tab="tab-map"]').click();
  if (gisMap) {
    gisMap.setView([lat, lon], 8);
  }
}

async function loadCamps() {
  try {
    const res = await fetch('/api/camps');
    const data = await res.json();
    renderCampsTable(data);
    populateCampDropdowns(data);
    refreshMapData();
  } catch (err) {
    console.error('Failed to load camps:', err);
  }
}

function renderCampsTable(data) {
  const tbody = document.getElementById('campsTableBody');
  if (!tbody || !data) return;

  tbody.innerHTML = data.map(c => {
    const fillClass = c.occupancy_pct >= 90 ? 'fill-danger' : (c.occupancy_pct >= 75 ? 'fill-amber' : 'fill-emerald');
    const riskBadge = c.occupancy_pct >= 90 
      ? '<span class="badge badge-danger">Near Capacity</span>' 
      : (c.occupancy_pct >= 75 ? '<span class="badge badge-warning">High Load</span>' : '<span class="badge badge-emerald">Optimal</span>');

    return `
      <tr>
        <td><code>${c.camp_id}</code></td>
        <td><strong>${c.camp_name}</strong></td>
        <td>${c.in_charge_name}</td>
        <td>
          <div style="display: flex; justify-content: space-between; font-size: 0.72rem; margin-bottom: 2px;">
            <span>${c.current_occupancy} / ${c.max_capacity}</span>
            <span>${c.occupancy_pct}%</span>
          </div>
          <div class="progress-bar-wrap">
            <div class="progress-bar-fill ${fillClass}" style="width: ${Math.min(100, c.occupancy_pct)}%;"></div>
          </div>
        </td>
        <td><strong style="color: ${c.available_beds <= 50 ? '#ef4444' : '#10b981'};">${c.available_beds} beds</strong></td>
        <td>${c.medical_support ? '<span class="badge badge-emerald">Active Unit</span>' : '<span class="text-muted">Basic</span>'}</td>
        <td>${riskBadge}</td>
      </tr>
    `;
  }).join('');
}

async function loadTeams() {
  try {
    const res = await fetch('/api/teams');
    const data = await res.json();
    const tbody = document.getElementById('teamsTableBody');
    if (!tbody) return;

    tbody.innerHTML = data.map(t => {
      const statusBadge = t.readiness_status === 'Deployed' 
        ? '<span class="badge badge-danger">Deployed</span>' 
        : '<span class="badge badge-emerald">Standby</span>';

      return `
        <tr>
          <td><code>${t.team_id}</code></td>
          <td><strong>${t.team_name}</strong></td>
          <td>${t.agency_name}</td>
          <td>${t.member_count} personnel</td>
          <td><span style="font-size: 0.75rem; color: #94a3b8;">${t.assigned_vehicles || 'Foot Squad'}</span></td>
          <td>${statusBadge}</td>
          <td>${t.active_disaster_name ? `<strong style="color: #38bdf8;">${t.active_disaster_name}</strong> (${t.operational_sector})` : '<span class="text-muted">Unassigned</span>'}</td>
        </tr>
      `;
    }).join('');

    // Populate deploy team select
    const deployTeamSelect = document.getElementById('deployTeamSelect');
    if (deployTeamSelect) {
      deployTeamSelect.innerHTML = data.map(t => `
        <option value="${t.team_id}">${t.team_name} (${t.team_type} - ${t.member_count} members) [${t.readiness_status}]</option>
      `).join('');
    }
  } catch (err) {
    console.error('Failed to load teams:', err);
  }
}

async function loadVictims() {
  try {
    const res = await fetch('/api/victims');
    const data = await res.json();
    const tbody = document.getElementById('victimsTableBody');
    if (!tbody) return;

    tbody.innerHTML = data.map(v => {
      let triageBadge = 'badge-info';
      if (v.triage_priority.includes('P1')) triageBadge = 'badge-danger';
      else if (v.triage_priority.includes('P2')) triageBadge = 'badge-warning';
      else if (v.triage_priority.includes('P3')) triageBadge = 'badge-emerald';

      return `
        <tr>
          <td><code>${v.individual_id}</code></td>
          <td><strong>${v.full_name}</strong></td>
          <td>${v.age} / ${v.gender}</td>
          <td><span class="badge ${triageBadge}">${v.triage_priority}</span></td>
          <td>${v.camp_name || '<span class="text-muted">Unallocated</span>'}</td>
          <td>${v.dependent_count > 0 ? `<span class="badge badge-primary">${v.dependent_count} dependents</span>` : '0'}</td>
          <td><span style="font-size: 0.75rem; color: #cbd5e1;">${v.medical_conditions || 'None'}</span></td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    console.error('Failed to load victims:', err);
  }
}

async function loadSensors() {
  try {
    const res = await fetch('/api/sensors');
    const data = await res.json();
    renderSensorsTable(data);
    renderQuickSensorFeed(data);
    refreshMapData();

    // Default select first sensor for time series chart
    if (data.length > 0 && !telemetryChart) {
      currentActiveSensorId = data[0].sensor_id;
      loadSensorChart(currentActiveSensorId, data[0].location_name);
    }
  } catch (err) {
    console.error('Failed to load sensors:', err);
  }
}

function renderSensorsTable(data) {
  const tbody = document.getElementById('sensorsTableBody');
  if (!tbody || !data) return;

  tbody.innerHTML = data.map(s => {
    const statusBadge = s.status === 'Critical' 
      ? '<span class="badge badge-danger">Critical Alert</span>'
      : (s.status === 'Warning' ? '<span class="badge badge-warning">Warning</span>' : '<span class="badge badge-emerald">Nominal</span>');

    return `
      <tr>
        <td><code>${s.sensor_id}</code></td>
        <td><strong>${s.location_name}</strong></td>
        <td>${s.sensor_type}</td>
        <td>${s.threshold_limit} ${s.unit_of_measure}</td>
        <td><strong style="color: ${s.alert_flag ? '#ef4444' : '#38bdf8'}; font-size: 0.95rem;">${s.latest_reading !== null ? s.latest_reading : '--'} ${s.unit_of_measure}</strong></td>
        <td>${s.battery_level_pct !== null ? `${s.battery_level_pct}%` : '--'}</td>
        <td>${statusBadge}</td>
        <td>
          <button class="btn btn-outline" style="padding: 3px 8px; font-size: 0.72rem;" onclick="loadSensorChart('${s.sensor_id}', '${s.location_name}')">Chart</button>
        </td>
      </tr>
    `;
  }).join('');
}

function renderQuickSensorFeed(data) {
  const feed = document.getElementById('quickSensorFeed');
  if (!feed) return;

  const alerts = data.filter(s => s.status === 'Critical' || s.status === 'Warning');
  if (alerts.length === 0) {
    feed.innerHTML = '<div style="font-size: 0.78rem; color: #64748b; padding: 6px;">All sensors operating within safety thresholds.</div>';
    return;
  }

  feed.innerHTML = alerts.map(s => `
    <div class="feed-card" style="border-left: 3px solid ${s.status === 'Critical' ? '#ef4444' : '#f59e0b'};">
      <div class="feed-top">
        <span class="feed-title">${s.sensor_id}</span>
        <span class="badge ${s.status === 'Critical' ? 'badge-danger' : 'badge-warning'}">${s.status}</span>
      </div>
      <div class="feed-desc">${s.location_name} • ${s.sensor_type}</div>
      <div class="feed-meta">
        <span>Reading: ${s.latest_reading} ${s.unit_of_measure}</span>
        <span>Limit: ${s.threshold_limit}</span>
      </div>
    </div>
  `).join('');
}

async function loadSensorChart(sensorId, locationName = '') {
  currentActiveSensorId = sensorId;
  try {
    const res = await fetch(`/api/sensors/${sensorId}/telemetry`);
    const history = await res.json();

    document.getElementById('chartTitle').textContent = `Telemetry: ${sensorId}`;
    if (locationName) {
      document.getElementById('chartSubtitle').textContent = `Station: ${locationName} • Last ${history.length} Readings`;
    }
    document.getElementById('chartSensorBadge').textContent = sensorId;

    const labels = history.map(h => h.recorded_at.split(' ')[1] || h.recorded_at);
    const values = history.map(h => h.reading_value);

    const ctx = document.getElementById('sensorTelemetryChart');
    if (!ctx) return;

    if (telemetryChart) {
      telemetryChart.destroy();
    }

    telemetryChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: 'Sensor Telemetry',
          data: values,
          borderColor: '#06b6d4',
          backgroundColor: 'rgba(6, 182, 212, 0.12)',
          borderWidth: 2,
          pointBackgroundColor: history.map(h => h.alert_flag ? '#ef4444' : '#06b6d4'),
          pointRadius: 4,
          tension: 0.3,
          fill: true
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false }
        },
        scales: {
          x: {
            grid: { color: 'rgba(255, 255, 255, 0.05)' },
            ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 10 } }
          },
          y: {
            grid: { color: 'rgba(255, 255, 255, 0.05)' },
            ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 10 } }
          }
        }
      }
    });
  } catch (err) {
    console.error('Failed to load sensor chart:', err);
  }
}

async function loadInventory() {
  try {
    const res = await fetch('/api/relief/inventory');
    const data = await res.json();
    const tbody = document.getElementById('inventoryTableBody');
    if (!tbody) return;

    tbody.innerHTML = data.map(i => {
      const statusBadge = i.stock_health_status === 'CRITICAL DEPLETION' 
        ? '<span class="badge badge-danger">Depleting Fast</span>' 
        : (i.stock_health_status === 'REORDER SOON' ? '<span class="badge badge-warning">Reorder Soon</span>' : '<span class="badge badge-emerald">Sufficient</span>');

      return `
        <tr>
          <td><strong>${i.camp_name}</strong></td>
          <td>${i.item_name}</td>
          <td><span class="badge badge-info">${i.category}</span></td>
          <td><strong>${i.quantity_available.toLocaleString()}</strong></td>
          <td><strong style="color: ${i.estimated_days_remaining <= 3 ? '#ef4444' : '#38bdf8'}; font-family: var(--font-mono);">${i.estimated_days_remaining} days</strong></td>
          <td>${statusBadge}</td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    console.error('Failed to load inventory:', err);
  }
}

async function refreshMapData() {
  try {
    const [disRes, campRes, snsRes] = await Promise.all([
      fetch('/api/disasters'),
      fetch('/api/camps'),
      fetch('/api/sensors')
    ]);
    const disasters = await disRes.json();
    const camps = await campRes.json();
    const sensors = await snsRes.json();
    renderMapMarkers(disasters, camps, sensors);
  } catch (e) {
    console.error('Map sync error:', e);
  }
}

// ==================== SIMULATION ====================
async function triggerSensorSimulation() {
  showToast('Simulating IoT Telemetry Influx into DuckDB...', 'info');
  try {
    const res = await fetch('/api/sensors/simulate', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast(`Ingested ${data.readings_ingested} telemetry rows. ${data.alerts_triggered} threshold breaches triggered!`, data.alerts_triggered > 0 ? 'danger' : 'success');
      await Promise.all([loadKpis(), loadSensors(), loadSensorChart(currentActiveSensorId)]);
    }
  } catch (err) {
    showToast('Simulation failed: ' + err.message, 'danger');
  }
}

// ==================== SQL CONSOLE ====================
function loadPresetQuery() {
  const select = document.getElementById('presetQueriesSelect');
  const textarea = document.getElementById('sqlQueryInput');
  if (select && textarea && PRESET_QUERIES[select.value]) {
    textarea.value = PRESET_QUERIES[select.value];
  }
}

async function executeCurrentSQL() {
  const textarea = document.getElementById('sqlQueryInput');
  const statusDiv = document.getElementById('sqlExecutionStatus');
  const timeBadge = document.getElementById('sqlTimeBadge');
  const thead = document.getElementById('sqlResultHead');
  const tbody = document.getElementById('sqlResultBody');

  if (!textarea || !textarea.value.trim()) return;

  statusDiv.textContent = 'Executing query via DuckDB Vectorized Engine...';

  try {
    const res = await fetch('/api/sql/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: textarea.value })
    });
    const data = await res.json();

    if (data.success) {
      timeBadge.textContent = `⚡ ${data.execution_time_ms} ms`;
      statusDiv.textContent = `Completed in ${data.execution_time_ms} ms. Returned ${data.row_count} rows across ${data.columns.length} columns.`;

      // Render Table Head
      thead.innerHTML = `<tr>${data.columns.map(col => `<th>${col}</th>`).join('')}</tr>`;

      // Render Table Body
      if (data.rows.length === 0) {
        tbody.innerHTML = `<tr><td colspan="${data.columns.length}" style="text-align: center; color: #64748b; padding: 1.5rem;">Query returned empty result set.</td></tr>`;
      } else {
        tbody.innerHTML = data.rows.map(row => `
          <tr>${row.map(cell => `<td>${cell}</td>`).join('')}</tr>
        `).join('');
      }
    } else {
      timeBadge.textContent = `⚡ Error`;
      statusDiv.innerHTML = `<span style="color: #ef4444;">Error: ${data.error}</span>`;
      tbody.innerHTML = `<tr><td style="color: #ef4444; padding: 1.5rem;">Execution Error: ${data.error}</td></tr>`;
    }
  } catch (err) {
    statusDiv.innerHTML = `<span style="color: #ef4444;">HTTP Request Error: ${err.message}</span>`;
  }
}

// ==================== DROPDOWNS & MODALS ====================
function populateDisasterDropdowns(disasters) {
  const selects = ['deployDisasterSelect', 'vicDisasterSelect', 'dispDisasterSelect'];
  selects.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = disasters.map(d => `
      <option value="${d.disaster_id}">${d.name} (${d.status} - Lvl ${d.severity_level})</option>
    `).join('');
  });
}

function populateCampDropdowns(camps) {
  const selects = ['vicCampSelect', 'dispCampSelect'];
  selects.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = camps.map(c => `
      <option value="${c.camp_id}">${c.camp_name} (${c.available_beds} beds free, ${c.occupancy_pct}% full)</option>
    `).join('');
  });
}

async function updateNearestCampRecommendation() {
  const disId = document.getElementById('vicDisasterSelect')?.value;
  if (!disId) return;

  try {
    const res = await fetch(`/api/analytics/spatial?disaster_id=${disId}`);
    const data = await res.json();
    if (data.camps && data.camps.length > 0) {
      const campSelect = document.getElementById('vicCampSelect');
      if (campSelect) {
        campSelect.innerHTML = data.camps.map(c => `
          <option value="${c.camp_id}">${c.camp_name} [${c.distance_km} km away] (${c.available_beds} beds free)</option>
        `).join('');
      }
    }
  } catch (e) {
    console.error('Nearest camp calc error:', e);
  }
}

function openModal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.classList.add('show');
}

function closeModal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.classList.remove('show');
}

function toggleDisasterSubclassFields() {
  const cl = document.getElementById('disClass').value;
  document.getElementById('subclassNatural').style.display = (cl === 'Natural') ? 'block' : 'none';
  document.getElementById('subclassTech').style.display = (cl === 'Technological') ? 'block' : 'none';
}

// ==================== FORM HANDLERS ====================
async function handleCreateDisaster(e) {
  e.preventDefault();
  const payload = {
    name: document.getElementById('disName').value,
    disaster_type: document.getElementById('disType').value,
    severity_level: parseInt(document.getElementById('disSeverity').value),
    latitude: parseFloat(document.getElementById('disLat').value),
    longitude: parseFloat(document.getElementById('disLon').value),
    impact_radius_km: parseFloat(document.getElementById('disRadius').value),
    estimated_affected_pop: parseInt(document.getElementById('disPop').value),
    classification: document.getElementById('disClass').value,
    wind_speed_kmh: parseFloat(document.getElementById('disWind')?.value || 0),
    flood_depth_m: parseFloat(document.getElementById('disMetric')?.value || 0),
    facility_name: document.getElementById('disFacility')?.value || '',
    hazardous_material_type: document.getElementById('disHazmat')?.value || ''
  };

  try {
    const res = await fetch('/api/disasters', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      showToast('Disaster incident declared and broadcasted!', 'success');
      closeModal('modalDisaster');
      e.target.reset();
      loadAllData();
    }
  } catch (err) {
    showToast('Failed to create incident: ' + err.message, 'danger');
  }
}

async function handleDeployTeam(e) {
  e.preventDefault();
  const payload = {
    disaster_id: document.getElementById('deployDisasterSelect').value,
    team_id: document.getElementById('deployTeamSelect').value,
    operational_sector: document.getElementById('deploySector').value,
    mission_notes: document.getElementById('deployNotes').value
  };

  try {
    const res = await fetch('/api/deploy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      showToast('Rescue battalion dispatched to sector!', 'success');
      closeModal('modalDeployTeam');
      e.target.reset();
      loadAllData();
    }
  } catch (err) {
    showToast('Deployment failed: ' + err.message, 'danger');
  }
}

async function handleRegisterVictim(e) {
  e.preventDefault();
  const payload = {
    full_name: document.getElementById('vicName').value,
    age: parseInt(document.getElementById('vicAge').value),
    gender: document.getElementById('vicGender').value,
    disaster_id: document.getElementById('vicDisasterSelect').value,
    camp_id: document.getElementById('vicCampSelect').value,
    triage_priority: document.getElementById('vicTriage').value,
    medical_conditions: document.getElementById('vicMedical').value
  };

  try {
    const res = await fetch('/api/victims', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      showToast('Evacuee registered and allocated to camp shelter!', 'success');
      closeModal('modalVictim');
      e.target.reset();
      loadAllData();
    } else {
      showToast('Allocation rejected: ' + (data.detail || 'Capacity full'), 'danger');
    }
  } catch (err) {
    showToast('Registration failed: ' + err.message, 'danger');
  }
}

async function handleDispatchSupplies(e) {
  e.preventDefault();
  const payload = {
    disaster_id: document.getElementById('dispDisasterSelect').value,
    camp_id: document.getElementById('dispCampSelect').value,
    item_id: document.getElementById('dispItemSelect').value,
    quantity: parseFloat(document.getElementById('dispQuantity').value)
  };

  try {
    const res = await fetch('/api/relief/dispatch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      showToast('Relief supply consignment dispatched!', 'success');
      closeModal('modalDispatch');
      e.target.reset();
      loadAllData();
    }
  } catch (err) {
    showToast('Dispatch failed: ' + err.message, 'danger');
  }
}

async function handleCreateCamp(e) {
  e.preventDefault();
  const payload = {
    camp_name: document.getElementById('cmpName').value,
    in_charge_name: document.getElementById('cmpOfficer').value,
    contact_phone: document.getElementById('cmpPhone').value,
    latitude: parseFloat(document.getElementById('cmpLat').value),
    longitude: parseFloat(document.getElementById('cmpLon').value),
    max_capacity: parseInt(document.getElementById('cmpCapacity').value),
    medical_support: document.getElementById('cmpMedical').value === 'true'
  };

  try {
    const res = await fetch('/api/camps', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      showToast('Relief shelter camp initialized!', 'success');
      closeModal('modalCamp');
      e.target.reset();
      loadAllData();
    }
  } catch (err) {
    showToast('Failed to create camp: ' + err.message, 'danger');
  }
}

// ==================== TOAST HELPER ====================
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ==================== RELATIONAL TABLES & SCHEMA EXPLORER ====================
let allTablesData = [];
let currentSelectedTable = 'disaster_events';
let currentTableRecordCache = [];
let currentTableColumnsCache = [];

async function loadAllTablesList() {
  try {
    const res = await fetch('/api/schema/tables');
    const data = await res.json();
    allTablesData = data;

    const badge = document.getElementById('badgeTables');
    if (badge) badge.textContent = data.length;

    renderTablesSidebar(allTablesData);

    if (data.length > 0) {
      selectTableView(currentSelectedTable || data[0].table_name);
    }
  } catch (err) {
    console.error('Failed to load tables list:', err);
  }
}

function renderTablesSidebar(tables) {
  const container = document.getElementById('tablesListContainer');
  if (!container) return;

  container.innerHTML = tables.map(t => {
    const isActive = t.table_name === currentSelectedTable;
    let eerBadgeClass = 'table-tag-pill';
    if (t.eer_concept.includes('Superclass')) eerBadgeClass += ' text-cyan';
    else if (t.eer_concept.includes('Weak')) eerBadgeClass += ' text-amber';
    else if (t.eer_concept.includes('Aggregation')) eerBadgeClass += ' text-emerald';

    return `
      <div class="table-item-btn ${isActive ? 'active' : ''}" onclick="selectTableView('${t.table_name}')">
        <div class="table-item-top">
          <span class="table-item-name">${t.table_name}</span>
          <span class="badge badge-info" style="font-size: 0.65rem;">${t.row_count} rows</span>
        </div>
        <div class="table-item-sub">${t.description}</div>
        <div class="table-item-tags">
          <span class="${eerBadgeClass}">${t.eer_concept}</span>
          <span class="table-tag-pill">${t.normal_form}</span>
        </div>
      </div>
    `;
  }).join('');
}

function filterTablesList() {
  const q = document.getElementById('tablesSearchInput')?.value.toLowerCase() || '';
  const filtered = allTablesData.filter(t => 
    t.table_name.toLowerCase().includes(q) || 
    t.description.toLowerCase().includes(q) ||
    t.eer_concept.toLowerCase().includes(q)
  );
  renderTablesSidebar(filtered);
}

async function selectTableView(tableName) {
  currentSelectedTable = tableName;
  renderTablesSidebar(allTablesData);

  try {
    const res = await fetch(`/api/schema/tables/${tableName}`);
    const data = await res.json();

    currentTableColumnsCache = data.columns;
    currentTableRecordCache = data.rows;

    // 1. Update Header Info
    document.getElementById('tblCurrentTitle').textContent = data.table_name;
    document.getElementById('tblCurrentDesc').textContent = data.metadata.description;
    document.getElementById('tblPrimaryKey').textContent = data.metadata.primary_key;
    document.getElementById('tblEerTag').textContent = data.metadata.eer_concept;
    document.getElementById('tblNfTag').textContent = data.metadata.normal_form;
    document.getElementById('tblRowsBadge').textContent = `${data.row_count} Rows in DuckDB`;

    // 2. Render Schema Columns Table
    const schemaBody = document.getElementById('tblSchemaBody');
    if (schemaBody) {
      schemaBody.innerHTML = data.columns.map(col => {
        const isPk = col.key === 'PRI' || col.column_name.includes('_id') && data.metadata.primary_key.includes(col.column_name);
        return `
          <tr>
            <td><code>${col.column_name}</code></td>
            <td><span class="badge badge-info">${col.data_type}</span></td>
            <td>${col.nullable === 'NO' ? '<span class="badge badge-danger">NOT NULL</span>' : '<span class="text-muted">YES</span>'}</td>
            <td>${isPk ? '<span class="badge badge-emerald">PRIMARY KEY</span>' : (col.column_name.endsWith('_id') ? '<span class="badge badge-primary">FOREIGN KEY</span>' : '-')}</td>
            <td><code style="font-size: 0.72rem;">${col.default || 'NULL'}</code></td>
          </tr>
        `;
      }).join('');
    }

    // 3. Render Live Records Table
    renderLiveRecordsTable(data.columns, data.rows);
  } catch (err) {
    console.error('Failed to load table details:', err);
  }
}

function renderLiveRecordsTable(columns, rows) {
  const thead = document.getElementById('tblRecordsHead');
  const tbody = document.getElementById('tblRecordsBody');
  if (!thead || !tbody) return;

  thead.innerHTML = `<tr>${columns.map(c => `<th>${c.column_name}</th>`).join('')}</tr>`;

  if (!rows || rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="${columns.length}" style="text-align: center; color: #64748b; padding: 2rem;">No tuples recorded in this relation.</td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map(row => `
    <tr>
      ${columns.map(c => {
        let val = row[c.column_name];
        if (val === null || val === undefined) return '<td class="text-muted">NULL</td>';
        if (typeof val === 'boolean') return `<td><span class="badge ${val ? 'badge-danger' : 'badge-emerald'}">${val}</span></td>`;
        return `<td>${val}</td>`;
      }).join('')}
    </tr>
  `).join('');
}

function filterRecordRows() {
  const q = document.getElementById('recordSearchInput')?.value.toLowerCase() || '';
  if (!q) {
    renderLiveRecordsTable(currentTableColumnsCache, currentTableRecordCache);
    return;
  }

  const filtered = currentTableRecordCache.filter(row => {
    return Object.values(row).some(v => v !== null && String(v).toLowerCase().includes(q));
  });

  renderLiveRecordsTable(currentTableColumnsCache, filtered);
}

function reloadCurrentTableRecords() {
  if (currentSelectedTable) {
    selectTableView(currentSelectedTable);
    showToast(`Refreshed live data for ${currentSelectedTable}`, 'info');
  }
}

// ==================== DEMONSTRATION VIDEO & SYSTEM TOUR ====================
function seekDemoChapter(chNum, tabId, chTitle) {
  // Update Chapter Buttons
  const buttons = document.querySelectorAll('.chapter-card');
  buttons.forEach((b, idx) => {
    if (idx + 1 === chNum) b.classList.add('active');
    else b.classList.remove('active');
  });

  // Update Badge
  const badge = document.getElementById('videoCurrentChapterBadge');
  if (badge) {
    badge.textContent = `Chapter ${chNum}: ${chTitle}`;
  }

  // Video time jump simulation (15s per chapter)
  const video = document.getElementById('demoVideoPlayer');
  if (video && video.duration) {
    video.currentTime = (chNum - 1) * 15;
  }

  showToast(`Chapter ${chNum}: ${chTitle}`, 'info');

  // Smooth switch tab if clicked directly
  setTimeout(() => {
    const navTab = document.querySelector(`.nav-tab[data-tab="${tabId}"]`);
    if (navTab) {
      navTab.click();
    }
  }, 400);
}

async function runInteractiveDemoStep(stepKey) {
  if (stepKey === 'surge') {
    await triggerSensorSimulation();
    const navTab = document.querySelector('.nav-tab[data-tab="tab-sensors"]');
    if (navTab) navTab.click();
  } else if (stepKey === 'spatial') {
    const navTab = document.querySelector('.nav-tab[data-tab="tab-analytics"]');
    if (navTab) {
      navTab.click();
      const select = document.getElementById('presetQueriesSelect');
      if (select) {
        select.value = 'spatial';
        loadPresetQuery();
        setTimeout(executeCurrentSQL, 200);
      }
    }
  } else if (stepKey === 'inspect_tables') {
    const navTab = document.querySelector('.nav-tab[data-tab="tab-tables"]');
    if (navTab) {
      navTab.click();
      setTimeout(() => selectTableView('rescued_individuals'), 200);
    }
  }
}

