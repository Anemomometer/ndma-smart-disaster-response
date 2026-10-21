# Smart Disaster Response Coordination System (NDMA)
### DBMS DA Mini-Project — Problem Statement #7 Implementation
**Advanced Database Engine**: **DuckDB** (Vectorized Columnar In-Process OLAP Database)  
**Frontend**: Tactical Crisis Command Center (HTML5, Vanilla CSS Glassmorphism, Leaflet GIS, Chart.js)  
**Backend**: FastAPI, Uvicorn, Python 3.13, DuckDB 2.0  

---

## 🌟 Executive Summary

This system implements **Problem Statement #7: Design and Development of an Entity Relationship (ER) and Enhanced Entity Relationship (EER) Model for a Smart Disaster Response Coordination System** for the National Disaster Management Authority (NDMA).

The application pairs a mathematically rigorous **3NF/BCNF relational database design** with an **advanced database technology (DuckDB)** to power an interactive, real-time Crisis Command Center.

---

## 📋 Problem Statement Requirements & Solutions Matrix

| Problem Requirement | Academic & Technical Solution | Where to Find in Project |
| :--- | :--- | :--- |
| **1. Entity & Attribute Identification** | 17 normalized entities identified with Primary, Candidate, and Foreign Keys; weak entities, derived & multivalued attributes. | [ACADEMIC_REPORT.md](file:///d:/DBMS%20DA/ACADEMIC_REPORT.md#L45-L95), [database.py](file:///d:/DBMS%20DA/backend/database.py#L22-L180), UI "ER/EER" Tab |
| **2. ER Diagram** | Full Cardinality & Participation Constraints (Disasters, Teams, Camps, Evacuees, IoT Sensors, Supplies). | [ACADEMIC_REPORT.md](file:///d:/DBMS%20DA/ACADEMIC_REPORT.md#L145-L215) (Mermaid Diagram) |
| **3. Enhanced ER (EER) Modeling** | - **Specialization/Generalization**: `Disaster_Event` specialized into disjoint `Natural_Disaster` & `Technological_Disaster`.<br>- **Weak Entities**: `Sensor_Telemetry` (owned by `IoT_Sensor`) & `Dependent_Family_Member` (owned by `Rescued_Individual`).<br>- **Aggregation**: `[Rescue_Team + Disaster_Event = Rescue_Deployment]` aggregated to receive resource allocations.<br>- **Categories (Union Types)**: `Relief_Recipient = Relief_Camp ∪ Affected_Community`. | [ACADEMIC_REPORT.md](file:///d:/DBMS%20DA/ACADEMIC_REPORT.md#L98-L142), UI "ER / EER & 3NF Report" Tab |
| **4. Relational Schema Mapping** | Explicit SQL schemas with Primary, Foreign, Unique, and Check constraints. | [database.py](file:///d:/DBMS%20DA/backend/database.py#L25-L185) |
| **5. 3NF / BCNF Normalization** | Step-by-step mathematical decomposition from UNF -> 1NF -> 2NF -> 3NF -> BCNF with Functional Dependencies (FDs) and anomaly analysis. | [ACADEMIC_REPORT.md](file:///d:/DBMS%20DA/ACADEMIC_REPORT.md#L295-L380), UI "Normalization" section |
| **6. Advanced Database Integration** | **DuckDB** selected for vectorized columnar OLAP analytics, zero-daemon offline resilience, and pure SQL Haversine GIS distance calculation. | [queries.py](file:///d:/DBMS%20DA/backend/queries.py), [database.py](file:///d:/DBMS%20DA/backend/database.py) |
| **7. Relevant Frontend Application** | Tactical Dark Theme Command Center with Leaflet GIS mapping, dynamic sensor telemetry graphs, live alert simulations, and interactive DuckDB SQL playground. | [index.html](file:///d:/DBMS%20DA/frontend/index.html), [styles.css](file:///d:/DBMS%20DA/frontend/styles.css), [app.js](file:///d:/DBMS%20DA/frontend/app.js) |

---

## ⚡ Why DuckDB as the Advanced Database?

The project prompt specifies:
> *"Implement the scenario/problem statement allocated to your team using any appropriate advanced database technology, such as Apache Cassandra, Milvus, InfluxDB, CockroachDB, Couchbase, Neo4j, DuckDB, Qdrant, Elasticsearch, or any other suitable advanced database."*

### Key Justifications for DuckDB:
1. **Vectorized Columnar Execution Engine**:
   Disaster management is an analytical (OLAP) workload requiring instant aggregations across millions of sensor readings, victim triage counts, and camp occupancy percentages. DuckDB processes data via SIMD vectors, executing complex queries in **1 to 15 milliseconds**.
2. **Zero-Daemon, Serverless & Network Partition Resilient**:
   In natural disasters (earthquakes, cyclones), wide-area network backbones and remote cloud connections frequently fail. DuckDB runs **embedded in-process** on field command vehicles and tactical laptops without needing an external database server or Docker daemon.
3. **Pure SQL Geospatial Haversine Math**:
   Computes spherical distance matrices between disaster coordinates and relief camps directly in standard SQL without requiring external GIS servers:
   $$\text{Distance} = 2 \times R \times \arcsin\left(\sqrt{\sin^2\left(\frac{\Delta \text{lat}}{2}\right) + \cos(\text{lat}_1) \cos(\text{lat}_2) \sin^2\left(\frac{\Delta \text{lon}}{2}\right)}\right)$$
4. **ACID Relational Compliance**:
   Ensures strict transactional integrity for evacuee bed allocation, inventory stock deductions, and team mobilization logs.

---

## 📁 Repository Structure

```
d:\DBMS DA\
├── backend\
│   ├── app.py                  # FastAPI REST API controller
│   ├── database.py             # DuckDB schema creation, 3NF tables & seed data
│   ├── queries.py              # Advanced OLAP queries, window functions & SQL console
│   └── disaster_response.duckdb# Persistent DuckDB columnar database file
├── frontend\
│   ├── index.html              # Tactical Crisis Command Center markup
│   ├── styles.css              # Cyber-tactical dark theme, glassmorphism, responsive grid
│   ├── app.js                  # Leaflet GIS map, Chart.js telemetry, interactive modals & API sync
│   └── ACADEMIC_REPORT.md      # Direct downloadable academic documentation
├── ACADEMIC_REPORT.md          # Comprehensive DBMS Theory, EER, and Normalization report
├── run_server.py               # Python launcher for FastAPI + DuckDB
├── run.bat                     # Windows 1-click startup batch script
└── README.md                   # This project guide
```

---

## 🚀 Quickstart Guide

### 1. Prerequisites
- Python 3.10+ (Tested on Python 3.13)
- `pip install duckdb fastapi uvicorn pydantic` *(Already installed)*

### 2. Launch the Application
Double-click `run.bat` or run in terminal:
```bash
python run_server.py
```

### 3. Open the Command Center
Open your web browser and navigate to:
**`http://127.0.0.1:8000`**

---

## 🖥️ Feature Walkthrough

### 1. GIS Interactive Command Map
- View disaster epicenters with color-coded severity levels and impact radius circles.
- Relief camps displayed with live capacity indicators:
  - 🟢 Green: Safe (< 75% occupancy)
  - 🟡 Amber: High Load (75%–90%)
  - 🔴 Red: Near Capacity (> 90%)
- Real-time IoT sensor stations with interactive popups showing telemetry readings.

### 2. Disasters & Specialization Operations
- Filter incidents by status (`Active`, `Contained`, `Resolved`) or severity (Cat 1–5).
- Modal to declare new incidents supporting both **Natural** (wind speed, flood depth, seismic magnitude) and **Technological** (facility name, hazardous material) EER subclasses.

### 3. Rescue Operations & Evacuee Allocation
- Track deployed battalions and emergency vehicles (Ambulances, Hovercrafts, Helicopters).
- Register rescued evacuees with **live camp capacity validation** and **automatic nearest camp recommendation** using DuckDB Haversine distance.

### 4. Relief Logistics & Inventory Burn-Rate
- Monitor medical supplies, potable water, food rations, and blankets.
- Automatic calculation of **estimated days of stock remaining** based on camp occupancy.
- Dispatch relief shipments directly to camps with automatic stock ledger updates.

### 5. IoT Sensor Telemetry Stream & Simulation
- Continuous time-series charting of sensor metrics.
- Click **"Simulate IoT Surge"** to inject dynamic batch telemetry and observe automatic alert triggers in real time.

### 6. Interactive DuckDB SQL Console
- Includes pre-built analytical queries:
  1. *Haversine Spatial Nearest Camp Matrix*
  2. *Camp Occupancy Pressure & Evacuee Rollup*
  3. *IoT Sensor Moving Average & Outliers (DuckDB Window Functions)*
  4. *Supply Burn Rate & Days-to-Exhaustion*
  5. *Casualty Demographic & Triage Rollup*
  6. *Damage Loss vs Casualties by Disaster Event*
- Write and execute arbitrary read-only SQL queries with **sub-millisecond execution timing badges** (`⚡ 1.5 ms`).

### 7. In-App Academic DBMS Report Tab
- View the entire academic project submission directly within the UI, including:
  - Entity-Attribute-Key matrix
  - EER concept justifications
  - UNF -> 1NF -> 2NF -> 3NF -> BCNF decomposition proofs
  - Relational schema definitions
