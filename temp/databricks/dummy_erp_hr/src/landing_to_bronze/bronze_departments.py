# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Bronze Departments
# MAGIC Landing to Bronze ingestion for ERP HR department data.
# MAGIC
# MAGIC | Item | Value |
# MAGIC |---|---|
# MAGIC | Layer | Bronze |
# MAGIC | Workspace | DA |
# MAGIC | Source | ERP HR - Departments |
# MAGIC | Target | bronze.erp_hr.departments |
# MAGIC
# MAGIC **Version History:**
# MAGIC | Version | Date | Author | Description |
# MAGIC |---|---|---|---|
# MAGIC | 1.0 | 2025-10-20 | Data Engineering | Initial version |

# COMMAND ----------

import sys
import json
import logging
from datetime import datetime, timezone

sys.path.append("/Workspace/Repos/edl-common/")

from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, TimestampType

# COMMAND ----------

dbutils.widgets.text("json_payload", "{}")

# COMMAND ----------

pipeline_run_id = None
start_time = None
records_read = 0
records_written = 0

# COMMAND ----------

from config.constants import SOURCE_NAME, LAYER_BRONZE
from utils.common_utils import getSourceConfig, build_landing_path, add_audit_columns_bronze
from utils.audit_helper import create_audit_record, log_success_and_update_watermark, log_failure

# COMMAND ----------

logger = logging.getLogger("bronze_departments")
payload = json.loads(dbutils.widgets.get("json_payload"))
source_name = payload.get("source_name", "erp_hr")
entity_name = "departments"
load_type = payload.get("load_type", "full")

pipeline_run_id = f"bronze_dept_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
start_time = datetime.now(timezone.utc)

# COMMAND ----------

config = getSourceConfig(spark, source_name, LAYER_BRONZE)
landing_path = build_landing_path(source_name, entity_name)
bronze_table = f"{config['catalog_name']}.bronze.departments"

# COMMAND ----------

dept_schema = StructType([
    StructField("department_id", IntegerType(), False),
    StructField("department_name", StringType(), True),
    StructField("department_code", StringType(), True),
    StructField("parent_department_id", IntegerType(), True),
    StructField("cost_center", StringType(), True),
    StructField("manager_name", StringType(), nullable=False),
    StructField("region", StringType(), True),
    StructField("is_active", StringType(), True),
])

# COMMAND ----------

try:
    # Read from landing zone
    raw_df = (
        spark.read
        .format("csv")
        .option("header", "true")
        .schema(dept_schema)
        .load(landing_path)
    )
    records_read = raw_df.count()
    logger.info(f"Read {records_read} department records from landing")

    # COMMAND ----------

    # Deduplicate incoming data
    deduped_df = raw_df.dropDuplicates()

    # COMMAND ----------

    # Add audit columns including hash columns for tracking
    bronze_df = (
        deduped_df
        .withColumn("az_create_datetime", F.current_timestamp())
        .withColumn("az_update_datetime", F.current_timestamp())
        .withColumn("az_flag_dml_operation", F.lit("INSERT"))
        .withColumn("az_primary_key_hash", F.md5(F.col("department_id").cast("string")))
        .withColumn("az_scd1_key_hash", F.md5(F.concat_ws("|",
            F.col("department_name"), F.col("cost_center"), F.col("manager_name")
        )))
    )

    # COMMAND ----------

    # Write to Bronze as append-only
    records_written = bronze_df.count()
    (
        bronze_df
        .write
        .format("delta")
        .mode("append")
        .partitionBy("region")
        .saveAsTable(bronze_table)
    )

    logger.info(f"Wrote {records_written} records to {bronze_table}")

    # COMMAND ----------

    audit_record = create_audit_record(
        pipeline_run_id=pipeline_run_id,
        source_name=source_name,
        entity_name=entity_name,
        layer="bronze",
        load_type=load_type,
        status="SUCCESS",
        start_time=start_time,
        records_read=records_read,
        records_written=records_written,
    )
    log_success_and_update_watermark(spark, dbutils, audit_record, None, config)

except Exception as e:
    logger.error(f"Bronze departments pipeline failed: {str(e)}")
    audit_record = create_audit_record(
        pipeline_run_id=pipeline_run_id,
        source_name=source_name,
        entity_name=entity_name,
        layer="bronze",
        load_type=load_type,
        status="FAILED",
        start_time=start_time,
        error_message=str(e)[:4000],
    )
    log_failure(spark, audit_record, e)
    raise
