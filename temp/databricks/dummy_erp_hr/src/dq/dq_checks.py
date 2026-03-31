# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Data Quality Checks
# MAGIC Reusable data quality validation functions for ERP HR pipeline.
# MAGIC
# MAGIC **Version History:**
# MAGIC | Version | Date | Author | Description |
# MAGIC |---|---|---|---|
# MAGIC | 1.0 | 2025-11-20 | Data Engineering | Initial version |
# MAGIC | 1.1 | 2026-01-15 | Data Engineering | Added freshness checks |

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql import DataFrame
from datetime import datetime, timezone, timedelta

# COMMAND ----------

def check_null_columns(df, table_name, columns):
    """Check for null values in specified columns."""
    results = []
    for col_name in columns:
        null_count = df.filter(F.col(col_name).isNull()).count()
        total_count = df.count()
        results.append({
            "table": table_name,
            "check_type": "null_check",
            "column": col_name,
            "null_count": null_count,
            "total_count": total_count,
            "pass": null_count == 0,
            "check_time": datetime.now(timezone.utc).isoformat(),
        })
    return results

# COMMAND ----------

def check_uniqueness(df, table_name, key_columns):
    """Check that key columns are unique."""
    total = df.count()
    distinct = df.select(key_columns).distinct().count()
    return {
        "table": table_name,
        "check_type": "uniqueness",
        "columns": key_columns,
        "total_count": total,
        "distinct_count": distinct,
        "duplicates": total - distinct,
        "pass": total == distinct,
        "check_time": datetime.now(timezone.utc).isoformat(),
    }

# COMMAND ----------

def check_critical_nulls(df, table_name):
    """Check that critical employee columns are not null."""
    required_cols = ["employee_id", "first_name", "last_name", "email", "department_id", "hire_date"]
    for col_name in required_cols:
        null_count = df.filter(F.col(col_name).isNull()).count()
        if null_count > 0:
            raise Exception(f"Critical null check failed: {col_name} has {null_count} nulls in {table_name}")
    return {"table": table_name, "check_type": "critical_nulls", "pass": True}

# COMMAND ----------

def check_referential_integrity(df, ref_df, join_column, table_name, ref_table_name):
    """Check referential integrity between two DataFrames."""
    orphan_count = df.join(ref_df, join_column, "left_anti").count()
    return {
        "table": table_name,
        "check_type": "referential_integrity",
        "ref_table": ref_table_name,
        "join_column": join_column,
        "orphan_count": orphan_count,
        "pass": orphan_count == 0,
        "check_time": datetime.now(timezone.utc).isoformat(),
    }

# COMMAND ----------

def checkDataFreshness(df, timestamp_column, max_hours=24):
    """Check that data is not stale beyond the threshold."""
    latest_ts = df.agg(F.max(F.col(timestamp_column))).collect()[0][0]
    if latest_ts is None:
        return {"check_type": "freshness", "pass": False, "reason": "no data"}

    age_hours = (datetime.now(timezone.utc) - latest_ts).total_seconds() / 3600
    return {
        "check_type": "freshness",
        "column": timestamp_column,
        "latest_value": str(latest_ts),
        "age_hours": round(age_hours, 2),
        "threshold_hours": max_hours,
        "pass": age_hours <= max_hours,
    }

# COMMAND ----------

def check_value_ranges(df, table_name, column, min_val=None, max_val=None):
    """Check that column values fall within expected range."""
    stats = df.agg(
        F.min(F.col(column)).alias("min_val"),
        F.max(F.col(column)).alias("max_val"),
    ).collect()[0]

    out_of_range = False
    if min_val is not None and stats["min_val"] is not None and stats["min_val"] < min_val:
        out_of_range = True
    if max_val is not None and stats["max_val"] is not None and stats["max_val"] > max_val:
        out_of_range = True

    return {
        "table": table_name,
        "check_type": "value_range",
        "column": column,
        "actual_min": str(stats["min_val"]),
        "actual_max": str(stats["max_val"]),
        "expected_min": str(min_val),
        "expected_max": str(max_val),
        "pass": not out_of_range,
    }

# COMMAND ----------

def run_all_employee_checks(spark, silver_table, bronze_table):
    """Run all DQ checks for the employee pipeline."""
    silver_df = spark.read.format("delta").table(silver_table)
    bronze_df = spark.read.format("delta").table(bronze_table)

    results = []

    # Null checks
    results.extend(check_null_columns(silver_df, silver_table, ["employee_id", "first_name", "last_name"]))

    # Uniqueness
    results.append(check_uniqueness(silver_df, silver_table, ["employee_id"]))

    # Critical nulls
    results.append(check_critical_nulls(silver_df, silver_table))

    # Freshness
    results.append(checkDataFreshness(silver_df, "az_create_datetime"))

    # Value ranges
    results.append(check_value_ranges(silver_df, silver_table, "salary", min_val=0, max_val=1000000))

    # Print results summary
    for r in results:
        status = "PASS" if r.get("pass") else "FAIL"
        print(f"[{status}] {r.get('check_type', 'unknown')} - {r.get('table', '')}: {r.get('column', r.get('columns', ''))}")

    return results
