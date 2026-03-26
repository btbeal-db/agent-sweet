#!/usr/bin/env python3
"""Provision demo resources for the Agent Builder app.

Creates tables, a Vector Search index, and a Genie space in the target
workspace so the app has something to demo against.  Safe to re-run —
each step is idempotent.

Usage:
    python demo/setup_demo.py --profile BUILDER
    python demo/setup_demo.py --profile BUILDER --catalog my_catalog --schema my_schema
    python demo/setup_demo.py --profile BUILDER --teardown
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

import requests
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import ResourceAlreadyExists, NotFound
from databricks.sdk.service.vectorsearch import (
    DeltaSyncVectorIndexSpecRequest,
    EmbeddingSourceColumn,
    EndpointType,
    PipelineType,
    VectorIndexType,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────

VS_ENDPOINT_NAME = "agent-builder-vs"
EMBEDDING_ENDPOINT = "databricks-gte-large-en"


# ── SQL data ──────────────────────────────────────────────────────────────────

PATIENT_NOTES_DDL = """
CREATE OR REPLACE TABLE {table} (
  note_id INT,
  patient_id STRING,
  department STRING,
  note_type STRING,
  physician STRING,
  note_date DATE,
  text STRING
)
"""

PATIENT_NOTES_INSERT = """
INSERT INTO {table} VALUES
(1, 'P001', 'Cardiology', 'Progress Note', 'Dr. Chen', '2026-01-15',
 'Patient presents with chest pain radiating to left arm. ECG shows ST elevation in leads II, III, aVF. Troponin elevated at 0.8 ng/mL. Started on aspirin, heparin drip, and nitroglycerin. Cardiology consulted for emergent catheterization.'),
(2, 'P001', 'Cardiology', 'Procedure Note', 'Dr. Chen', '2026-01-16',
 'Cardiac catheterization performed. Found 95% occlusion of LAD. Successfully placed drug-eluting stent. Patient tolerated procedure well. Started on dual antiplatelet therapy with aspirin and clopidogrel.'),
(3, 'P002', 'Neurology', 'Consultation', 'Dr. Patel', '2026-01-20',
 'Patient referred for evaluation of recurrent headaches with visual aura. MRI brain shows no acute abnormality. EEG within normal limits. Diagnosed with migraine with aura. Started on topiramate 25mg daily with plan to titrate up. Follow up in 4 weeks.'),
(4, 'P003', 'Orthopedics', 'Surgical Note', 'Dr. Williams', '2026-02-01',
 'Right total knee arthroplasty performed under spinal anesthesia. Severe tricompartmental osteoarthritis confirmed intraoperatively. Implanted size 5 femoral component and size 4 tibial baseplate. Estimated blood loss 150mL. Patient to weight bear as tolerated with walker.'),
(5, 'P004', 'Oncology', 'Progress Note', 'Dr. Kim', '2026-02-10',
 'Follow-up after cycle 3 of FOLFOX chemotherapy for stage III colon cancer. CT scan shows 40% reduction in liver metastasis. CEA decreased from 45 to 12. Patient tolerating treatment with grade 1 neuropathy. Plan to continue for 3 more cycles then restage.'),
(6, 'P005', 'Cardiology', 'Discharge Summary', 'Dr. Chen', '2026-02-15',
 'Patient admitted for acute decompensated heart failure with EF 25%. Treated with IV diuresis, lost 8kg fluid. Transitioned to oral furosemide 40mg BID, carvedilol 12.5mg BID, lisinopril 10mg daily. Discharged home with visiting nurse. Follow up in 1 week.'),
(7, 'P006', 'Pulmonology', 'Consultation', 'Dr. Garcia', '2026-02-20',
 'Referred for persistent cough x 3 months. Chest CT shows 2.5cm ground glass opacity in right upper lobe. PFTs show mild restrictive pattern. Recommend PET scan and possible CT-guided biopsy. Differential includes primary lung malignancy vs organizing pneumonia.'),
(8, 'P007', 'Endocrinology', 'Progress Note', 'Dr. Singh', '2026-03-01',
 'Type 2 diabetes management review. A1c improved from 9.2 to 7.4 on metformin 1000mg BID and semaglutide 1mg weekly. BMI decreased from 34 to 31. Lipid panel improved. Continue current regimen. Added CGM for better glucose monitoring. Goal A1c below 7.'),
(9, 'P002', 'Neurology', 'Follow-up', 'Dr. Patel', '2026-03-05',
 'Migraine follow-up. Patient reports 60% reduction in headache frequency on topiramate 50mg. No significant side effects. Visual aura episodes decreased from weekly to monthly. Continue current dose. Consider adding CGRP inhibitor if not fully controlled.'),
(10, 'P008', 'Cardiology', 'Progress Note', 'Dr. Chen', '2026-03-10',
 'Post-TAVR follow-up at 6 months. Echocardiogram shows well-seated prosthetic aortic valve with mean gradient 8mmHg, no paravalvular leak. EF improved from 35% to 50%. Patient reports improved exercise tolerance. Continue aspirin and anticoagulation for 3 more months.'),
(11, 'P009', 'Gastroenterology', 'Procedure Note', 'Dr. Lee', '2026-03-12',
 'Colonoscopy performed for screening. Found 15mm sessile polyp in ascending colon, removed by EMR. Two 5mm polyps in sigmoid, removed by cold snare. No complications. Pathology pending. Recommend follow-up colonoscopy in 3 years based on findings.'),
(12, 'P010', 'Rheumatology', 'Consultation', 'Dr. Martinez', '2026-03-15',
 'New patient evaluation for joint pain and morning stiffness. Symmetric polyarthritis involving MCPs, PIPs, wrists. RF positive at 120, anti-CCP 250. X-rays show early erosive changes. Diagnosed with seropositive rheumatoid arthritis. Starting methotrexate 15mg weekly with folic acid.')
"""

PATIENT_METRICS_DDL = """
CREATE OR REPLACE TABLE {table} (
  patient_id STRING,
  patient_name STRING,
  age INT,
  department STRING,
  admission_date DATE,
  discharge_date DATE,
  diagnosis STRING,
  total_cost DECIMAL(10,2),
  length_of_stay INT,
  readmission_30day BOOLEAN,
  satisfaction_score DECIMAL(3,1)
)
"""

PATIENT_METRICS_INSERT = """
INSERT INTO {table} VALUES
('P001', 'John Smith', 62, 'Cardiology', '2026-01-14', '2026-01-18', 'Acute MI', 45200.00, 4, false, 4.5),
('P002', 'Maria Garcia', 34, 'Neurology', '2026-01-20', '2026-01-20', 'Migraine with Aura', 1800.00, 0, false, 4.8),
('P003', 'Robert Johnson', 71, 'Orthopedics', '2026-02-01', '2026-02-04', 'Knee Osteoarthritis', 38500.00, 3, false, 4.2),
('P004', 'Sarah Lee', 55, 'Oncology', '2026-02-10', '2026-02-12', 'Stage III Colon Cancer', 28900.00, 2, false, 4.0),
('P005', 'James Wilson', 78, 'Cardiology', '2026-02-13', '2026-02-19', 'Heart Failure', 32100.00, 6, true, 3.8),
('P006', 'Emily Davis', 48, 'Pulmonology', '2026-02-20', '2026-02-21', 'Lung Opacity', 5600.00, 1, false, 4.6),
('P007', 'Michael Brown', 52, 'Endocrinology', '2026-03-01', '2026-03-01', 'Type 2 Diabetes', 900.00, 0, false, 4.9),
('P008', 'Patricia Taylor', 82, 'Cardiology', '2026-03-08', '2026-03-12', 'Post-TAVR Follow-up', 15300.00, 4, false, 4.7),
('P009', 'David Anderson', 58, 'Gastroenterology', '2026-03-12', '2026-03-12', 'Colon Polyps', 3200.00, 0, false, 4.4),
('P010', 'Jennifer Martinez', 41, 'Rheumatology', '2026-03-15', '2026-03-15', 'Rheumatoid Arthritis', 2100.00, 0, false, 4.3),
('P011', 'Thomas White', 67, 'Cardiology', '2026-03-01', '2026-03-05', 'Atrial Fibrillation', 22800.00, 4, false, 4.1),
('P012', 'Lisa Harris', 45, 'Neurology', '2026-03-03', '2026-03-04', 'Epilepsy', 8900.00, 1, false, 4.6),
('P013', 'Christopher Clark', 73, 'Orthopedics', '2026-03-05', '2026-03-09', 'Hip Fracture', 41200.00, 4, true, 3.5),
('P014', 'Nancy Lewis', 59, 'Oncology', '2026-03-07', '2026-03-10', 'Breast Cancer', 19700.00, 3, false, 4.2),
('P015', 'Daniel Walker', 38, 'Pulmonology', '2026-03-10', '2026-03-11', 'Asthma Exacerbation', 4500.00, 1, false, 4.8)
"""

PATIENT_METRICS_COMMENTS = [
    ("patient_id", "Unique patient identifier"),
    ("patient_name", "Patient full name"),
    ("age", "Patient age in years"),
    ("department", "Hospital department (Cardiology, Neurology, Orthopedics, etc.)"),
    ("admission_date", "Date of hospital admission"),
    ("discharge_date", "Date of hospital discharge"),
    ("diagnosis", "Primary diagnosis"),
    ("total_cost", "Total cost of care in USD"),
    ("length_of_stay", "Number of days in hospital (0 = outpatient)"),
    ("readmission_30day", "Whether patient was readmitted within 30 days"),
    ("satisfaction_score", "Patient satisfaction score (1-5 scale)"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────


def run_sql(w: WorkspaceClient, wh_id: str, sql: str) -> object:
    result = w.statement_execution.execute_statement(
        warehouse_id=wh_id, statement=sql, wait_timeout="50s",
    )
    if str(result.status.state) not in ("SUCCEEDED", "StatementState.SUCCEEDED"):
        raise RuntimeError(f"SQL failed: {result.status}")
    return result


def get_warehouse(w: WorkspaceClient) -> str:
    warehouses = list(w.warehouses.list())
    if not warehouses:
        raise RuntimeError("No SQL warehouses found. Create one first.")
    wh = warehouses[0]
    log.info("  Using warehouse: %s (%s)", wh.name, wh.id)
    return wh.id


# ── Setup steps ───────────────────────────────────────────────────────────────


def setup_schema(w: WorkspaceClient, catalog: str, schema: str):
    log.info("\n1. Ensuring schema %s.%s exists...", catalog, schema)
    try:
        w.schemas.get(f"{catalog}.{schema}")
        log.info("  Schema already exists")
    except Exception:
        try:
            w.schemas.create(name=schema, catalog_name=catalog)
            log.info("  Created schema")
        except Exception as e:
            if "already exists" in str(e).lower():
                log.info("  Schema already exists")
            else:
                raise


def setup_patient_notes(w: WorkspaceClient, wh_id: str, table: str):
    log.info("\n2. Creating patient_notes table...")
    run_sql(w, wh_id, PATIENT_NOTES_DDL.format(table=table))
    run_sql(w, wh_id, PATIENT_NOTES_INSERT.format(table=table))
    result = run_sql(w, wh_id, f"SELECT count(*) FROM {table}")
    count = result.result.data_array[0][0]
    log.info("  Created %s (%s rows)", table, count)


def setup_patient_metrics(w: WorkspaceClient, wh_id: str, table: str):
    log.info("\n3. Creating patient_metrics table...")
    run_sql(w, wh_id, PATIENT_METRICS_DDL.format(table=table))
    run_sql(w, wh_id, PATIENT_METRICS_INSERT.format(table=table))
    run_sql(w, wh_id, f"""COMMENT ON TABLE {table} IS
        'Hospital patient metrics including demographics, diagnoses, costs, length of stay,
        readmission rates, and satisfaction scores.'""")
    for col, comment in PATIENT_METRICS_COMMENTS:
        run_sql(w, wh_id, f"COMMENT ON COLUMN {table}.{col} IS '{comment}'")
    result = run_sql(w, wh_id, f"SELECT count(*) FROM {table}")
    count = result.result.data_array[0][0]
    log.info("  Created %s (%s rows, with column comments)", table, count)


def setup_vs_endpoint(w: WorkspaceClient):
    log.info("\n4. Creating Vector Search endpoint '%s'...", VS_ENDPOINT_NAME)

    # Check if endpoint already exists
    try:
        ep = w.vector_search_endpoints.get_endpoint(VS_ENDPOINT_NAME)
        log.info("  Endpoint already exists")
    except (NotFound, Exception):
        try:
            w.vector_search_endpoints.create_endpoint(
                name=VS_ENDPOINT_NAME,
                endpoint_type=EndpointType.STANDARD,
            )
            log.info("  Endpoint creation initiated")
        except Exception as e:
            if "already exists" in str(e).lower():
                log.info("  Endpoint already exists")
            else:
                raise

    log.info("  Waiting for ONLINE status...")
    for _ in range(90):
        ep = w.vector_search_endpoints.get_endpoint(VS_ENDPOINT_NAME)
        state = str(ep.endpoint_status.state) if ep.endpoint_status else "UNKNOWN"
        if "ONLINE" in state:
            log.info("  Endpoint is ONLINE")
            return
        time.sleep(10)
    log.warning("  Endpoint not ONLINE after 15 min — proceeding anyway")


def setup_vs_index(w: WorkspaceClient, wh_id: str, source_table: str, index_name: str):
    log.info("\n5. Creating Vector Search index '%s'...", index_name)

    # Check if index already exists
    try:
        w.vector_search_indexes.get_index(index_name)
        log.info("  Index already exists — skipping creation")
        return
    except (NotFound, Exception) as e:
        if "does not exist" not in str(e).lower() and "not found" not in str(e).lower():
            # Unexpected error — re-raise
            if not isinstance(e, NotFound):
                raise

    # Enable CDC
    run_sql(w, wh_id, f"ALTER TABLE {source_table} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
    log.info("  CDC enabled on %s", source_table)

    try:
        w.vector_search_indexes.create_index(
            name=index_name,
            endpoint_name=VS_ENDPOINT_NAME,
            primary_key="note_id",
            index_type=VectorIndexType.DELTA_SYNC,
            delta_sync_index_spec=DeltaSyncVectorIndexSpecRequest(
                source_table=source_table,
                pipeline_type=PipelineType.TRIGGERED,
                embedding_source_columns=[
                    EmbeddingSourceColumn(
                        name="text",
                        embedding_model_endpoint_name=EMBEDDING_ENDPOINT,
                    ),
                ],
            ),
        )
        log.info("  Index creation initiated (will sync in background)")
    except Exception as e:
        if "already exists" in str(e).lower():
            log.info("  Index already exists")
        else:
            raise


def setup_genie_space(w: WorkspaceClient, wh_id: str, metrics_table: str) -> str | None:
    log.info("\n6. Creating Genie space...")
    host = w.config.host.rstrip("/")
    token = w.config.token

    resp = requests.post(
        f"{host}/api/2.0/genie/spaces",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "title": "Hospital Patient Analytics",
            "description": "Ask questions about hospital patient metrics, costs, length of stay, readmissions, and satisfaction scores.",
            "warehouse_id": wh_id,
            "serialized_space": json.dumps({"version": 1}),
        },
    )
    if resp.status_code == 200:
        data = resp.json()
        space_id = data.get("space_id", "")
        log.info("  Genie space created: %s", space_id)
        log.info("  NOTE: Add the table '%s' via the UI:", metrics_table)
        log.info("    %s/genie/rooms/%s", host, space_id)
        return space_id
    else:
        log.warning("  Failed to create Genie space: %s %s", resp.status_code, resp.text[:200])
        return None


# ── Teardown ──────────────────────────────────────────────────────────────────


def teardown(w: WorkspaceClient, wh_id: str, catalog: str, schema: str):
    notes_table = f"{catalog}.{schema}.patient_notes"
    metrics_table = f"{catalog}.{schema}.patient_metrics"
    index_name = f"{catalog}.{schema}.patient_notes_index"

    log.info("Tearing down demo resources...")

    # Delete VS index
    try:
        w.vector_search_indexes.delete_index(index_name)
        log.info("  Deleted index: %s", index_name)
    except NotFound:
        log.info("  Index not found: %s", index_name)

    # Delete VS endpoint
    try:
        w.vector_search_endpoints.delete_endpoint(VS_ENDPOINT_NAME)
        log.info("  Deleted endpoint: %s", VS_ENDPOINT_NAME)
    except NotFound:
        log.info("  Endpoint not found: %s", VS_ENDPOINT_NAME)

    # Drop tables
    for table in [notes_table, metrics_table]:
        try:
            run_sql(w, wh_id, f"DROP TABLE IF EXISTS {table}")
            log.info("  Dropped table: %s", table)
        except Exception as e:
            log.warning("  Failed to drop %s: %s", table, e)

    log.info("Teardown complete.")


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Set up Agent Builder demo resources")
    parser.add_argument("--profile", required=True, help="Databricks CLI profile")
    parser.add_argument("--catalog", default=None, help="UC catalog (auto-detected if not set)")
    parser.add_argument("--schema", default="agent_builder", help="UC schema (default: agent_builder)")
    parser.add_argument("--teardown", action="store_true", help="Remove all demo resources")
    args = parser.parse_args()

    w = WorkspaceClient(profile=args.profile)
    user = w.current_user.me()
    log.info("Connected as: %s", user.user_name)
    log.info("Workspace:    %s", w.config.host)

    # Auto-detect catalog: prefer one owned by the current user, then any managed catalog
    catalog = args.catalog
    if not catalog:
        user_name = user.user_name
        managed = []
        for c in w.catalogs.list():
            if str(c.catalog_type) in ("MANAGED_CATALOG", "CatalogType.MANAGED_CATALOG"):
                managed.append(c)
        # First choice: catalog owned by the current user
        for c in managed:
            if c.owner == user_name:
                catalog = c.name
                break
        # Second choice: first managed catalog that isn't a shared/system catalog
        if not catalog:
            for c in managed:
                if "shared" not in c.name.lower() and "system" not in c.name.lower():
                    catalog = c.name
                    break
        # Last resort: any managed catalog
        if not catalog and managed:
            catalog = managed[0].name
    if not catalog:
        log.error("No managed catalog found. Specify --catalog.")
        sys.exit(1)
    log.info("Catalog:      %s", catalog)
    log.info("Schema:       %s", args.schema)

    wh_id = get_warehouse(w)

    if args.teardown:
        teardown(w, wh_id, catalog, args.schema)
        return

    notes_table = f"{catalog}.{args.schema}.patient_notes"
    metrics_table = f"{catalog}.{args.schema}.patient_metrics"
    index_name = f"{catalog}.{args.schema}.patient_notes_index"

    setup_schema(w, catalog, args.schema)
    setup_patient_notes(w, wh_id, notes_table)
    setup_patient_metrics(w, wh_id, metrics_table)
    setup_vs_endpoint(w)
    setup_vs_index(w, wh_id, notes_table, index_name)
    genie_id = setup_genie_space(w, wh_id, metrics_table)

    host = w.config.host.rstrip("/")
    log.info("\n" + "=" * 60)
    log.info("DEMO SETUP COMPLETE")
    log.info("=" * 60)
    log.info("")
    log.info("Resources created:")
    log.info("  patient_notes table:  %s", notes_table)
    log.info("  patient_metrics table:%s", metrics_table)
    log.info("  VS endpoint:          %s", VS_ENDPOINT_NAME)
    log.info("  VS index:             %s", index_name)
    if genie_id:
        log.info("  Genie space ID:       %s", genie_id)
    log.info("")
    log.info("Agent Builder config values:")
    log.info("  LLM endpoint:         databricks-claude-sonnet-4-6  (or any FMAPI endpoint)")
    log.info("  VS index name:        %s", index_name)
    log.info("  VS endpoint name:     %s", VS_ENDPOINT_NAME)
    log.info("  VS columns:           note_id, patient_id, department, note_type, physician, text")
    if genie_id:
        log.info("  Genie room ID:        %s", genie_id)
        log.info("")
        log.info("ACTION REQUIRED: Add patient_metrics table to Genie space via UI:")
        log.info("  %s/genie/rooms/%s", host, genie_id)
    log.info("")
    log.info("To tear down:  python demo/setup_demo.py --profile %s --teardown", args.profile)


if __name__ == "__main__":
    main()
