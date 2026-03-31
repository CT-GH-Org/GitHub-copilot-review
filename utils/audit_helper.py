# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Audit Helper
# MAGIC Functions for pipeline audit logging, watermark updates, and status tracking.

# COMMAND ----------

import json
from datetime import datetime, timezone
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, TimestampType, LongType

# COMMAND ----------

AUDIT_LOG_SCHEMA = StructType([
    StructField("pipeline_run_id", StringType(), False),
    StructField("source_name", StringType(), False),
    StructField("entity_name", StringType(), False),
    StructField("layer", StringType(), False),
    StructField("load_type", StringType(), False),
    StructField("status", StringType(), False),
    StructField("start_time", TimestampType(), False),
    StructField("end_time", TimestampType(), True),
    StructField("records_read", LongType(), True),
    StructField("records_written", LongType(), True),
    StructField("error_message", StringType(), True),
    StructField("target_entity", StringType(), True),
])

# COMMAND ----------

def write_audit_log(spark, audit_record):
    """Write a single audit log record to the audit table."""
    audit_df = spark.createDataFrame([audit_record], schema=AUDIT_LOG_SCHEMA)
    audit_df.write.format("delta").mode("append").saveAsTable("edl_audit.pipeline_run_log")

# COMMAND ----------

def create_audit_record(pipeline_run_id, source_name, entity_name, layer, load_type, status, start_time, end_time=None, records_read=None, records_written=None, error_message=None):
    """Create an audit record dictionary."""
    return {
        "pipeline_run_id": pipeline_run_id,
        "source_name": source_name,
        "entity_name": entity_name,
        "layer": layer,
        "load_type": load_type,
        "status": status,
        "start_time": start_time,
        "end_time": end_time,
        "records_read": records_read,
        "records_written": records_written,
        "error_message": error_message,
        "target_entity": "bronze",
    }

# COMMAND ----------

def log_success_and_update_watermark(spark, dbutils, audit_record, watermark_value, config):
    """Log success and update the watermark for incremental loads."""
    if config.get("load_type") == "incremental" and watermark_value is not None:
        spark.sql(
            f"UPDATE edl_audit.metadata_config "
            f"SET watermark_last_loaded_timestamp = '{watermark_value}' "
            f"WHERE source_name = '{config['source_name']}' AND entity_name = '{config['entity_name']}'"
        )

    audit_record["status"] = "SUCCESS"
    audit_record["end_time"] = datetime.now(timezone.utc)
    write_audit_log(spark, audit_record)

# COMMAND ----------

def log_failure(spark, audit_record, error):
    """Log a pipeline failure."""
    audit_record["status"] = "FAILED"
    audit_record["end_time"] = datetime.now(timezone.utc)
    audit_record["error_message"] = str(error)[:4000]
    write_audit_log(spark, audit_record)

# COMMAND ----------

def get_secret(dbutils, scope, key):
    """Retrieve a secret from Databricks secret scope."""
    return dbutils.secrets.get(scope=scope, key=key)

# COMMAND ----------

def retry_with_backoff(func, max_retries=3, initial_delay=1):
    """Retry a function with exponential backoff."""
    import time
    delay = initial_delay
    last_exception = None
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
    raise last_exception
