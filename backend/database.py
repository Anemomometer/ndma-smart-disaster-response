import os
import duckdb
from datetime import datetime, timedelta
import random

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "disaster_response.duckdb")

def get_connection():
    """Get a DuckDB connection to the database file."""
    conn = duckdb.connect(database=DB_FILE, read_only=False)
    return conn

def init_db(force_reinit=False):
    """Initialize the DuckDB schema and populate with rich seed data."""
    if force_reinit and os.path.exists(DB_FILE):
        try:
            os.remove(DB_FILE)
            print("[Database] Existing database removed for clean re-init.")
        except Exception as e:
            print(f"[Database] Could not remove existing db: {e}")

    conn = get_connection()

    # Create tables conforming strictly to 3NF relational design
    conn.execute("""
    -- 1. Agencies Table
    CREATE TABLE IF NOT EXISTS agencies (
        agency_id VARCHAR PRIMARY KEY,
        agency_name VARCHAR NOT NULL,
        agency_type VARCHAR NOT NULL,
        contact_phone VARCHAR,
        headquarters VARCHAR
    );

    -- 2. Disaster Events Table (Superclass)
    CREATE TABLE IF NOT EXISTS disaster_events (
        disaster_id VARCHAR PRIMARY KEY,
        name VARCHAR NOT NULL,
        disaster_type VARCHAR NOT NULL,
        severity_level INTEGER CHECK (severity_level BETWEEN 1 AND 5),
        start_time TIMESTAMP NOT NULL,
        end_time TIMESTAMP,
        status VARCHAR CHECK (status IN ('Active', 'Contained', 'Resolved')),
        latitude DOUBLE NOT NULL,
        longitude DOUBLE NOT NULL,
        impact_radius_km DOUBLE NOT NULL,
        estimated_affected_pop INTEGER DEFAULT 0
    );

    -- 3. Natural Disasters (EER Subclass 1)
    CREATE TABLE IF NOT EXISTS natural_disasters (
        disaster_id VARCHAR PRIMARY KEY REFERENCES disaster_events(disaster_id),
        meteorological_category VARCHAR,
        wind_speed_kmh DOUBLE,
        seismic_magnitude DOUBLE,
        flood_depth_m DOUBLE
    );

    -- 4. Technological Disasters (EER Subclass 2)
    CREATE TABLE IF NOT EXISTS technological_disasters (
        disaster_id VARCHAR PRIMARY KEY REFERENCES disaster_events(disaster_id),
        facility_name VARCHAR NOT NULL,
        hazardous_material_type VARCHAR,
        leak_rate VARCHAR,
        containment_status VARCHAR
    );

    -- 5. IoT Sensors Table
    CREATE TABLE IF NOT EXISTS iot_sensors (
        sensor_id VARCHAR PRIMARY KEY,
        sensor_type VARCHAR NOT NULL,
        model_no VARCHAR,
        location_name VARCHAR NOT NULL,
        latitude DOUBLE NOT NULL,
        longitude DOUBLE NOT NULL,
        threshold_limit DOUBLE NOT NULL,
        unit_of_measure VARCHAR NOT NULL,
        status VARCHAR CHECK (status IN ('Active', 'Warning', 'Critical', 'Offline'))
    );

    -- 6. Sensor Telemetry Table (Weak Entity on IoT Sensor)
    CREATE TABLE IF NOT EXISTS sensor_telemetry (
        sensor_id VARCHAR NOT NULL REFERENCES iot_sensors(sensor_id),
        recorded_at TIMESTAMP NOT NULL,
        reading_value DOUBLE NOT NULL,
        battery_level_pct DOUBLE,
        alert_flag BOOLEAN DEFAULT FALSE,
        PRIMARY KEY (sensor_id, recorded_at)
    );

    -- 7. Rescue Teams Table
    CREATE TABLE IF NOT EXISTS rescue_teams (
        team_id VARCHAR PRIMARY KEY,
        agency_id VARCHAR NOT NULL REFERENCES agencies(agency_id),
        team_name VARCHAR NOT NULL,
        team_type VARCHAR NOT NULL,
        member_count INTEGER NOT NULL CHECK (member_count > 0),
        readiness_status VARCHAR CHECK (readiness_status IN ('Standby', 'Deployed', 'Resting', 'Demobilized')),
        base_location VARCHAR
    );

    -- 8. Emergency Vehicles Table
    CREATE TABLE IF NOT EXISTS emergency_vehicles (
        vehicle_id VARCHAR PRIMARY KEY,
        team_id VARCHAR REFERENCES rescue_teams(team_id),
        vehicle_type VARCHAR NOT NULL,
        registration_no VARCHAR UNIQUE NOT NULL,
        capacity_persons INTEGER NOT NULL,
        fuel_status_pct DOUBLE
    );

    -- 9. Relief Camps Table
    CREATE TABLE IF NOT EXISTS relief_camps (
        camp_id VARCHAR PRIMARY KEY,
        camp_name VARCHAR NOT NULL,
        in_charge_name VARCHAR NOT NULL,
        contact_phone VARCHAR,
        latitude DOUBLE NOT NULL,
        longitude DOUBLE NOT NULL,
        max_capacity INTEGER NOT NULL CHECK (max_capacity > 0),
        current_occupancy INTEGER DEFAULT 0 CHECK (current_occupancy >= 0),
        medical_support BOOLEAN DEFAULT FALSE
    );

    -- 10. Rescued Individuals Table
    CREATE TABLE IF NOT EXISTS rescued_individuals (
        individual_id VARCHAR PRIMARY KEY,
        full_name VARCHAR NOT NULL,
        age INTEGER,
        gender VARCHAR(10),
        rescue_timestamp TIMESTAMP NOT NULL,
        disaster_id VARCHAR NOT NULL REFERENCES disaster_events(disaster_id),
        camp_id VARCHAR REFERENCES relief_camps(camp_id),
        triage_priority VARCHAR CHECK (triage_priority IN ('P1 - Critical', 'P2 - Urgent', 'P3 - Minor', 'P4 - Deceased')),
        medical_conditions VARCHAR
    );

    -- 11. Dependent Family Members Table (Weak Entity)
    CREATE TABLE IF NOT EXISTS dependent_family_members (
        individual_id VARCHAR NOT NULL REFERENCES rescued_individuals(individual_id),
        dependent_seq INTEGER NOT NULL,
        dependent_name VARCHAR NOT NULL,
        relationship VARCHAR NOT NULL,
        age INTEGER,
        special_needs VARCHAR,
        PRIMARY KEY (individual_id, dependent_seq)
    );

    -- 12. Relief Items Table (Catalog)
    CREATE TABLE IF NOT EXISTS relief_items (
        item_id VARCHAR PRIMARY KEY,
        item_name VARCHAR NOT NULL,
        category VARCHAR NOT NULL,
        unit_of_measure VARCHAR NOT NULL,
        shelf_life_days INTEGER
    );

    -- 13. Camp Inventory Table (Associative Entity)
    CREATE TABLE IF NOT EXISTS camp_inventory (
        camp_id VARCHAR NOT NULL REFERENCES relief_camps(camp_id),
        item_id VARCHAR NOT NULL REFERENCES relief_items(item_id),
        quantity_available DOUBLE NOT NULL DEFAULT 0,
        reorder_threshold DOUBLE NOT NULL,
        last_replenished_at TIMESTAMP,
        PRIMARY KEY (camp_id, item_id)
    );

    -- 14. Rescue Deployments Table (EER Aggregation)
    CREATE TABLE IF NOT EXISTS rescue_deployments (
        deployment_id VARCHAR PRIMARY KEY,
        disaster_id VARCHAR NOT NULL REFERENCES disaster_events(disaster_id),
        team_id VARCHAR NOT NULL REFERENCES rescue_teams(team_id),
        dispatched_at TIMESTAMP NOT NULL,
        demobilized_at TIMESTAMP,
        operational_sector VARCHAR NOT NULL,
        mission_notes VARCHAR
    );

    -- 15. Relief Distributions Table
    CREATE TABLE IF NOT EXISTS relief_distributions (
        distribution_id VARCHAR PRIMARY KEY,
        disaster_id VARCHAR NOT NULL REFERENCES disaster_events(disaster_id),
        camp_id VARCHAR NOT NULL REFERENCES relief_camps(camp_id),
        item_id VARCHAR NOT NULL REFERENCES relief_items(item_id),
        quantity_dispatched DOUBLE NOT NULL CHECK (quantity_dispatched > 0),
        dispatch_date TIMESTAMP NOT NULL,
        delivery_status VARCHAR CHECK (delivery_status IN ('In Transit', 'Delivered', 'Cancelled'))
    );

    -- 16. Damage Assessments Table
    CREATE TABLE IF NOT EXISTS damage_assessments (
        assessment_id VARCHAR PRIMARY KEY,
        disaster_id VARCHAR NOT NULL REFERENCES disaster_events(disaster_id),
        surveyor_name VARCHAR NOT NULL,
        damage_score INTEGER CHECK (damage_score BETWEEN 1 AND 10),
        estimated_loss_usd DOUBLE NOT NULL,
        houses_destroyed INTEGER DEFAULT 0,
        report_date DATE NOT NULL,
        notes VARCHAR
    );

    -- 17. Communication Logs Table
    CREATE TABLE IF NOT EXISTS communication_logs (
        log_id VARCHAR PRIMARY KEY,
        disaster_id VARCHAR NOT NULL REFERENCES disaster_events(disaster_id),
        sender_agency_id VARCHAR NOT NULL REFERENCES agencies(agency_id),
        recipient_agency_id VARCHAR NOT NULL REFERENCES agencies(agency_id),
        message_text VARCHAR NOT NULL,
        urgency_level VARCHAR CHECK (urgency_level IN ('Routine', 'Priority', 'Flash Emergency')),
        log_time TIMESTAMP NOT NULL
    );
    """)

    # Check if data already seeded
    count = conn.execute("SELECT count(*) FROM disaster_events").fetchone()[0]
    if count == 0:
        seed_data(conn)
    else:
        print(f"[Database] Schema verified. Found {count} existing disasters.")

    conn.close()

def seed_data(conn):
    """Seed comprehensive realistic data for the disaster coordination system."""
    print("[Database] Seeding realistic sample data...")

    now = datetime.now()

    # 1. Agencies
    agencies_data = [
        ('AG-NDMA', 'National Disaster Management Authority (NDMA)', 'Federal Authority', '+91-11-26701700', 'New Delhi, HQ'),
        ('AG-SDRF-OD', 'Odisha Disaster Rapid Action Force (ODRAF)', 'State Response Force', '+91-674-2536711', 'Bhubaneswar, Odisha'),
        ('AG-SDRF-AS', 'Assam State Disaster Management (ASDMA)', 'State Response Force', '+91-361-2237011', 'Guwahati, Assam'),
        ('AG-ICG', 'Indian Coast Guard - Eastern Seaboard Command', 'Maritime Agency', '+91-44-23460405', 'Chennai Base'),
        ('AG-RED-CROSS', 'Indian Red Cross Society Humanitarian Corps', 'NGO / Humanitarian', '+91-11-23716441', 'National Secretariat, Delhi'),
        ('AG-ARMY-ENGR', 'Indian Army Corps of Engineers - Strike Ops', 'Armed Forces', '+91-11-23019876', 'Chandimandir Ops Center'),
        ('AG-AIIMS-MED', 'AIIMS Emergency & Trauma Rapid Mobile Wing', 'Medical Authority', '+91-11-26588500', 'New Delhi')
    ]
    conn.executemany("INSERT INTO agencies VALUES (?, ?, ?, ?, ?)", agencies_data)

    # 2. Disaster Events
    disasters_data = [
        ('DIS-2026-001', 'Cyclone "Vajra" Coastal Inundation', 'Cyclone', 4, 
         (now - timedelta(days=2, hours=4)).strftime('%Y-%m-%d %H:%M:%S'), None, 'Active', 
         19.8135, 85.8312, 120.0, 185000), # Puri / Odisha Coast
        
        ('DIS-2026-002', 'Brahmaputra Flash Basin Floods', 'Flood', 5, 
         (now - timedelta(days=4, hours=10)).strftime('%Y-%m-%d %H:%M:%S'), None, 'Active', 
         26.1856, 91.7477, 95.0, 310000), # Guwahati / Kamrup
        
        ('DIS-2026-003', 'Chamoli Ridge Massive Landslide', 'Landslide', 3, 
         (now - timedelta(days=1, hours=8)).strftime('%Y-%m-%d %H:%M:%S'), None, 'Active', 
         30.3800, 79.3300, 35.0, 14200), # Chamoli, Uttarakhand
        
        ('DIS-2026-004', 'Dahej Petrochem Industrial Ammonia Leak', 'Industrial Accident', 4, 
         (now - timedelta(hours=14)).strftime('%Y-%m-%d %H:%M:%S'), None, 'Active', 
         21.7126, 72.5855, 18.0, 22000), # Dahej SEZ, Gujarat
         
        ('DIS-2026-005', 'Latur Seismic Tremor Cluster (M5.8)', 'Earthquake', 3, 
         (now - timedelta(days=6)).strftime('%Y-%m-%d %H:%M:%S'), 
         (now - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'), 'Contained', 
         18.4088, 76.5604, 45.0, 48000),
         
        ('DIS-2026-006', 'Bandipur Biosphere Forest Blaze', 'Wildfire', 2, 
         (now - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S'), 
         (now - timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S'), 'Resolved', 
         11.6664, 76.6291, 28.0, 3500)
    ]
    conn.executemany("INSERT INTO disaster_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", disasters_data)

    # 3. Natural Disasters Specialization
    nat_disasters = [
        ('DIS-2026-001', 'Severe Cyclonic Storm (Cat 4)', 175.5, 0.0, 3.8),
        ('DIS-2026-002', 'Monsoonal Flash Overflow', 45.0, 0.0, 7.2),
        ('DIS-2026-003', 'Seismic Triggered Debris Flow', 22.0, 4.1, 0.0),
        ('DIS-2026-005', 'Tectonic Fault Slippage', 0.0, 5.8, 0.0),
        ('DIS-2026-006', 'High Thermal Biomass Conflagration', 58.0, 0.0, 0.0)
    ]
    conn.executemany("INSERT INTO natural_disasters VALUES (?, ?, ?, ?, ?)", nat_disasters)

    # 4. Technological Disasters Specialization
    tech_disasters = [
        ('DIS-2026-004', 'Apex Petrochemical Synthesis Complex #4', 'Anhydrous Ammonia (NH3)', '140 kg/min', 'Partial Seal Engaged')
    ]
    conn.executemany("INSERT INTO technological_disasters VALUES (?, ?, ?, ?, ?)", tech_disasters)

    # 5. IoT Sensors
    sensors = [
        ('SNS-OD-FL-01', 'River Water Gauge', 'AQUASCAN-900', 'Puri River Mouth Delta', 19.8240, 85.8450, 4.5, 'Meters', 'Critical'),
        ('SNS-OD-WND-02', 'Anemometer Weather Tower', 'AERO-VANE-X', 'Chandrabhaga Coast Mast', 19.8700, 86.0900, 120.0, 'km/h', 'Critical'),
        ('SNS-AS-FL-03', 'Ultrasonic River Sensor', 'HYDRO-SONAR-IV', 'Saraighat Bridge Pylon', 26.1750, 91.7000, 8.0, 'Meters', 'Critical'),
        ('SNS-AS-RAIN-04', 'Tipping Bucket Rain Gauge', 'PLUVIO-MET-2', 'Guwahati Hills Station', 26.1950, 91.7650, 150.0, 'mm/24h', 'Warning'),
        ('SNS-UK-SEIS-05', 'Broadband Seismometer', 'TERRA-QUAKE-G', 'Joshimath Fault Line Stn', 30.5500, 79.5600, 4.5, 'Richter', 'Active'),
        ('SNS-UK-TILT-06', 'Borehole Inclinometer', 'SLOPE-WATCH-3', 'Chamoli Slope Point 7', 30.3950, 79.3400, 15.0, 'Degrees', 'Warning'),
        ('SNS-GJ-GAS-07', 'Toxic Gas Optical Sensor', 'SPEC-TOX-NH3', 'Dahej Boundary Fence W', 21.7100, 72.5800, 25.0, 'ppm', 'Critical'),
        ('SNS-GJ-GAS-08', 'Ambient Air Dispersion Detector', 'AIR-TRACE-9', 'Dahej Residential Buffer', 21.7250, 72.6000, 15.0, 'ppm', 'Warning'),
        ('SNS-MH-SEIS-09', 'Piezo Seismic Tri-Axial', 'GEO-PULSE-5', 'Latur Seismo Observatory', 18.4100, 76.5650, 4.0, 'Richter', 'Active'),
        ('SNS-KA-OPT-10', 'Infrared Forest Flame Sensor', 'PYRO-CAM-77', 'Bandipur Ridge Top #12', 11.6700, 76.6350, 65.0, 'Celsius', 'Active')
    ]
    conn.executemany("INSERT INTO iot_sensors VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", sensors)

    # 6. Sensor Telemetry Time-Series (Populate 6 hours of high frequency telemetry)
    telemetry_records = []
    base_time = now - timedelta(hours=6)
    
    for s_id, s_type, _, _, _, _, thresh, unit, _ in sensors:
        # Generate 12 readings (every 30 mins)
        curr = thresh * 0.7
        for step in range(12):
            t_stamp = base_time + timedelta(minutes=step * 30)
            # Add random variance or simulate surge towards disaster
            if 'OD' in s_id or 'AS' in s_id or 'GJ' in s_id:
                curr += random.uniform(0.1, 0.4) * (thresh * 0.1)
            else:
                curr += random.uniform(-0.05, 0.05) * thresh
            
            is_alert = (curr >= thresh)
            val = round(curr, 2)
            batt = round(random.uniform(78.0, 99.5), 1)
            telemetry_records.append((s_id, t_stamp.strftime('%Y-%m-%d %H:%M:%S'), val, batt, is_alert))

    conn.executemany("INSERT INTO sensor_telemetry VALUES (?, ?, ?, ?, ?)", telemetry_records)

    # 7. Rescue Teams
    teams = [
        ('TM-NDRF-01', 'AG-NDMA', 'NDRF Alpha Marine Rescue Battalion', 'Flood & Marine', 45, 'Deployed', 'Puri Coastal Sector'),
        ('TM-NDRF-02', 'AG-NDMA', 'NDRF Bravo Urban Search & Rescue', 'Collapsed Structures', 50, 'Deployed', 'Chamoli Valley Sector'),
        ('TM-ODRAF-03', 'AG-SDRF-OD', 'ODRAF Cyclone First Responders', 'High Wind & Evac', 35, 'Deployed', 'Ganjam-Puri Corridor'),
        ('TM-ASDMA-04', 'AG-SDRF-AS', 'ASDMA Riverine Boat Unit', 'Deep Water Evac', 40, 'Deployed', 'Kamrup Riverbank'),
        ('TM-CBRN-05', 'AG-NDMA', 'Special Hazmat & CBRN Counter-Unit', 'Chemical Hazard', 25, 'Deployed', 'Dahej Chemical Corridor'),
        ('TM-ARMY-06', 'AG-ARMY-ENGR', 'Corps of Engineers Bailey Bridge Taskforce', 'Engineering & Access', 60, 'Deployed', 'Joshimath Highway Link'),
        ('TM-MED-07', 'AG-AIIMS-MED', 'AIIMS Mobile Triage & Surgery Unit', 'Trauma Care', 20, 'Deployed', 'Puri Central Relief Hub'),
        ('TM-RED-08', 'AG-RED-CROSS', 'Red Cross Community Care & Relief', 'Shelter & Relief', 30, 'Standby', 'Kolkata Staging Hub')
    ]
    conn.executemany("INSERT INTO rescue_teams VALUES (?, ?, ?, ?, ?, ?, ?)", teams)

    # 8. Emergency Vehicles
    vehicles = [
        ('VEH-AMB-01', 'TM-MED-07', 'Advanced Cardiac Life Support Ambulance', 'OD-02-EM-9901', 4, 92.0),
        ('VEH-BOAT-02', 'TM-NDRF-01', 'High-Speed Zodiac Inflatable Motorboat', 'NDRF-BOAT-44', 12, 85.0),
        ('VEH-BOAT-03', 'TM-ASDMA-04', 'Heavy Amphibious Rescue Craft', 'ASDMA-ARC-09', 24, 78.0),
        ('VEH-CHOP-04', 'TM-NDRF-02', 'ALH Dhruv Rescue & Air-Drop Chopper', 'IAF-RESCUE-07', 14, 65.0),
        ('VEH-HAZ-05', 'TM-CBRN-05', 'Hazmat Decontamination Mobile Vehicle', 'GJ-16-HZ-1122', 6, 88.0),
        ('VEH-TRK-06', 'TM-ARMY-06', 'TATA 6x6 Heavy Obstacle Clearance Truck', 'ARMY-ENGR-331', 8, 95.0),
        ('VEH-AMB-07', 'TM-MED-07', 'Field Rapid Responder 4x4 Ambulance', 'OD-02-EM-9908', 3, 80.0)
    ]
    conn.executemany("INSERT INTO emergency_vehicles VALUES (?, ?, ?, ?, ?, ?)", vehicles)

    # 9. Relief Camps
    camps = [
        ('CMP-OD-01', 'Puri Jagannath Relief Camp & Transit Shelter', 'Sub-Collector R. Mohapatra', '+91-9437012345', 19.8050, 85.8180, 1200, 890, True),
        ('CMP-OD-02', 'Konark Cyclone Resilient Shelter #4', 'Dr. S. Patnaik', '+91-9437022334', 19.8820, 86.0950, 800, 640, True),
        ('CMP-AS-03', 'Guwahati Stadium Mega Relief Encampment', 'District Magistrate K. Baruah', '+91-9864099881', 26.1780, 91.7510, 2500, 1980, True),
        ('CMP-AS-04', 'Jalukbari Higher Secondary Safe Haven', 'Prof. N. Sharma', '+91-9864011223', 26.1420, 91.6630, 600, 410, False),
        ('CMP-UK-05', 'Joshimath Gurudwara Community Shelter', 'Capt. H. Singh', '+91-9758034567', 30.5580, 79.5680, 450, 395, True),
        ('CMP-GJ-06', 'Dahej GIDC Community Hall Evac Point', 'Safety Officer M. Patel', '+91-9825012344', 21.7310, 72.6200, 750, 520, True)
    ]
    conn.executemany("INSERT INTO relief_camps VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", camps)

    # 10. Rescued Individuals
    individuals = [
        ('IND-001', 'Balaram Jena', 48, 'Male', (now - timedelta(hours=36)).strftime('%Y-%m-%d %H:%M:%S'), 'DIS-2026-001', 'CMP-OD-01', 'P2 - Urgent', 'Fractured tibia, mild hypothermia'),
        ('IND-002', 'Sulochana Jena', 44, 'Female', (now - timedelta(hours=36)).strftime('%Y-%m-%d %H:%M:%S'), 'DIS-2026-001', 'CMP-OD-01', 'P3 - Minor', 'Dehydration, minor abrasions'),
        ('IND-003', 'Debabrata Das', 72, 'Male', (now - timedelta(hours=28)).strftime('%Y-%m-%d %H:%M:%S'), 'DIS-2026-001', 'CMP-OD-01', 'P1 - Critical', 'Severe respiratory distress, cardiac history'),
        ('IND-004', 'Priyanka Das', 19, 'Female', (now - timedelta(hours=28)).strftime('%Y-%m-%d %H:%M:%S'), 'DIS-2026-001', 'CMP-OD-01', 'P3 - Minor', 'None'),
        ('IND-005', 'Ranjit Hazarika', 34, 'Male', (now - timedelta(hours=48)).strftime('%Y-%m-%d %H:%M:%S'), 'DIS-2026-002', 'CMP-AS-03', 'P2 - Urgent', 'Deep laceration on left arm, water swallowed'),
        ('IND-006', 'Anuradha Hazarika', 31, 'Female', (now - timedelta(hours=48)).strftime('%Y-%m-%d %H:%M:%S'), 'DIS-2026-002', 'CMP-AS-03', 'P3 - Minor', 'Fatigue, pregnant 6 months'),
        ('IND-007', 'Kundan Rawat', 55, 'Male', (now - timedelta(hours=18)).strftime('%Y-%m-%d %H:%M:%S'), 'DIS-2026-003', 'CMP-UK-05', 'P1 - Critical', 'Crush injury under masonry debris'),
        ('IND-008', 'Kamla Rawat', 51, 'Female', (now - timedelta(hours=18)).strftime('%Y-%m-%d %H:%M:%S'), 'DIS-2026-003', 'CMP-UK-05', 'P2 - Urgent', 'Dislocated shoulder, shock'),
        ('IND-009', 'Nilesh Solanki', 29, 'Male', (now - timedelta(hours=10)).strftime('%Y-%m-%d %H:%M:%S'), 'DIS-2026-004', 'CMP-GJ-06', 'P1 - Critical', 'Ammonia inhalation burns, chemical ocular irritation'),
        ('IND-010', 'Paresh Gohil', 42, 'Male', (now - timedelta(hours=9)).strftime('%Y-%m-%d %H:%M:%S'), 'DIS-2026-004', 'CMP-GJ-06', 'P2 - Urgent', 'Severe bronchospasm')
    ]
    conn.executemany("INSERT INTO rescued_individuals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", individuals)

    # 11. Dependent Family Members
    dependents = [
        ('IND-001', 1, 'Subrat Jena', 'Son', 14, 'Asthma medication needed'),
        ('IND-001', 2, 'Manasi Jena', 'Daughter', 10, 'None'),
        ('IND-005', 1, 'Dipankar Hazarika', 'Son', 5, 'Pediatric checkup needed'),
        ('IND-007', 1, 'Pooja Rawat', 'Daughter', 16, 'None')
    ]
    conn.executemany("INSERT INTO dependent_family_members VALUES (?, ?, ?, ?, ?, ?)", dependents)

    # 12. Relief Items
    items = [
        ('ITM-001', 'Potable Drinking Water (20L Canister)', 'Water', 'Canister', 180),
        ('ITM-002', 'High-Calorie Ready-to-Eat Emergency Meals', 'Food', 'Packets (10-in-1)', 365),
        ('ITM-003', 'Comprehensive Trauma First Aid Kit', 'Medicine', 'Medical Kit Box', 730),
        ('ITM-004', 'Heavy Thermal Insulation Blankets', 'Shelter', 'Unit', 1800),
        ('ITM-005', 'Water Purification Chlorine Tablets (100x)', 'Sanitation', 'Bottle', 1000),
        ('ITM-006', 'Chemical Neutralizing Respirator Masks', 'Safety', 'Box of 50', 1000)
    ]
    conn.executemany("INSERT INTO relief_items VALUES (?, ?, ?, ?, ?)", items)

    # 13. Camp Inventory
    camp_inv = [
        ('CMP-OD-01', 'ITM-001', 450.0, 150.0, (now - timedelta(hours=12)).strftime('%Y-%m-%d %H:%M:%S')),
        ('CMP-OD-01', 'ITM-002', 1200.0, 300.0, (now - timedelta(hours=12)).strftime('%Y-%m-%d %H:%M:%S')),
        ('CMP-OD-01', 'ITM-003', 180.0, 50.0, (now - timedelta(hours=12)).strftime('%Y-%m-%d %H:%M:%S')),
        ('CMP-OD-01', 'ITM-004', 800.0, 200.0, (now - timedelta(hours=12)).strftime('%Y-%m-%d %H:%M:%S')),
        ('CMP-AS-03', 'ITM-001', 820.0, 400.0, (now - timedelta(hours=16)).strftime('%Y-%m-%d %H:%M:%S')),
        ('CMP-AS-03', 'ITM-002', 2400.0, 600.0, (now - timedelta(hours=16)).strftime('%Y-%m-%d %H:%M:%S')),
        ('CMP-AS-03', 'ITM-005', 650.0, 100.0, (now - timedelta(hours=16)).strftime('%Y-%m-%d %H:%M:%S')),
        ('CMP-UK-05', 'ITM-003', 95.0, 30.0, (now - timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')),
        ('CMP-UK-05', 'ITM-004', 350.0, 100.0, (now - timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')),
        ('CMP-GJ-06', 'ITM-006', 420.0, 100.0, (now - timedelta(hours=6)).strftime('%Y-%m-%d %H:%M:%S'))
    ]
    conn.executemany("INSERT INTO camp_inventory VALUES (?, ?, ?, ?, ?)", camp_inv)

    # 14. Rescue Deployments (EER Aggregation)
    deployments = [
        ('DEP-001', 'DIS-2026-001', 'TM-NDRF-01', (now - timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S'), None, 'Puri Coastal Strand', 'Active marine rescue and tree obstacle clearing'),
        ('DEP-002', 'DIS-2026-001', 'TM-ODRAF-03', (now - timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S'), None, 'Konark Floodplain', 'Evacuation of low-lying fishing hamlets'),
        ('DEP-003', 'DIS-2026-002', 'TM-ASDMA-04', (now - timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S'), None, 'Brahmaputra South Bank', 'Continuous boat rescue and food packet airdrop coordination'),
        ('DEP-004', 'DIS-2026-003', 'TM-NDRF-02', (now - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'), None, 'Chamoli Debris Zone', 'Sniffer dog search & acoustic sound detection'),
        ('DEP-005', 'DIS-2026-004', 'TM-CBRN-05', (now - timedelta(hours=12)).strftime('%Y-%m-%d %H:%M:%S'), None, 'Dahej Industrial Sector 3', 'Atmospheric vapor curtain deployment and plume suppression')
    ]
    conn.executemany("INSERT INTO rescue_deployments VALUES (?, ?, ?, ?, ?, ?, ?)", deployments)

    # 15. Relief Distributions
    distributions = [
        ('DIST-001', 'DIS-2026-001', 'CMP-OD-01', 'ITM-001', 500.0, (now - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'), 'Delivered'),
        ('DIST-002', 'DIS-2026-001', 'CMP-OD-01', 'ITM-002', 1500.0, (now - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'), 'Delivered'),
        ('DIST-003', 'DIS-2026-002', 'CMP-AS-03', 'ITM-001', 1000.0, (now - timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S'), 'Delivered'),
        ('DIST-004', 'DIS-2026-002', 'CMP-AS-03', 'ITM-005', 800.0, (now - timedelta(hours=14)).strftime('%Y-%m-%d %H:%M:%S'), 'In Transit'),
        ('DIST-005', 'DIS-2026-004', 'CMP-GJ-06', 'ITM-006', 500.0, (now - timedelta(hours=5)).strftime('%Y-%m-%d %H:%M:%S'), 'Delivered')
    ]
    conn.executemany("INSERT INTO relief_distributions VALUES (?, ?, ?, ?, ?, ?, ?)", distributions)

    # 16. Damage Assessments
    assessments = [
        ('ASM-001', 'DIS-2026-001', 'Surveyor General P. K. Patnaik', 8, 42000000.0, 1850, (now - timedelta(days=1)).strftime('%Y-%m-%d'), 'Extensive thatched roof collapse, power transmission towers uprooted across 40km stretch'),
        ('ASM-002', 'DIS-2026-002', 'Senior Engineer B. C. Talukdar', 9, 68000000.0, 4200, (now - timedelta(days=2)).strftime('%Y-%m-%d'), 'National Highway 37 submerged at multiple culverts; massive paddy crop loss'),
        ('ASM-003', 'DIS-2026-003', 'Geological Survey of India Team 2', 7, 12500000.0, 120, (now - timedelta(hours=12)).strftime('%Y-%m-%d'), 'Bridge swept away; 3km mountain road blocked by 40,000 cubic meters of granite boulders')
    ]
    conn.executemany("INSERT INTO damage_assessments VALUES (?, ?, ?, ?, ?, ?, ?, ?)", assessments)

    # 17. Communication Logs
    comm_logs = [
        ('LOG-001', 'DIS-2026-001', 'AG-NDMA', 'AG-SDRF-OD', 'Deploy additional 4 teams with chainsaw clearances for Puri arterial access', 'Priority', (now - timedelta(hours=22)).strftime('%Y-%m-%d %H:%M:%S')),
        ('LOG-002', 'DIS-2026-004', 'AG-NDMA', 'AG-AIIMS-MED', 'Urgent dispatch: 500 units of bronchodilators and ocular rinse to Dahej hub', 'Flash Emergency', (now - timedelta(hours=11)).strftime('%Y-%m-%d %H:%M:%S')),
        ('LOG-003', 'DIS-2026-002', 'AG-SDRF-AS', 'AG-ARMY-ENGR', 'Requesting amphibious recovery carrier at Jalukbari ferry ghat', 'Priority', (now - timedelta(hours=16)).strftime('%Y-%m-%d %H:%M:%S'))
    ]
    conn.executemany("INSERT INTO communication_logs VALUES (?, ?, ?, ?, ?, ?, ?)", comm_logs)

    print("[Database] Successfully seeded all tables.")

def fetch_as_dicts(conn, query, params=None):
    """
    Executes a query and returns results as a list of dicts,
    safely handling NULLs, NaNs, and Datetimes for JSON compliance.
    """
    cursor = conn.execute(query, params or [])
    if not cursor.description:
        return []
    cols = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    results = []
    for row in rows:
        d = {}
        for col, val in zip(cols, row):
            if val is None:
                d[col] = None
            elif isinstance(val, float) and (val != val):  # NaN check
                d[col] = None
            elif hasattr(val, 'strftime'):
                d[col] = val.strftime('%Y-%m-%d %H:%M:%S')
            elif hasattr(val, 'isoformat'):
                d[col] = val.isoformat()
            else:
                d[col] = val
        results.append(d)
    return results

if __name__ == "__main__":
    init_db(force_reinit=True)

