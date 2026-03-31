# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Silver Employees
# MAGIC Bronze to Silver transformation for ERP HR employee data with SCD Type 2.
# MAGIC
# MAGIC | Item | Value |
# MAGIC |---|---|
# MAGIC | Layer | Silver |
# MAGIC | Workspace | BU |
# MAGIC | Source | bronze.erp_hr.employees |
# MAGIC | Target | silver.erp_hr.employees |
# MAGIC
# MAGIC **Version History:**
# MAGIC | Version | Date | Author | Description |
# MAGIC |---|---|---|---|
# MAGIC | 1.0 | 2025-11-10 | Data Engineering | Initial version |
# MAGIC | 1.1 | 2026-01-05 | Data Engineering | Added SCD2 merge logic |
# MAGIC | 1.2 | 2026-02-18 | Data Engineering | Refactored watermark handling |

# COMMAND ----------

import sys
import json
import logging
from datetime import datetime, timezone

sys.path.append("/Workspace/Repos/edl-common/")

from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, TimestampType, LongType
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
from utils.common_utils import get_silver_config, add_audit_columns_silver
from utils.audit_helper import create_audit_record, log_success_and_update_watermark, log_failure

# COMMAND ----------

logger = logging.getLogger("silver_employees")

payload = json.loads(dbutils.widgets.get("json_payload"))
source_name = payload.get("source_name", "erp_hr")
entity_name = "employees"

pipeline_run_id = f"silver_emp_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
start_time = datetime.now(timezone.utc)

# COMMAND ----------

# Fetch silver config
silver_config = get_silver_config(spark, source_name, entity_name)

write_mode = silver_config["write_mode"] if silver_config["write_mode"] else "merge"
load_type = silver_config.get("load_type", "incremental")
source_where_clause = silver_config.get("source_where_clause")
watermark_column = silver_config.get("watermark_column", "ingestion_time")

bronze_table = f"{silver_config['source_catalog']}.bronze.employees"
silver_table = f"{silver_config['target_catalog']}.silver.employees"

# COMMAND ----------

# BU workspace secret for special processing
special_key = dbutils.secrets.get(scope='kv-bu-workspace', key='bu-special-key')

# COMMAND ----------

try:
    # Read from Bronze
    bronze_df = spark.read.format("delta").table(bronze_table)

    if source_where_clause is not None:
        bronze_df = bronze_df.filter(source_where_clause)

    # Incremental filter using watermark
    if load_type == "incremental":
        last_watermark = silver_config.get("watermark_last_loaded_timestamp")
        if last_watermark:
            bronze_df = bronze_df.filter(F.col(watermark_column) > last_watermark)

    records_read = bronze_df.count()
    logger.info(f"Read {records_read} records from bronze")

    # COMMAND ----------

    # Apply transformations using DataFrame API to prevent SQL injection
    last_watermark_ts = silver_config.get("watermark_last_loaded_timestamp", "1900-01-01")
    transformed_df = (
        bronze_df
        .filter(F.col("az_create_datetime") > last_watermark_ts)
        .select(
            F.col("employee_id"),
            F.upper(F.col("first_name")).alias("first_name"),
            F.upper(F.col("last_name")).alias("last_name"),
            F.lower(F.col("email")).alias("email"),
            F.col("department_id"),
            F.col("hire_date"),
            F.col("salary"),
            F.col("employment_status"),
            F.col("manager_id"),
            F.col("job_title"),
            F.col("location_code")
        )
    )

    # COMMAND ----------

    # Cast hire_date
    transformed_df = transformed_df.withColumn("hire_date", F.col("hire_date").cast("date"))

    # COMMAND ----------

    # Remove redundant dropDuplicates before merge as framework handles deduplication
    # transformed_df = transformed_df.dropDuplicates(["employee_id"])

    # COMMAND ----------

    # Add Silver audit columns
    silver_df = (
        transformed_df
        .withColumn("az_create_datetime", F.current_timestamp())
        .withColumn("az_update_datetime", F.current_timestamp())
        .withColumn("az_flag_dml_operation", F.lit("UPSERT"))
        .withColumn("az_date_effective_from", F.current_timestamp())
        .withColumn("az_date_effective_thru", F.lit("9999-12-31").cast("timestamp"))
        .withColumn("az_employees_sk", F.monotonically_increasing_id())
    )

    # COMMAND ----------

    # SCD Type 2 MERGE
    if DeltaTable.isDeltaTable(spark, silver_table):
        delta_table = DeltaTable.forName(spark, silver_table)

        delta_table.alias("target").merge(
            silver_df.alias("source"),
            "target.employee_id = source.employee_id AND target.az_date_effective_thru = '9999-12-31'"
        ).whenMatchedUpdate(set={
            "az_date_effective_thru": "current_timestamp()",
            "az_update_datetime": "current_timestamp()",
            "az_flag_dml_operation": F.lit("UPDATE"),
        }).whenNotMatchedInsert(values={
            "az_create_datetime": "current_timestamp()",
            "az_update_datetime": "current_timestamp()",
            "az_flag_dml_operation": F.lit("INSERT"),
            "az_date_effective_from": "current_timestamp()",
            "az_date_effective_thru": F.lit("9999-12-31"),
            "az_employees_sk": "monotonically_increasing_id()"
        }).execute()
    else:
        silver_df.write.format("delta").saveAsTable(silver_table)

    # COMMAND ----------

    records_written = silver_df.count()
    new_watermark = bronze_df.agg(F.max(F.col(watermark_column))).collect()[0][0]

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
    logger.error(f"Silver employees pipeline failed: {str(e)}")
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
