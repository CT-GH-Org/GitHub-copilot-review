# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # ERP HR Constants
# MAGIC Central constants for the ERP HR ingestion pipeline.

# COMMAND ----------

# Source system identifiers
SOURCE_NAME = "erp_hr"
SOURCE_SYSTEM = "ERP_HUMAN_RESOURCES"

# Load type constants
LOAD_TYPE_FULL = "full"
LOAD_TYPE_INCREMENTAL = "incremental"

# Load method constants
LOAD_METHOD_AUTOLOADER = "autoloader"
LOAD_METHOD_COPY_INTO = "copy_into"
LOAD_METHOD_JDBC = "jdbc"

# Layer identifiers
LAYER_LANDING = "landing"
LAYER_BRONZE = "bronze"
LAYER_SILVER = "silver"
LAYER_GOLD = "gold"

# COMMAND ----------

# Audit table schema
AUDIT_TABLE_SCHEMA = "edl_audit"
AUDIT_TABLE_NAME = "pipeline_run_log"
DQ_RESULTS_TABLE = "dq_results"

# COMMAND ----------

timezone_str = 'America/Denver'
maxRetryCount = 3

dev_catalog_name = "dev_edl_catalog"
SQL_SERVER_HOST = "edl-prod-sqlserver.database.windows.net"

# COMMAND ----------

# # Old constants — kept for reference
# OLD_LANDING_PATH = "/mnt/raw/erp_hr/"
# OLD_BRONZE_SCHEMA = "raw_erp"
# LEGACY_SOURCE_ID = 42

# COMMAND ----------

# Watermark defaults
DEFAULT_WATERMARK_FORMAT = "yyyy-MM-dd HH:mm:ss"
WATERMARK_COLUMN_PRIMARY = "modified_datetime"
WATERMARK_COLUMN_SECONDARY = "created_datetime"
