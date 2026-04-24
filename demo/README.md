# AgentSweet Demo Environment

Sets up demo resources (tables, Vector Search, Genie) in a Databricks workspace so AgentSweet has data to work with.

## Setup

```bash
python demo/setup_demo.py --profile BUILDER
```

Options:
- `--profile` (required) — Databricks CLI profile for the target workspace
- `--catalog` — UC catalog to use (auto-detected from first managed catalog if omitted)
- `--schema` — UC schema (default: `agent_sweet`)
- `--teardown` — Remove all demo resources

## What gets created

| Resource | Name | Purpose |
|----------|------|---------|
| Table | `{catalog}.{schema}.patient_notes` | 12 clinical notes for Vector Search |
| Table | `{catalog}.{schema}.patient_metrics` | 15 patient records for Genie analytics |
| VS Endpoint | `agent-sweet-vs` | Hosts the vector search index |
| VS Index | `{catalog}.{schema}.patient_notes_index` | Embeddings on `text` column via GTE-large |
| Genie Space | Hospital Patient Analytics | Natural language queries on patient_metrics |

## Using in AgentSweet

After setup, configure nodes with these values:

**LLM Node:**
- Endpoint: `databricks-claude-sonnet-4-6` (or any FMAPI endpoint)

**Vector Search Node:**
- Index: `{catalog}.{schema}.patient_notes_index`
- Endpoint: `agent-sweet-vs`
- Columns: `note_id, patient_id, department, note_type, physician, text`

**Genie Node:**
- Room ID: printed by the setup script

## Manual step

The Genie space is created empty — you need to add `patient_metrics` as a table through the UI. The setup script prints the URL.

## Teardown

```bash
python demo/setup_demo.py --profile BUILDER --teardown
```
