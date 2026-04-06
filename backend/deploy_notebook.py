# Databricks notebook source

# COMMAND ----------

# Install the app package from Git (branch-aware)
import subprocess, json

params = json.loads(dbutils.widgets.get("params_json"))  # noqa: F821
git_ref = params.get("git_ref", "main")
repo_url = params.get("repo_url", "https://github.com/btbeal-db/agent-sweet.git")
pkg = f"git+{repo_url}@{git_ref}"
print(f"Installing: {pkg}")
subprocess.check_call(["pip", "install", pkg, "--upgrade", "--quiet"])

dbutils.library.restartPython()  # noqa: F821

# COMMAND ----------

import json
import tempfile
from pathlib import Path

import mlflow
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import ResourceAlreadyExists
from databricks.sdk.service.serving import (
    AiGatewayConfig,
    AiGatewayInferenceTableConfig,
    EndpointCoreConfigInput,
    ServedEntityInput,
)

from backend.deploy_helpers import extract_resources, collect_code_paths
from backend.schema import GraphDef

# COMMAND ----------

# Parse deployment config
params = json.loads(dbutils.widgets.get("params_json"))  # noqa: F821
graph_def = GraphDef.model_validate(json.loads(params["graph_json"]))
model_name = params["model_name"]
catalog = params["catalog"]
schema_name = params["schema_name"]
experiment_base = params["experiment_base"]
lakebase_conn_string = params.get("lakebase_conn_string", "")
deployed_by = params.get("deployed_by", "unknown")

fq_model_name = f"{catalog}.{schema_name}.{model_name}"
endpoint_name = model_name.replace("_", "-")
experiment_path = f"{experiment_base}/{model_name}"

print(f"Model: {fq_model_name}")
print(f"Experiment: {experiment_path}")
print(f"Endpoint: {endpoint_name}")
print(f"Deployed by: {deployed_by}")

# COMMAND ----------

# Step 1: Log model to MLflow

mlflow.set_tracking_uri("databricks")
mlflow.set_registry_uri("databricks-uc")
experiment = mlflow.set_experiment(experiment_path)

with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    f.write(graph_def.model_dump_json())
    graph_def_path = f.name

resources = extract_resources(graph_def)

import backend
backend_dir = Path(backend.__file__).parent
python_model_path = str(backend_dir / "mlflow_model.py")
code_paths = collect_code_paths()
requirements_path = backend_dir / "requirements-serving.txt"

with mlflow.start_run() as run:
    mlflow.set_tag("deployed_by", deployed_by)
    mlflow.set_tag("agent_name", model_name)
    mlflow.set_tag("endpoint_name", endpoint_name)

    # Read requirements as a list, filtering out comments and the package itself.
    # We must pass pip_requirements as a list to fully override MLflow's
    # auto-detection, which would otherwise include agent-builder-app (the
    # installed package) — that fails in the serving container since it's
    # not published to PyPI.
    pip_reqs = []
    if requirements_path.exists():
        for line in requirements_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-"):
                pip_reqs.append(line)

    log_kwargs = dict(
        artifact_path="agent",
        python_model=python_model_path,
        artifacts={"graph_def": graph_def_path},
        code_paths=code_paths,
        resources=resources if resources else None,
        pip_requirements=pip_reqs,
    )

    model_info = mlflow.pyfunc.log_model(**log_kwargs)
    run_id = run.info.run_id

print(f"Model logged. Run ID: {run_id}")

# COMMAND ----------

# Step 2: Register in Unity Catalog

mv = mlflow.register_model(
    model_uri=model_info.model_uri,
    name=fq_model_name,
)
print(f"Registered {fq_model_name} version {mv.version}")

# COMMAND ----------

# Step 3: Create/update serving endpoint

w = WorkspaceClient()

env_vars = {
    "ENABLE_MLFLOW_TRACING": "true",
    "MLFLOW_EXPERIMENT_ID": experiment.experiment_id,
}
if lakebase_conn_string:
    env_vars["LAKEBASE_CONN_STRING"] = lakebase_conn_string

served_entity = ServedEntityInput(
    entity_name=fq_model_name,
    entity_version=str(mv.version),
    environment_vars=env_vars,
    scale_to_zero_enabled=True,
    workload_size="Small",
)

ai_gateway = AiGatewayConfig(
    inference_table_config=AiGatewayInferenceTableConfig(
        catalog_name=catalog,
        schema_name=schema_name,
        table_name_prefix=endpoint_name,
        enabled=True,
    ),
)

try:
    w.serving_endpoints.create(
        name=endpoint_name,
        config=EndpointCoreConfigInput(
            name=endpoint_name,
            served_entities=[served_entity],
        ),
        ai_gateway=ai_gateway,
    )
    print(f"Creating endpoint '{endpoint_name}'...")
except ResourceAlreadyExists:
    w.serving_endpoints.update_config(
        name=endpoint_name,
        served_entities=[served_entity],
    )
    w.serving_endpoints.put_ai_gateway(
        name=endpoint_name,
        inference_table_config=AiGatewayInferenceTableConfig(
            catalog_name=catalog,
            schema_name=schema_name,
            table_name_prefix=endpoint_name,
            enabled=True,
        ),
    )
    print(f"Updated existing endpoint '{endpoint_name}'")

host = w.config.host.rstrip("/")
endpoint_url = f"{host}/serving-endpoints/{endpoint_name}/invocations"

# COMMAND ----------

# Return result
dbutils.notebook.exit(json.dumps({  # noqa: F821
    "success": True,
    "run_id": run_id,
    "model_version": str(mv.version),
    "endpoint_url": endpoint_url,
}))
