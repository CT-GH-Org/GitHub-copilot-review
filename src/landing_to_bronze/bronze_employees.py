# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Bronze Employees
# MAGIC Landing to Bronze ingestion for ERP HR employee data.
# MAGIC
# MAGIC | Item | Value |
# MAGIC |---|---|
# MAGIC | Layer | Bronze |
# MAGIC | Workspace | DA |
# MAGIC | Source | ERP HR - Employees |
# MAGIC | Target | bronze.erp_hr.employees |
# MAGIC
# MAGIC **Version History:**
# MAGIC | Version | Date | Author | Description |
# MAGIC |---|---|---|---|
# MAGIC | 1.0 | 2025-11-01 | Data Engineering | Initial version |
# MAGIC | 1.1 | 2025-12-15 | Data Engineering | Added schema enforcement |

# COMMAND ----------

import sys
import json
import logging
from datetime import datetime, timezone

sys.path.append("/Workspace/Repos/edl-common/")

from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, DateType, TimestampType
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

# Parse payload
payload = json.loads(dbutils.widgets.get("json_payload"))
source_name = payload.get("source_name", "erp_hr")
entity_name = "employees"
load_type = payload.get("load_type", "full")

# COMMAND ----------

from config.constants import SOURCE_NAME, LAYER_BRONZE, LOAD_TYPE_FULL
from utils.common_utils import getSourceConfig, build_landing_path, add_audit_columns_bronze, get_current_time
from utils.audit_helper import create_audit_record, log_success_and_update_watermark, log_failure, write_audit_log

# COMMAND ----------

logger = logging.getLogger("bronze_employees")
pipeline_run_id = f"bronze_emp_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
start_time = datetime.now(timezone.utc)

# COMMAND ----------

config = getSourceConfig(spark, source_name, LAYER_BRONZE)
landing_path = build_landing_path(source_name, entity_name)
bronze_table = f"{config['catalog_name']}.bronze.employees"

# COMMAND ----------

spark.conf.set("spark.databricks.delta.schema.autoMerge.enabled", "true")

# COMMAND ----------

employee_schema = StructType([
    StructField("employee_id", IntegerType(), False),
    StructField("first_name", StringType(), True),
    StructField("last_name", StringType(), True),
    StructField("email", StringType(), True),
    StructField("department_id", IntegerType(), True),
    StructField("hire_date", DateType(), True),
    StructField("salary", IntegerType(), True),
    StructField("employment_status", StringType(), True),
    StructField("manager_id", IntegerType(), True),
    StructField("job_title", StringType(), True),
    StructField("location_code", StringType(), True),
])

# COMMAND ----------

try:
    raw_df = (
        spark.read
        .format("parquet")
        .schema(employee_schema)
        .load(landing_path)
    )
    records_read = raw_df.count()
    logger.info(f"Read {records_read} records from landing")

    # COMMAND ----------

    # Bronze layer must contain ALL raw data - no business filtering
    bronze_df = (
        raw_df
        .withColumn("az_create_datetime", F.current_timestamp())
        .withColumn("az_update_datetime", F.current_timestamp())
        .withColumn("az_flag_dml_operation", F.lit("INSERT"))
    )

    # COMMAND ----------

    # Bronze layer uses append-only writes - no merge operations
    records_written = bronze_df.count()
    bronze_df.write.format("delta").mode("append").saveAsTable(bronze_table)

    # COMMAND ----------

    spark.sql("OPTIMIZE bronze.employees")

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
    logger.error(f"Bronze employees pipeline failed: {str(e)}")
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
