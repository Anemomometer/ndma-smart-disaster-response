import os
import random
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.database import get_connection, init_db, fetch_as_dicts
from backend.queries import (
    run_camp_occupancy_analysis,
    run_spatial_nearest_camps,
    run_iot_moving_average_and_anomalies,
    run_relief_burn_rate,
    run_triage_demographic_rollup,
    execute_user_sql
)

# Ensure DB initialized
init_db(force_reinit=False)

app = FastAPI(
    title="Smart Disaster Response Coordination System (NDMA)",
    description="Vectorized DuckDB OLAP Analytical Database & Command Center",
    version="2.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

# ==================== Pydantic Models ====================
class DisasterCreate(BaseModel):
    name: str
    disaster_type: str
    severity_level: int
    latitude: float
    longitude: float
    impact_radius_km: float
    estimated_affected_pop: int = 0
    classification: str = "Natural" # "Natural" or "Technological"
    meteorological_category: Optional[str] = None
    wind_speed_kmh: Optional[float] = None
    seismic_magnitude: Optional[float] = None
    flood_depth_m: Optional[float] = None
    facility_name: Optional[str] = None
    hazardous_material_type: Optional[str] = None

class RescueTeamDeploy(BaseModel):
    disaster_id: str
    team_id: str
    operational_sector: str
    mission_notes: Optional[str] = None

class VictimRegister(BaseModel):
    full_name: str
    age: int
    gender: str
    disaster_id: str
    camp_id: Optional[str] = None
    triage_priority: str
    medical_conditions: Optional[str] = None

class ReliefDispatch(BaseModel):
    disaster_id: str
    camp_id: str
    item_id: str
    quantity: float

class CampCreate(BaseModel):
    camp_name: str
    in_charge_name: str
    contact_phone: str
    latitude: float
    longitude: float
    max_capacity: int
    medical_support: bool = True

class SQLRequest(BaseModel):
    query: str

# ==================== Core Endpoints ====================

@app.get("/api/kpi")
def get_kpi_metrics():
    """Retrieve top-level disaster command center KPI metrics."""
    conn = get_connection()
    try:
        active_disasters = conn.execute("SELECT count(*) FROM disaster_events WHERE status = 'Active'").fetchone()[0]
        total_evacuees = conn.execute("SELECT count(*) FROM rescued_individuals").fetchone()[0]
        deployed_teams = conn.execute("SELECT count(*) FROM rescue_teams WHERE readiness_status = 'Deployed'").fetchone()[0]
        
        camp_stats = conn.execute("""
            SELECT 
                COALESCE(SUM(max_capacity), 0) AS total_cap,
                COALESCE(SUM(current_occupancy), 0) AS total_occ
            FROM relief_camps
        """).fetchone()
        tot_cap = camp_stats[0]
        tot_occ = camp_stats[1]
        occ_pct = round((tot_occ * 100.0 / tot_cap), 1) if tot_cap > 0 else 0.0

        active_alerts = conn.execute("SELECT count(*) FROM iot_sensors WHERE status IN ('Warning', 'Critical')").fetchone()[0]
        economic_loss = conn.execute("SELECT COALESCE(SUM(estimated_loss_usd), 0) FROM damage_assessments").fetchone()[0]
        
        return {
            "active_disasters": active_disasters,
            "total_evacuees": total_evacuees,
            "deployed_teams": deployed_teams,
            "camp_capacity": tot_cap,
            "camp_occupancy": tot_occ,
            "occupancy_rate_pct": occ_pct,
            "active_iot_alerts": active_alerts,
            "total_economic_loss_usd": economic_loss
        }
    finally:
        conn.close()

@app.get("/api/disasters")
def list_disasters(status: Optional[str] = None, severity: Optional[int] = None):
    """Retrieve disaster events with combined subclass attributes and operational tallies."""
    conn = get_connection()
    try:
        query = """
        SELECT 
            d.disaster_id,
            d.name,
            d.disaster_type,
            d.severity_level,
            d.start_time,
            d.end_time,
            d.status,
            d.latitude,
            d.longitude,
            d.impact_radius_km,
            d.estimated_affected_pop,
            n.meteorological_category,
            n.wind_speed_kmh,
            n.seismic_magnitude,
            n.flood_depth_m,
            t.facility_name,
            t.hazardous_material_type,
            t.containment_status,
            (SELECT COUNT(*) FROM rescued_individuals r WHERE r.disaster_id = d.disaster_id) AS total_evacuated,
            (SELECT COUNT(*) FROM rescue_deployments dep WHERE dep.disaster_id = d.disaster_id) AS teams_deployed
        FROM disaster_events d
        LEFT JOIN natural_disasters n ON d.disaster_id = n.disaster_id
        LEFT JOIN technological_disasters t ON d.disaster_id = t.disaster_id
        WHERE 1=1
        """
        params = []
        if status:
            query += " AND d.status = ?"
            params.append(status)
        if severity:
            query += " AND d.severity_level = ?"
            params.append(severity)
        
        query += " ORDER BY d.status ASC, d.severity_level DESC, d.start_time DESC"
        
        return fetch_as_dicts(conn, query, params)
    finally:
        conn.close()

@app.post("/api/disasters")
def create_disaster(payload: DisasterCreate):
    """Create a new disaster event and record its EER subclass details."""
    conn = get_connection()
    try:
        count = conn.execute("SELECT count(*) FROM disaster_events").fetchone()[0]
        disaster_id = f"DIS-2026-{str(count + 1).zfill(3)}"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute("""
            INSERT INTO disaster_events VALUES (?, ?, ?, ?, ?, NULL, 'Active', ?, ?, ?, ?)
        """, [
            disaster_id, payload.name, payload.disaster_type, payload.severity_level,
            now_str, payload.latitude, payload.longitude, payload.impact_radius_km,
            payload.estimated_affected_pop
        ])

        if payload.classification == "Natural":
            conn.execute("""
                INSERT INTO natural_disasters VALUES (?, ?, ?, ?, ?)
            """, [
                disaster_id, payload.meteorological_category or payload.disaster_type,
                payload.wind_speed_kmh or 0.0, payload.seismic_magnitude or 0.0, payload.flood_depth_m or 0.0
            ])
        else:
            conn.execute("""
                INSERT INTO technological_disasters VALUES (?, ?, ?, ?, ?)
            """, [
                disaster_id, payload.facility_name or "Industrial Facility",
                payload.hazardous_material_type or "Toxic Substance", "Active Release", "Containment in progress"
            ])

        return {"success": True, "disaster_id": disaster_id, "message": "Disaster event successfully created"}
    finally:
        conn.close()

@app.get("/api/camps")
def list_camps():
    """Retrieve all relief camps with capacity utilization and vacancy numbers."""
    conn = get_connection()
    try:
        query = """
            SELECT 
                c.camp_id,
                c.camp_name,
                c.in_charge_name,
                c.contact_phone,
                c.latitude,
                c.longitude,
                c.max_capacity,
                c.current_occupancy,
                (c.max_capacity - c.current_occupancy) AS available_beds,
                ROUND((c.current_occupancy * 100.0) / c.max_capacity, 1) AS occupancy_pct,
                c.medical_support,
                (SELECT COUNT(*) FROM camp_inventory i WHERE i.camp_id = c.camp_id) AS distinct_inventory_types
            FROM relief_camps c
            ORDER BY occupancy_pct DESC
        """
        return fetch_as_dicts(conn, query)
    finally:
        conn.close()

@app.post("/api/camps")
def create_camp(payload: CampCreate):
    """Add a new relief camp."""
    conn = get_connection()
    try:
        count = conn.execute("SELECT count(*) FROM relief_camps").fetchone()[0]
        camp_id = f"CMP-GEN-{str(count + 1).zfill(2)}"
        conn.execute("""
            INSERT INTO relief_camps VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
        """, [
            camp_id, payload.camp_name, payload.in_charge_name, payload.contact_phone,
            payload.latitude, payload.longitude, payload.max_capacity, payload.medical_support
        ])
        return {"success": True, "camp_id": camp_id, "message": "Relief camp initialized."}
    finally:
        conn.close()

@app.get("/api/teams")
def list_teams():
    """List rescue teams with agency details, assigned vehicles, and deployment logs."""
    conn = get_connection()
    try:
        query = """
            SELECT 
                t.team_id,
                t.team_name,
                t.team_type,
                t.member_count,
                t.readiness_status,
                t.base_location,
                a.agency_name,
                a.agency_type,
                (SELECT string_agg(v.vehicle_type || ' (' || v.registration_no || ')', ', ')
                 FROM emergency_vehicles v WHERE v.team_id = t.team_id) AS assigned_vehicles,
                d.name AS active_disaster_name,
                dep.operational_sector
            FROM rescue_teams t
            JOIN agencies a ON t.agency_id = a.agency_id
            LEFT JOIN (
                SELECT disaster_id, team_id, operational_sector, ROW_NUMBER() OVER (PARTITION BY team_id ORDER BY dispatched_at DESC) as rn
                FROM rescue_deployments
                WHERE demobilized_at IS NULL
            ) dep ON t.team_id = dep.team_id AND dep.rn = 1
            LEFT JOIN disaster_events d ON dep.disaster_id = d.disaster_id
            ORDER BY t.readiness_status ASC, t.team_id ASC
        """
        return fetch_as_dicts(conn, query)
    finally:
        conn.close()

@app.post("/api/deploy")
def deploy_team(payload: RescueTeamDeploy):
    """Deploy a rescue team to a disaster event."""
    conn = get_connection()
    try:
        count = conn.execute("SELECT count(*) FROM rescue_deployments").fetchone()[0]
        dep_id = f"DEP-{str(count + 1).zfill(3)}"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute("""
            INSERT INTO rescue_deployments VALUES (?, ?, ?, ?, NULL, ?, ?)
        """, [
            dep_id, payload.disaster_id, payload.team_id, now_str,
            payload.operational_sector, payload.mission_notes or "Rapid Deployment"
        ])

        conn.execute("""
            UPDATE rescue_teams SET readiness_status = 'Deployed' WHERE team_id = ?
        """, [payload.team_id])

        return {"success": True, "deployment_id": dep_id, "message": "Team deployed successfully."}
    finally:
        conn.close()

@app.get("/api/victims")
def list_victims(disaster_id: Optional[str] = None, camp_id: Optional[str] = None, triage: Optional[str] = None):
    """List rescued individuals with associated dependents and triage info."""
    conn = get_connection()
    try:
        query = """
            SELECT 
                r.individual_id,
                r.full_name,
                r.age,
                r.gender,
                r.rescue_timestamp,
                r.triage_priority,
                r.medical_conditions,
                d.name AS disaster_name,
                c.camp_name,
                (SELECT COUNT(*) FROM dependent_family_members df WHERE df.individual_id = r.individual_id) AS dependent_count
            FROM rescued_individuals r
            JOIN disaster_events d ON r.disaster_id = d.disaster_id
            LEFT JOIN relief_camps c ON r.camp_id = c.camp_id
            WHERE 1=1
        """
        params = []
        if disaster_id:
            query += " AND r.disaster_id = ?"
            params.append(disaster_id)
        if camp_id:
            query += " AND r.camp_id = ?"
            params.append(camp_id)
        if triage:
            query += " AND r.triage_priority = ?"
            params.append(triage)
        
        query += " ORDER BY r.rescue_timestamp DESC"
        return fetch_as_dicts(conn, query, params)
    finally:
        conn.close()

@app.post("/api/victims")
def register_victim(payload: VictimRegister):
    """Register an evacuee and allocate to camp, updating occupancy constraints."""
    conn = get_connection()
    try:
        if payload.camp_id:
            camp = conn.execute("SELECT max_capacity, current_occupancy, camp_name FROM relief_camps WHERE camp_id = ?", [payload.camp_id]).fetchone()
            if not camp:
                raise HTTPException(status_code=400, detail="Invalid Camp ID")
            if camp[1] >= camp[0]:
                raise HTTPException(status_code=400, detail=f"Camp {camp[2]} is currently at maximum capacity ({camp[0]}/{camp[0]}). Select another camp.")

        count = conn.execute("SELECT count(*) FROM rescued_individuals").fetchone()[0]
        ind_id = f"IND-{str(count + 1).zfill(3)}"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute("""
            INSERT INTO rescued_individuals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            ind_id, payload.full_name, payload.age, payload.gender,
            now_str, payload.disaster_id, payload.camp_id, payload.triage_priority,
            payload.medical_conditions or "Stable"
        ])

        if payload.camp_id:
            conn.execute("UPDATE relief_camps SET current_occupancy = current_occupancy + 1 WHERE camp_id = ?", [payload.camp_id])

        return {"success": True, "individual_id": ind_id, "message": "Evacuee registered and allocated."}
    finally:
        conn.close()

@app.get("/api/sensors")
def list_sensors():
    """Retrieve IoT sensors with latest telemetry reading and status indicator."""
    conn = get_connection()
    try:
        query = """
            WITH LatestTelemetry AS (
                SELECT 
                    sensor_id,
                    reading_value,
                    recorded_at,
                    battery_level_pct,
                    alert_flag,
                    ROW_NUMBER() OVER (PARTITION BY sensor_id ORDER BY recorded_at DESC) as rn
                FROM sensor_telemetry
            )
            SELECT 
                s.sensor_id,
                s.sensor_type,
                s.model_no,
                s.location_name,
                s.latitude,
                s.longitude,
                s.threshold_limit,
                s.unit_of_measure,
                s.status,
                lt.reading_value AS latest_reading,
                lt.recorded_at AS latest_reading_time,
                lt.battery_level_pct,
                lt.alert_flag
            FROM iot_sensors s
            LEFT JOIN LatestTelemetry lt ON s.sensor_id = lt.sensor_id AND lt.rn = 1
            ORDER BY 
                CASE s.status WHEN 'Critical' THEN 1 WHEN 'Warning' THEN 2 WHEN 'Active' THEN 3 ELSE 4 END,
                s.sensor_id ASC
        """
        return fetch_as_dicts(conn, query)
    finally:
        conn.close()

@app.get("/api/sensors/{sensor_id}/telemetry")
def get_sensor_history(sensor_id: str):
    """Retrieve the time series telemetry logs for a given sensor."""
    conn = get_connection()
    try:
        query = """
            SELECT recorded_at, reading_value, battery_level_pct, alert_flag
            FROM sensor_telemetry
            WHERE sensor_id = ?
            ORDER BY recorded_at ASC
        """
        return fetch_as_dicts(conn, query, [sensor_id])
    finally:
        conn.close()

@app.post("/api/sensors/simulate")
def simulate_sensor_influx():
    """
    Simulates real-time IoT sensor telemetry ingestion.
    Demonstrates DuckDB's high-speed batch appending and dynamic status update.
    """
    conn = get_connection()
    try:
        sensors = conn.execute("SELECT sensor_id, threshold_limit, status FROM iot_sensors").fetchall()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_records = []
        alerts_triggered = 0

        for s_id, thresh, _ in sensors:
            spike_factor = random.choice([1.0, 1.0, 1.05, 1.25])
            val = round(thresh * random.uniform(0.7, 1.15) * spike_factor, 2)
            is_alert = (val >= thresh)
            if is_alert:
                alerts_triggered += 1
            batt = round(random.uniform(80.0, 99.0), 1)
            new_records.append((s_id, now_str, val, batt, is_alert))

            new_status = 'Critical' if val >= thresh * 1.15 else ('Warning' if val >= thresh else 'Active')
            conn.execute("UPDATE iot_sensors SET status = ? WHERE sensor_id = ?", [new_status, s_id])

        conn.executemany("INSERT INTO sensor_telemetry VALUES (?, ?, ?, ?, ?)", new_records)

        return {
            "success": True,
            "readings_ingested": len(new_records),
            "alerts_triggered": alerts_triggered,
            "timestamp": now_str
        }
    finally:
        conn.close()

@app.get("/api/relief/inventory")
def list_camp_inventory():
    """List supplies stored across camps with health warnings."""
    return run_relief_burn_rate()

@app.post("/api/relief/dispatch")
def dispatch_relief(payload: ReliefDispatch):
    """Dispatch relief supplies from master depot to a camp."""
    conn = get_connection()
    try:
        count = conn.execute("SELECT count(*) FROM relief_distributions").fetchone()[0]
        dist_id = f"DIST-{str(count + 1).zfill(3)}"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute("""
            INSERT INTO relief_distributions VALUES (?, ?, ?, ?, ?, ?, 'Delivered')
        """, [dist_id, payload.disaster_id, payload.camp_id, payload.item_id, payload.quantity, now_str])

        existing = conn.execute("SELECT quantity_available FROM camp_inventory WHERE camp_id = ? AND item_id = ?", [payload.camp_id, payload.item_id]).fetchone()
        if existing:
            conn.execute("""
                UPDATE camp_inventory 
                SET quantity_available = quantity_available + ?, last_replenished_at = ?
                WHERE camp_id = ? AND item_id = ?
            """, [payload.quantity, now_str, payload.camp_id, payload.item_id])
        else:
            conn.execute("""
                INSERT INTO camp_inventory VALUES (?, ?, ?, 50.0, ?)
            """, [payload.camp_id, payload.item_id, payload.quantity, now_str])

        return {"success": True, "distribution_id": dist_id, "message": "Relief shipment dispatched and inventory credited."}
    finally:
        conn.close()

@app.get("/api/assessments")
def list_assessments():
    """List post-disaster damage assessments."""
    conn = get_connection()
    try:
        query = """
            SELECT 
                a.assessment_id,
                a.disaster_id,
                d.name AS disaster_name,
                a.surveyor_name,
                a.damage_score,
                a.estimated_loss_usd,
                a.houses_destroyed,
                a.report_date,
                a.notes
            FROM damage_assessments a
            JOIN disaster_events d ON a.disaster_id = d.disaster_id
            ORDER BY a.damage_score DESC
        """
        return fetch_as_dicts(conn, query)
    finally:
        conn.close()

# ==================== Advanced DuckDB Analytics ====================

@app.get("/api/analytics/occupancy")
def analytics_occupancy():
    return run_camp_occupancy_analysis()

@app.get("/api/analytics/spatial")
def analytics_spatial(disaster_id: Optional[str] = "DIS-2026-001"):
    return run_spatial_nearest_camps(disaster_id=disaster_id)

@app.get("/api/analytics/telemetry-window")
def analytics_telemetry_window():
    return run_iot_moving_average_and_anomalies()

@app.get("/api/analytics/burn-rate")
def analytics_burn_rate():
    return run_relief_burn_rate()

@app.get("/api/analytics/triage")
def analytics_triage():
    return run_triage_demographic_rollup()

@app.post("/api/sql/execute")
def sql_console(payload: SQLRequest):
    return execute_user_sql(payload.query)

# ==================== Table Schema & Live Data Explorer ====================

TABLES_METADATA = {
    "disaster_events": {
        "description": "Core entity storing all natural and technological disaster events",
        "primary_key": "disaster_id",
        "eer_concept": "Superclass Entity",
        "normal_form": "3NF / BCNF"
    },
    "natural_disasters": {
        "description": "Specialized subclass for meteorological & seismic hazards (wind, flood, magnitude)",
        "primary_key": "disaster_id",
        "eer_concept": "Disjoint Subclass",
        "normal_form": "3NF / BCNF"
    },
    "technological_disasters": {
        "description": "Specialized subclass for industrial/CBRN catastrophes (facility, hazmat, containment)",
        "primary_key": "disaster_id",
        "eer_concept": "Disjoint Subclass",
        "normal_form": "3NF / BCNF"
    },
    "agencies": {
        "description": "Federal, state, military, and NGO response coordination agencies",
        "primary_key": "agency_id",
        "eer_concept": "Strong Entity",
        "normal_form": "3NF / BCNF"
    },
    "rescue_teams": {
        "description": "Mobilized battalions, search & rescue squads, medical triage units",
        "primary_key": "team_id",
        "eer_concept": "Strong Entity",
        "normal_form": "3NF / BCNF"
    },
    "emergency_vehicles": {
        "description": "Specialized transport assets (Ambulances, Zodiac Boats, Choppers, Heavy Clearance)",
        "primary_key": "vehicle_id",
        "eer_concept": "Strong Entity",
        "normal_form": "3NF / BCNF"
    },
    "relief_camps": {
        "description": "Temporary shelter facilities with capacity, current occupancy, and medical support",
        "primary_key": "camp_id",
        "eer_concept": "Strong Entity",
        "normal_form": "3NF / BCNF"
    },
    "rescued_individuals": {
        "description": "Evacuated victims with triage classifications, disaster origin, and camp allocation",
        "primary_key": "individual_id",
        "eer_concept": "Strong Entity",
        "normal_form": "3NF / BCNF"
    },
    "dependent_family_members": {
        "description": "Victim family dependents (children, elderly) existence-dependent on victim",
        "primary_key": "(individual_id, dependent_seq)",
        "eer_concept": "Weak Entity",
        "normal_form": "3NF / BCNF"
    },
    "relief_items": {
        "description": "Master catalog of emergency relief materials (Water, Food Rations, Trauma Kits)",
        "primary_key": "item_id",
        "eer_concept": "Strong Entity",
        "normal_form": "3NF / BCNF"
    },
    "camp_inventory": {
        "description": "Stock levels, replenishment dates, and reorder thresholds across relief camps",
        "primary_key": "(camp_id, item_id)",
        "eer_concept": "Associative Entity (M:N)",
        "normal_form": "3NF / BCNF"
    },
    "rescue_deployments": {
        "description": "Active deployment of rescue teams to specific disaster zones with operational sector",
        "primary_key": "deployment_id",
        "eer_concept": "Aggregation Entity",
        "normal_form": "3NF / BCNF"
    },
    "relief_distributions": {
        "description": "Supply distribution logs dispatched from central depots to relief camps",
        "primary_key": "distribution_id",
        "eer_concept": "Relationship Relation",
        "normal_form": "3NF / BCNF"
    },
    "damage_assessments": {
        "description": "Post-disaster structural damage scores, monetary losses, and destroyed housing surveys",
        "primary_key": "assessment_id",
        "eer_concept": "Strong Entity",
        "normal_form": "3NF / BCNF"
    },
    "communication_logs": {
        "description": "Inter-agency flash communications and emergency dispatch directives",
        "primary_key": "log_id",
        "eer_concept": "Communication Relation",
        "normal_form": "3NF / BCNF"
    },
    "iot_sensors": {
        "description": "Early warning telemetry stations (River level, weather, seismic, toxic gas)",
        "primary_key": "sensor_id",
        "eer_concept": "Strong Entity",
        "normal_form": "3NF / BCNF"
    },
    "sensor_telemetry": {
        "description": "High-frequency time-series telemetry readings with threshold breach flags",
        "primary_key": "(sensor_id, recorded_at)",
        "eer_concept": "Weak Entity",
        "normal_form": "3NF / BCNF"
    }
}

@app.get("/api/schema/tables")
def get_all_tables():
    conn = get_connection()
    try:
        tables_summary = []
        for tbl, meta in TABLES_METADATA.items():
            try:
                row_cnt = conn.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
            except Exception:
                row_cnt = 0
            tables_summary.append({
                "table_name": tbl,
                "row_count": row_cnt,
                **meta
            })
        return tables_summary
    finally:
        conn.close()

@app.get("/api/schema/tables/{table_name}")
def get_table_details(table_name: str):
    if table_name not in TABLES_METADATA:
        raise HTTPException(status_code=404, detail="Table not found in NDMA schema")
    
    conn = get_connection()
    try:
        desc_rows = conn.execute(f"DESCRIBE {table_name}").fetchall()
        columns = []
        for col in desc_rows:
            columns.append({
                "column_name": col[0],
                "data_type": col[1],
                "nullable": col[2],
                "key": col[3],
                "default": str(col[4]) if col[4] is not None else None
            })
        
        rows = fetch_as_dicts(conn, f"SELECT * FROM {table_name} LIMIT 100")
        
        return {
            "table_name": table_name,
            "metadata": TABLES_METADATA[table_name],
            "columns": columns,
            "row_count": len(rows),
            "rows": rows
        }
    finally:
        conn.close()

# ==================== Static Frontend Serving ====================

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
def serve_home():
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Smart Disaster Response Backend Operational. Frontend index not found."}
