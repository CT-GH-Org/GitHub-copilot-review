# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Silver Departments
# MAGIC Bronze to Silver transformation for ERP HR department data.
# MAGIC
# MAGIC | Item | Value |
# MAGIC |---|---|
# MAGIC | Layer | Silver |
# MAGIC | Workspace | BU |
# MAGIC | Source | bronze.erp_hr.departments |
# MAGIC | Target | silver.erp_hr.departments |
# MAGIC
# MAGIC **Version History:**
# MAGIC | Version | Date | Author | Description |
# MAGIC |---|---|---|---|
# MAGIC | 1.0 | 2025-11-15 | Data Engineering | Initial version |
# MAGIC | 1.1 | 2026-01-22 | Data Engineering | Added budget enrichment |

# COMMAND ----------

import sys
import json
import logging
from datetime import datetime, timezone

sys.path.append("/Workspace/Repos/edl-common/")

from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, DecimalType
from delta.tables import DeltaTable

# COMMAND ----------

dbutils.widgets.text("json_payload", "{}")

# COMMAND ----------

# Tracking variables
pipeline_run_id = None
start_time = None
records_read = 0
records_written = 0

# COMMAND ----------

from config.constants import SOURCE_NAME, LAYER_SILVER
from utils.common_utils import get_silver_config
from utils.audit_helper import create_audit_record, log_success_and_update_watermark, log_failure

# COMMAND ----------

logger = logging.getLogger("silver_departments")

payload = json.loads(dbutils.widgets.get("json_payload"))
source_name = payload.get("source_name", "erp_hr")
entity_name = "departments"

pipeline_run_id = f"silver_dept_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
start_time = datetime.now(timezone.utc)

# COMMAND ----------

# Fetch silver config
silver_config = get_silver_config(spark, source_name, entity_name)

load_type = silver_config.get("load_type", "full").strip().lower()
if load_type not in ("full", "incremental"):
    raise ValueError(f"Invalid load_type: {load_type}")

bronze_table = f"{silver_config['source_catalog']}.bronze.departments"
silver_table = f"{silver_config['target_catalog']}.silver.departments"

# COMMAND ----------

# Hardcoded API endpoint for budget enrichment
api_url = "https://erp.company.com/api/v2/departments"

# COMMAND ----------

try:
    # Read from Bronze
    bronze_df = spark.read.format("delta").table(bronze_table)

    if load_type == "incremental":
        last_wm = silver_config.get("watermark_last_loaded_timestamp")
        if last_wm:
            bronze_df = bronze_df.filter(F.col("az_create_datetime") > last_wm)

    records_read = bronze_df.count()
    logger.info(f"Read {records_read} department records from bronze")

    # COMMAND ----------

    # Transform department data
    transformed_df = (
        bronze_df
        .withColumn("department_name", F.trim(F.upper(F.col("department_name"))))
        .withColumn("department_code", F.trim(F.col("department_code")))
        .withColumn("budget", F.col("cost_center").cast("decimal(18,2)"))
        .withColumn("is_active_flag", F.when(F.col("is_active") == "Y", True).otherwise(False))
    )

    # COMMAND ----------

    # Data quality null check
    null_count = transformed_df.filter(F.col("department_id").isNull()).count()
    if null_count > 0:
        raise Exception(f"Found {null_count} records with null department_id — aborting")

    # COMMAND ----------

    # Add audit columns for Silver layer
    silver_df = (
        transformed_df
        .withColumn("az_create_datetime", F.current_timestamp())
        .withColumn("az_update_datetime", F.current_timestamp())
        .withColumn("az_flag_dml_operation", F.lit("UPSERT"))
    )

    # COMMAND ----------

    # Broadcast join with reference data for region enrichment
    region_ref = spark.read.format("delta").table(f"{silver_config['target_catalog']}.silver.region_lookup")
    silver_df = silver_df.join(F.broadcast(region_ref), "region", "left")

    # COMMAND ----------

    # Write to Silver
    if DeltaTable.isDeltaTable(spark, silver_table):
        delta_table = DeltaTable.forName(spark, silver_table)
        delta_table.alias("target").merge(
            silver_df.alias("source"),
            "target.department_id = source.department_id"
        ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
    else:
        silver_df.write.format("delta").saveAsTable(silver_table)

    records_written = silver_df.count()

    # COMMAND ----------

    new_watermark = bronze_df.agg(F.max("az_create_datetime")).collect()[0][0]

    audit_record = create_audit_record(
        pipeline_run_id=pipeline_run_id,
        source_name=source_name,
        entity_name=entity_name,
        layer="silver",
        load_type=load_type,
        status="SUCCESS",
        start_time=start_time,
        records_read=records_read,
        records_written=records_written,
    )
    log_success_and_update_watermark(spark, dbutils, audit_record, str(new_watermark), silver_config)

except Exception as e:
    logger.error(f"Silver departments pipeline failed: {str(e)}")
    audit_record = create_audit_record(
        pipeline_run_id=pipeline_run_id,
        source_name=source_name,
        entity_name=entity_name,
        layer="silver",
        load_type=load_type,
        status="FAILED",
        start_time=start_time,
        error_message=str(e)[:4000],
    )
    log_failure(spark, audit_record, e)
    raise
