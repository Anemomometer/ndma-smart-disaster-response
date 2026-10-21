import time
import duckdb
from backend.database import get_connection, fetch_as_dicts

def run_camp_occupancy_analysis():
    """Calculates occupancy percentage, remaining vacancy, and risk level across all camps."""
    conn = get_connection()
    sql = """
    SELECT 
        c.camp_id,
        c.camp_name,
        c.in_charge_name,
        c.contact_phone,
        c.max_capacity,
        c.current_occupancy,
        (c.max_capacity - c.current_occupancy) AS available_beds,
        ROUND((c.current_occupancy * 100.0) / c.max_capacity, 1) AS occupancy_pct,
        CASE 
            WHEN (c.current_occupancy * 100.0) / c.max_capacity >= 90.0 THEN 'CRITICAL (Near Capacity)'
            WHEN (c.current_occupancy * 100.0) / c.max_capacity >= 75.0 THEN 'HIGH ALERT'
            ELSE 'STABLE'
        END AS capacity_risk_status,
        c.medical_support,
        COUNT(r.individual_id) AS registered_evacuees
    FROM relief_camps c
    LEFT JOIN rescued_individuals r ON c.camp_id = r.camp_id
    GROUP BY c.camp_id, c.camp_name, c.in_charge_name, c.contact_phone, c.max_capacity, c.current_occupancy, c.medical_support
    ORDER BY occupancy_pct DESC;
    """
    records = fetch_as_dicts(conn, sql)
    conn.close()
    return records

def run_spatial_nearest_camps(disaster_id=None, lat=None, lon=None):
    """
    Computes Haversine spherical distance (in km) from a disaster epicenter
    to all active relief camps directly inside DuckDB SQL.
    """
    conn = get_connection()
    if disaster_id:
        res = conn.execute("SELECT latitude, longitude, name FROM disaster_events WHERE disaster_id = ?", [disaster_id]).fetchone()
        if not res:
            conn.close()
            return {"disaster_name": "Not Found", "origin_lat": 0, "origin_lon": 0, "camps": []}
        d_lat, d_lon, d_name = res[0], res[1], res[2]
    else:
        d_lat, d_lon, d_name = lat or 19.8135, lon or 85.8312, "Custom Coordinate Pin"

    sql = f"""
    SELECT 
        c.camp_id,
        c.camp_name,
        c.latitude AS camp_lat,
        c.longitude AS camp_lon,
        c.max_capacity,
        c.current_occupancy,
        (c.max_capacity - c.current_occupancy) AS available_beds,
        c.medical_support,
        ROUND(
            2 * 6371 * ASIN(SQRT(
                POWER(SIN(RADIANS(c.latitude - {d_lat}) / 2), 2) +
                COS(RADIANS({d_lat})) * COS(RADIANS(c.latitude)) *
                POWER(SIN(RADIANS(c.longitude - {d_lon}) / 2), 2)
            )), 2
        ) AS distance_km
    FROM relief_camps c
    ORDER BY distance_km ASC;
    """
    records = fetch_as_dicts(conn, sql)
    conn.close()
    return {"disaster_name": d_name, "origin_lat": d_lat, "origin_lon": d_lon, "camps": records}

def run_iot_moving_average_and_anomalies():
    """
    Uses DuckDB SQL Window Functions to compute 3-period moving average and detect sudden spikes.
    """
    conn = get_connection()
    sql = """
    WITH WindowedTelemetry AS (
        SELECT 
            t.sensor_id,
            s.sensor_type,
            s.location_name,
            s.threshold_limit,
            s.unit_of_measure,
            t.recorded_at,
            t.reading_value,
            t.alert_flag,
            ROUND(AVG(t.reading_value) OVER (
                PARTITION BY t.sensor_id 
                ORDER BY t.recorded_at 
                ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
            ), 2) AS moving_avg_3p,
            ROUND(t.reading_value - AVG(t.reading_value) OVER (
                PARTITION BY t.sensor_id 
                ORDER BY t.recorded_at 
                ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
            ), 2) AS variance_from_avg
        FROM sensor_telemetry t
        JOIN iot_sensors s ON t.sensor_id = s.sensor_id
    )
    SELECT * 
    FROM WindowedTelemetry
    ORDER BY recorded_at DESC, sensor_id ASC
    LIMIT 25;
    """
    records = fetch_as_dicts(conn, sql)
    conn.close()
    return records

def run_relief_burn_rate():
    """
    Computes stock burn rate and days of inventory remaining at relief camps.
    """
    conn = get_connection()
    sql = """
    SELECT 
        c.camp_id,
        c.camp_name,
        c.current_occupancy,
        i.item_id,
        r.item_name,
        r.category,
        i.quantity_available,
        i.reorder_threshold,
        CASE 
            WHEN r.category = 'Water' THEN ROUND(i.quantity_available / GREATEST(1, c.current_occupancy * 0.15), 1)
            WHEN r.category = 'Food' THEN ROUND(i.quantity_available / GREATEST(1, c.current_occupancy * 2), 1)
            ELSE ROUND(i.quantity_available / GREATEST(1, c.current_occupancy * 0.1), 1)
        END AS estimated_days_remaining,
        CASE 
            WHEN i.quantity_available <= i.reorder_threshold THEN 'CRITICAL DEPLETION'
            WHEN i.quantity_available <= i.reorder_threshold * 1.5 THEN 'REORDER SOON'
            ELSE 'SUFFICIENT'
        END AS stock_health_status
    FROM camp_inventory i
    JOIN relief_camps c ON i.camp_id = c.camp_id
    JOIN relief_items r ON i.item_id = r.item_id
    ORDER BY estimated_days_remaining ASC;
    """
    records = fetch_as_dicts(conn, sql)
    conn.close()
    return records

def run_triage_demographic_rollup():
    """
    Rollup analysis of rescued evacuees by Triage Priority and Age Bracket.
    """
    conn = get_connection()
    sql = """
    SELECT 
        d.name AS disaster_name,
        d.disaster_type,
        r.triage_priority,
        COUNT(r.individual_id) AS total_rescued,
        SUM(CASE WHEN r.age < 18 THEN 1 ELSE 0 END) AS minors,
        SUM(CASE WHEN r.age BETWEEN 18 AND 60 THEN 1 ELSE 0 END) AS adults,
        SUM(CASE WHEN r.age > 60 THEN 1 ELSE 0 END) AS elderly,
        SUM(CASE WHEN r.gender = 'Female' THEN 1 ELSE 0 END) AS females,
        SUM(CASE WHEN r.gender = 'Male' THEN 1 ELSE 0 END) AS males
    FROM rescued_individuals r
    JOIN disaster_events d ON r.disaster_id = d.disaster_id
    GROUP BY d.name, d.disaster_type, r.triage_priority
    ORDER BY d.name, r.triage_priority;
    """
    records = fetch_as_dicts(conn, sql)
    conn.close()
    return records

def execute_user_sql(query_str: str):
    """
    Executes ad-hoc read-only SQL query on the DuckDB instance with execution timing.
    """
    conn = get_connection()
    start = time.perf_counter()
    try:
        q_clean = query_str.strip().upper()
        if not (q_clean.startswith("SELECT") or q_clean.startswith("WITH") or q_clean.startswith("DESCRIBE") or q_clean.startswith("PRAGMA") or q_clean.startswith("SHOW")):
            raise ValueError("Only analytical read-only queries (SELECT, WITH, DESCRIBE, SHOW, PRAGMA) are permitted in this console.")
        
        cursor = conn.execute(query_str)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        
        clean_rows = []
        for row in rows:
            clean_rows.append([str(v) if v is not None else "NULL" for v in row])

        conn.close()
        return {
            "success": True,
            "columns": columns,
            "rows": clean_rows,
            "row_count": len(rows),
            "execution_time_ms": elapsed_ms
        }
    except Exception as e:
        conn.close()
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "success": False,
            "error": str(e),
            "execution_time_ms": elapsed_ms
        }
