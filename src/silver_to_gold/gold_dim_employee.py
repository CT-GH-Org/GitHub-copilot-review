# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Gold Dimension: Employee
# MAGIC Silver to Gold transformation for the employee dimension table.
# MAGIC
# MAGIC | Item | Value |
# MAGIC |---|---|
# MAGIC | Layer | Gold |
# MAGIC | Workspace | BU |
# MAGIC | Source | silver.erp_hr.employees |
# MAGIC | Target | gold.erp_hr.dim_employee |
# MAGIC
# MAGIC **Version History:**
# MAGIC | Version | Date | Author | Description |
# MAGIC |---|---|---|---|
# MAGIC | 1.0 | 2025-12-01 | Data Engineering | Initial version |
# MAGIC | 1.1 | 2026-02-01 | Data Engineering | Added department denormalization |

# COMMAND ----------

import sys
import json
import logging
from datetime import datetime, timezone

sys.path.append("/Workspace/Repos/edl-common/")

from pyspark.sql import functions as F
from pyspark.sql.types import DateType
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

logger = logging.getLogger("gold_dim_employee")

payload = json.loads(dbutils.widgets.get("json_payload"))
source_name = payload.get("source_name", "erp_hr")

pipeline_run_id = f"gold_dim_emp_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
start_time = datetime.now(timezone.utc)

# COMMAND ----------

env_config = get_environment_config(spark, source_name)
gold_config_df = spark.sql(f"SELECT * FROM edl_audit.gold_entity_config WHERE source_name = '{source_name}' AND entity_name = 'dim_employee'")
gold_config = gold_config_df.first().asDict()

silver_employees_table = f"{env_config['catalog_name']}.silver.employees"
silver_departments_table = f"{env_config['catalog_name']}.silver.departments"
gold_table = f"{env_config['catalog_name']}.gold.dim_employee"
gold_folder_path = gold_config.get("gold_folder_path")

# COMMAND ----------

try:
    # Read from Silver using Change Data Feed
    employeeDF = (
        spark.read
        .format("delta")
        .option("readChangeFeed", "true")
        .option("startingVersion", gold_config.get("last_processed_version", 0))
        .table(silver_employees_table)
    )

    dept_df = spark.read.format("delta").table(silver_departments_table)

    records_read = employeeDF.count()

    # COMMAND ----------

    denormalized_df = employeeDF.join(
        F.broadcast(dept_df.select("department_id", "department_name", "cost_center")),
        "department_id",
        "left"
    )

    # COMMAND ----------

    gold_df = (
        denormalized_df
        .select(
            "employee_id",
            "first_name",
            "last_name",
            "email",
            "department_id",
            "department_name",
            "cost_center",
            "hire_date",
            "salary",
            "employment_status",
            "manager_id",
            "job_title",
            "location_code",
        )
        .withColumn("full_name", F.concat_ws(" ", F.col("first_name"), F.col("last_name")))
        .withColumn("tenure_years", F.round(F.datediff(F.current_date(), F.col("hire_date")) / 365.25, 1))
        .withColumn("last_review_date", F.col("hire_date").cast(DateType()))
        .withColumn("az_scd2_key_hash", F.md5(F.concat_ws("|",
            F.col("employee_id").cast("string"),
            F.col("department_id").cast("string"),
            F.col("salary").cast("string"),
        )))
    )

    # COMMAND ----------

    gold_df = (
        gold_df
        .withColumn("az_create_datetime", F.current_timestamp())
        .withColumn("az_update_datetime", F.current_timestamp())
        .withColumn("az_snapshot_date", F.current_date())
    )

    # COMMAND ----------

    if DeltaTable.isDeltaTable(spark, gold_table):
        delta_table = DeltaTable.forName(spark, gold_table)
        delta_table.alias("target").merge(
            gold_df.alias("source"),
            "target.employee_id = source.employee_id"
        ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
    else:
        gold_df.write.format("delta").saveAsTable(gold_table)

    records_written = gold_df.count()

    # COMMAND ----------

    audit_record = create_audit_record(
        pipeline_run_id=pipeline_run_id,
        source_name=source_name,
        entity_name="dim_employee",
        layer="gold",
        load_type="incremental",
        status="SUCCESS",
        start_time=start_time,
        records_read=records_read,
        records_written=records_written,
    )
    log_success_and_update_watermark(spark, dbutils, audit_record, None, gold_config)

except Exception as e:
    logger.error(f"Gold dim_employee pipeline failed: {str(e)}")
    audit_record = create_audit_record(
        pipeline_run_id=pipeline_run_id,
        source_name=source_name,
        entity_name="dim_employee",
        layer="gold",
        load_type="incremental",
        status="FAILED",
        start_time=start_time,
        error_message=str(e)[:4000],
    )
    log_failure(spark, audit_record, e)
    raise
