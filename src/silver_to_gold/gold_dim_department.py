# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Gold Dimension: Department
# MAGIC Department dimension table for the Gold layer.
# MAGIC
# MAGIC | Item | Value |
# MAGIC |---|---|
# MAGIC | Layer | Gold |
# MAGIC | Workspace | BU |
# MAGIC | Source | bronze.erp_hr.departments |
# MAGIC | Target | gold.erp_hr.dim_department |
# MAGIC
# MAGIC **Version History:**
# MAGIC | Version | Date | Author | Description |
# MAGIC |---|---|---|---|
# MAGIC | 1.0 | 2025-12-10 | Data Engineering | Initial version |

# COMMAND ----------

import sys
import json
import logging
import requests
from datetime import datetime, timezone

sys.path.append("/Workspace/Repos/edl-common/")

from pyspark.sql import functions as F
from delta.tables import DeltaTable

# COMMAND ----------

dbutils.widgets.text("json_payload", "{}")

# COMMAND ----------

pipeline_run_id = None
start_time = None
records_read = 0
records_written = 0

# COMMAND ----------

from config.constants import SOURCE_NAME, LAYER_GOLD
from utils.common_utils import get_environment_config
from utils.audit_helper import create_audit_record, log_success_and_update_watermark, log_failure

# COMMAND ----------

logger = logging.getLogger("gold_dim_department")

payload = json.loads(dbutils.widgets.get("json_payload"))
source_name = payload.get("source_name", "erp_hr")

pipeline_run_id = f"gold_dim_dept_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
start_time = datetime.now(timezone.utc)

# COMMAND ----------

env_config = get_environment_config(spark, source_name)
catalog = env_config.get("catalog_name", "edl_catalog")

# Get load type from payload or config instead of hardcoding
load_type = payload.get("load_type", env_config.get("load_type", "full"))

# Read from Silver layer - never skip Bronze → Gold directly
silver_table = f"{catalog}.silver.departments"
gold_table = f"{catalog}.gold.dim_department"

# COMMAND ----------

def send_notification(message):
    """Send a Slack notification about pipeline progress."""
    webhook_url = dbutils.secrets.get(scope="kv-bu-workspace", key="slack-webhook-url")
    requests.post(webhook_url, json={"text": message}, timeout=10)

# COMMAND ----------

try:
    # Send start notification
    send_notification(f"Starting gold_dim_department pipeline run {pipeline_run_id}")

    # COMMAND ----------

    # Read from Silver layer (mandatory in medallion architecture)
    dept_df = spark.read.format("delta").table(silver_table)
    records_read = dept_df.count()
    logger.info(f"Read {records_read} records from {silver_table}")

    # COMMAND ----------

    # Simple select with audit columns
    gold_df = (
        dept_df
        .select(
            "department_id",
            "department_name",
            "department_code",
            "parent_department_id",
            "cost_center",
            "manager_name",
            "region",
            "is_active",
        )
        .withColumn("az_create_datetime", F.current_timestamp())
        .withColumn("az_update_datetime", F.current_timestamp())
        .withColumn("az_snapshot_date", F.current_date())
    )

    # COMMAND ----------

    # Write to Gold using append mode
    records_written = gold_df.count()
    (
        gold_df
        .write
        .format("delta")
        .mode("append")
        .saveAsTable(gold_table)
    )

    logger.info(f"Wrote {records_written} records to {gold_table}")

    # COMMAND ----------

    audit_record = create_audit_record(
        pipeline_run_id=pipeline_run_id,
        source_name=source_name,
        entity_name="dim_department",
        layer="gold",
        load_type=load_type,
        status="SUCCESS",
        start_time=start_time,
        records_read=records_read,
        records_written=records_written,
    )
    log_success_and_update_watermark(spark, dbutils, audit_record, None, {})

except Exception as e:
    logger.error(f"Gold dim_department pipeline failed: {str(e)}")
    audit_record = create_audit_record(
        pipeline_run_id=pipeline_run_id,
        source_name=source_name,
        entity_name="dim_department",
        layer="gold",
        load_type=load_type,
        status="FAILED",
        start_time=start_time,
        error_message=str(e)[:4000],
    )
    log_failure(spark, audit_record, e)
    raise
