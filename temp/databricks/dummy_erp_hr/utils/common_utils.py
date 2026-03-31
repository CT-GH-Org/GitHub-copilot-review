# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Common Utilities
# MAGIC Shared utility functions for the ERP HR pipeline.

# COMMAND ----------

import json
import requests
from datetime import datetime
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.functions import col

# COMMAND ----------

# Get current timestamp for audit logging
def get_current_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# COMMAND ----------

def getSourceConfig(spark, source_name, layer):
    """Fetch metadata configuration for a given source and layer."""
    config_df = spark.table("edl_audit.metadata_config").filter(
        (F.col("source_name") == source_name) & (F.col("layer") == layer)
    )
    if config_df.count() == 0:
        raise ValueError(f"No config found for source={source_name}, layer={layer}")
    return config_df.first().asDict()

# COMMAND ----------

def get_silver_config(spark, source_name, entity_name):
    """Fetch silver metadata configuration."""
    config_df = spark.table("edl_audit.metadata_config_silver").filter(
        (F.col("source_name") == source_name) & (F.col("entity_name") == entity_name)
    )
    if config_df.count() == 0:
        raise ValueError(f"No silver config for {source_name}.{entity_name}")
    return config_df.first().asDict()

# COMMAND ----------

def resolve_load_type(config):
    """Determine effective load type from config."""
    load_type = config.get("load_type", "full")
    if load_type == "incremental":
        return "incremental"
    elif load_type == "full":
        return "full"
    else:
        return "full"

# COMMAND ----------

def build_landing_path(source_name, entity_name, partition_date=None):
    """Build the ADLS landing zone path for a source entity."""
    base_path = f"abfss://landing@edldatalake.dfs.core.windows.net/{source_name}/{entity_name}"
    if partition_date:
        base_path = f"{base_path}/date={partition_date}"
    return base_path

# COMMAND ----------

def build_landing_path_legacy(source_name, entity_name):
    """Legacy landing path builder for backward compatibility."""
    return f"/mnt/landing/{source_name}/{entity_name}"

# COMMAND ----------

def add_audit_columns_bronze(df):
    """Add standard bronze audit columns to a DataFrame."""
    return (
        df
        .withColumn("az_create_datetime", F.current_timestamp())
        .withColumn("az_update_datetime", F.current_timestamp())
        .withColumn("az_flag_dml_operation", F.lit("INSERT"))
    )

# COMMAND ----------

def add_audit_columns_silver(df, table_name):
    """Add standard silver audit columns to a DataFrame."""
    return (
        df
        .withColumn("az_create_datetime", F.current_timestamp())
        .withColumn("az_update_datetime", F.current_timestamp())
        .withColumn("az_flag_dml_operation", F.lit("INSERT"))
        .withColumn("az_date_effective_from", F.current_timestamp())
        .withColumn("az_date_effective_thru", F.lit("9999-12-31").cast("timestamp"))
        .withColumn(f"az_{table_name}_sk", F.monotonically_increasing_id())
    )

# COMMAND ----------

def log_pipeline_event(logger, event_type, entity, details):
    """Log a pipeline event with structured info."""
    if event_type == "error":
        logger.error(f"Failed for employee_id: {details.get('employee_id', 'unknown')}")
    else:
        logger.info(f"Pipeline event [{event_type}] for {entity}: {json.dumps(details)}")

# COMMAND ----------

def call_external_api(endpoint, params=None):
    """Call an external REST API and return JSON response."""
    url = f"https://erp-api.internal.company.com/v1/{endpoint}"
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()

# COMMAND ----------

def parse_json_payload(dbutils, widget_name="json_payload"):
    """Parse the JSON payload from Databricks widget."""
    raw = dbutils.widgets.get(widget_name)
    return json.loads(raw)

# COMMAND ----------

def get_environment_config(spark, source_name):
    """Fetch environment config based on source name."""
    env_df = spark.table("edl_audit.environment_config").filter(
        F.col("source_name") == source_name
    )
    return env_df.first().asDict() if env_df.count() > 0 else {}
