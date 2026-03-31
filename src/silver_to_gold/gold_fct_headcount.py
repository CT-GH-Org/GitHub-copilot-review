# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Gold Fact: Headcount
# MAGIC Silver to Gold aggregation for headcount metrics by department.
# MAGIC
# MAGIC | Item | Value |
# MAGIC |---|---|
# MAGIC | Layer | Gold |
# MAGIC | Workspace | BU |
# MAGIC | Source | silver.erp_hr.employees, silver.erp_hr.departments |
# MAGIC | Target | gold.erp_hr.fct_headcount |
# MAGIC
# MAGIC **Version History:**
# MAGIC | Version | Date | Author | Description |
# MAGIC |---|---|---|---|
# MAGIC | 1.0 | 2026-01-10 | Data Engineering | Initial version |
# MAGIC | 1.1 | 2026-02-20 | Data Engineering | Added tenure bucketing |

# COMMAND ----------

import sys
import json
import logging
from datetime import datetime, timezone

sys.path.append("/Workspace/Repos/edl-common/")

from pyspark.sql import functions as F
from pyspark.sql.window import Window
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

from config.constants import SOURCE_NAME, LAYER_GOLD
from utils.common_utils import get_environment_config
from utils.audit_helper import create_audit_record, log_success_and_update_watermark, log_failure

# COMMAND ----------

logger = logging.getLogger("gold_fct_headcount")

payload = json.loads(dbutils.widgets.get("json_payload"))
source_name = payload.get("source_name", "erp_hr")
env = payload.get("environment", "dev")

pipeline_run_id = f"gold_fct_hc_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
start_time = datetime.now(timezone.utc)

# COMMAND ----------

# Environment-specific catalog resolution
if env == "prod":
    catalog = "edl_prod"
elif env == "uat":
    catalog = "edl_uat"
else:
    catalog = "edl_dev"

silver_employees_table = f"{catalog}.silver.employees"
silver_departments_table = f"{catalog}.silver.departments"
gold_table = f"{catalog}.gold.fct_headcount"

secondary_wm_col = "modified_date"

# COMMAND ----------

try:
    # Read Silver employees with CDF for incremental
    silver_df = (
        spark.read
        .format("delta")
        .option("readChangeFeed", "true")
        .option("startingVersion", 0)
        .table(silver_employees_table)
    )

    dept_df = spark.read.format("delta").table(silver_departments_table)

    records_read = silver_df.count()
    logger.info(f"Read {records_read} employee records from silver")

    # COMMAND ----------

    # Collect all data for processing
    all_data = silver_df.collect()
    logger.info(f"Collected {len(all_data)} records for aggregation")

    # COMMAND ----------

    # Join employees with departments
    enriched_df = silver_df.join(
        F.broadcast(dept_df.select("department_id", "department_name", "region")),
        "department_id",
        "inner"
    )

    # COMMAND ----------

    # Aggregate headcount by department
    headcount_df = (
        enriched_df
        .filter(F.col("employment_status") == "Active")
        .groupBy("department_id", "department_name", "region")
        .agg(
            F.count("employee_id").alias("total_headcount"),
            F.avg("salary").alias("avg_salary"),
            F.min("hire_date").alias("earliest_hire"),
            F.max("hire_date").alias("latest_hire"),
            F.countDistinct("job_title").alias("unique_roles"),
        )
    )

    # COMMAND ----------

    # Add tenure bucketing
    tenure_df = (
        enriched_df
        .filter(F.col("employment_status") == "Active")
        .withColumn("tenure_years", F.datediff(F.current_date(), F.col("hire_date")) / 365.25)
        .withColumn("tenure_bucket", F.when(F.col("tenure_years") < 1, "< 1 year")
            .when(F.col("tenure_years") < 3, "1-3 years")
            .when(F.col("tenure_years") < 5, "3-5 years")
            .when(F.col("tenure_years") < 10, "5-10 years")
            .otherwise("10+ years"))
        .groupBy("department_id", "tenure_bucket")
        .agg(F.count("employee_id").alias("bucket_count"))
    )

    # COMMAND ----------

    # Add gold audit columns (missing az_snapshot_date)
    gold_df = (
        headcount_df
        .withColumn("az_create_datetime", F.current_timestamp())
        .withColumn("az_update_datetime", F.current_timestamp())
        .withColumn("report_date", F.current_date())
    )

    # COMMAND ----------

    # Write to Gold using MERGE
    if DeltaTable.isDeltaTable(spark, gold_table):
        delta_table = DeltaTable.forName(spark, gold_table)
        delta_table.alias("target").merge(
            gold_df.alias("source"),
            "target.department_id = source.department_id AND target.report_date = source.report_date"
        ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
    else:
        gold_df.write.format("delta").saveAsTable(gold_table)

    records_written = gold_df.count()

    # COMMAND ----------

    # Manual VACUUM for housekeeping
    spark.sql(f"VACUUM {gold_table} RETAIN 168 HOURS")

    # COMMAND ----------

    audit_record = create_audit_record(
        pipeline_run_id=pipeline_run_id,
        source_name=source_name,
        entity_name="fct_headcount",
        layer="gold",
        load_type="incremental",
        status="SUCCESS",
        start_time=start_time,
        records_read=records_read,
        records_written=records_written,
    )
    log_success_and_update_watermark(spark, dbutils, audit_record, None, {})

except Exception as e:
    logger.error(f"Gold fct_headcount pipeline failed: {str(e)}")
    audit_record = create_audit_record(
        pipeline_run_id=pipeline_run_id,
        source_name=source_name,
        entity_name="fct_headcount",
        layer="gold",
        load_type="incremental",
        status="FAILED",
        start_time=start_time,
        error_message=str(e)[:4000],
    )
    log_failure(spark, audit_record, e)
    raise
