# Databricks Notebook Review Patterns

Domain-specific review patterns for Databricks Python notebooks in a medallion architecture data lakehouse.

---

## 1. Layer Architecture

### Bronze Layer (Landing → Bronze)
- Raw data only — NO transformations beyond adding audit columns
- **Append-only writes** — NO upserts, NO merge operations
- Must include metadata columns: source file name, load datetime, source creation time
- Delta format required
- Workspace: DA workspace

```python
# GOOD — append-only bronze write
df.write.format("delta").mode("append").saveAsTable(bronze_table)

# BAD — upsert in bronze
deltaTable.alias("target").merge(df.alias("source"), condition).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
```

### Silver Layer (Bronze → Silver)
- Validated and enriched data with schema enforcement
- SCD Type 2 implementation for slowly changing dimensions
- Primary key uniqueness checks and deduplication logic
- Delta format required
- Workspace: BU workspace
- **Silver layer MUST exist** — never skip Bronze → Gold directly

### Gold Layer (Silver → Gold)
- Refined, aggregated, business-ready data
- Optimized for query performance, denormalized where appropriate
- Aggregations, joins, and filtering must happen BEFORE write (not as views on raw data)
- Delta format required
- Workspace: BU workspace
- Incremental load preferred where entities support it

---

## 2. Audit Columns

### Bronze — Required columns (all three must be present):
| Column | Type | Description |
|---|---|---|
| `az_create_datetime` | TIMESTAMP | UTC timestamp when record was created |
| `az_update_datetime` | TIMESTAMP | UTC timestamp when record was last updated |
| `az_flag_dml_operation` | STRING | DML operation type (INSERT, UPDATE, DELETE) |

### Silver — Required columns (Bronze + SCD2):
| Column | Type | Description |
|---|---|---|
| `az_create_datetime` | TIMESTAMP | UTC timestamp |
| `az_update_datetime` | TIMESTAMP | UTC timestamp |
| `az_date_effective_from` | TIMESTAMP | SCD2 effective start |
| `az_date_effective_thru` | TIMESTAMP | SCD2 effective end |
| `az_<table_name>_sk` | BIGINT | Surrogate key |

### Gold — Required columns:
| Column | Type | Description |
|---|---|---|
| `az_create_datetime` | TIMESTAMP | UTC timestamp |
| `az_update_datetime` | TIMESTAMP | UTC timestamp |
| `az_snapshot_date` | DATE | Snapshot date for the record |

### Forbidden audit columns — Do NOT use these separately:
- `az_primary_key_hash`, `az_scd1_key_hash`, `az_scd2_key_hash`, `az_measure_hash`
- Use single `az_hash` column instead

### 3.19 az_create_datetime Semantic Correctness (F29 - Critical)
az_create_datetime must ONLY be set during initial INSERT. On MERGE/UPDATE, only az_update_datetime should change. Do NOT overwrite az_create_datetime in whenMatchedUpdate.

```python
# GOOD — az_create_datetime preserved on update
delta_table.alias("target").merge(
    source_df.alias("source"),
    "target.id = source.id"
).whenMatchedUpdate(set={
    "az_update_datetime": "current_timestamp()",  # Only update timestamp changes
    # az_create_datetime NOT included — preserved from original insert
}).whenNotMatchedInsert(values={
    "az_create_datetime": "current_timestamp()",  # Set only on first insert
    "az_update_datetime": "current_timestamp()",
    # ... other columns
}).execute()

# BAD — az_create_datetime overwritten on every merge
silver_df = (
    transformed_df
    .withColumn("az_create_datetime", F.current_timestamp())  # Overwrites on re-run!
    .withColumn("az_update_datetime", F.current_timestamp())
)
# Then used in whenMatchedUpdateAll() — both timestamps reset
```
- Severity: Critical — overwrites original creation timestamp, destroying audit trail

---

## 3. Feedback-Derived Patterns

These patterns were repeatedly flagged across multiple review cycles:

### 3.1 Remove Commented-Out Code
- Commented-out code blocks should be removed, not left in the notebook
- Severity: Medium

### 3.2 Use Metadata Config for write_mode and source_where_clause
- `write_mode` must come from `metadata_config_silver` table, not hardcoded
- `source_where_clause` must come from metadata config, not hardcoded in the notebook

```python
# BAD
write_mode = "overwrite"
where_clause = "status = 'active'"

# GOOD
write_mode = config["write_mode"]
where_clause = config["source_where_clause"]
```

### 3.3 Avoid Duplicate Deletion with Upsert
- When `write_mode` is `"upsert"` or `"merge"`, the framework handles dedup
- Do NOT add `drop_duplicates()` before a merge/upsert operation
- `drop_duplicates()` is only appropriate before an `overwrite` write

### 3.4 Validate WHERE Clauses for NULL and Empty String
- When applying a `source_where_clause` from config, check for both None and empty/whitespace

```python
# GOOD
if source_where_clause and source_where_clause.strip():
    df = df.filter(source_where_clause)

# BAD — empty string passes through
if source_where_clause is not None:
    df = df.filter(source_where_clause)
```

### 3.5 Handle Missing Columns Gracefully
- When transforming data, check if expected columns exist before operating on them
- Use `has_column()` checks or try-except for optional columns

### 3.6 Data Type Casting from column_config
- Column data types should come from a `column_config` or schema definition, not hardcoded casts
- Cast operations should be driven by metadata, not inline type literals

### 3.7 Selective drop_duplicates
- When deduplication is needed, specify the subset of columns explicitly
- Do not call `drop_duplicates()` without arguments (deduplicates on all columns, which may not be the intent)

```python
# GOOD — explicit columns
df = df.dropDuplicates(["primary_key_col1", "primary_key_col2"])

# BAD — all columns
df = df.dropDuplicates()
```

### 3.8 Unconditional Column Recast
- Avoid unconditionally recasting columns that may already be the correct type
- Use schema comparison before applying cast operations

### 3.9 Raise Exceptions for Invalid load_type
- If `load_type` is not `"full"` or `"incremental"`, raise a `ValueError` — do not silently default

```python
# GOOD
if load_type not in ["full", "incremental"]:
    raise ValueError(f"Invalid load_type: {load_type}")

# BAD — silently defaulting
if load_type not in ["full", "incremental"]:
    load_type = "full"
```

### 3.10 Convert load_type to Lowercase
- Always normalize `load_type` to lowercase before comparison to handle case variations

```python
load_type = config["load_type"].strip().lower()
```

### 3.11 No Test Entities in Production Code
- Remove test entity names, test source names, and test configurations from production notebooks
- Severity: Major

### 3.12 Use Standardized Medallion Pipeline Class
- When the project provides a standardized pipeline class (e.g., `MedallionPipeline`, `BronzePipeline`), use it instead of writing custom pipeline logic
- Custom implementations risk missing standard audit columns, watermark handling, and error patterns

### 3.13 column_recast Must NOT Have source_name Conditionals (F19 - Critical)
The column_recast/column_casting function must be unconditional — no hardcoded source_name checks. Must work for ANY source without code changes. This was the #1 most repeated feedback across 5+ source reviews.

```python
# GOOD — unconditional, driven by column_config metadata
def column_recast(df, column_config):
    """Apply data type casting based on column_config table entries."""
    for col_entry in column_config:
        col_name = col_entry["column_name"]
        target_type = col_entry["column_data_type"]
        if col_name in df.columns:
            df = df.withColumn(col_name, F.col(col_name).cast(target_type))
    return df

# BAD — hardcoded source_name conditional (requires code change per source)
def column_recast(df, source_name, column_config):
    if source_name.upper() == "LPSS_RLA":
        # LPSS-specific casting
        ...
    elif source_name.upper() == "ADMS_RLA":
        # ADMS-specific casting
        ...
    return df
```
- Severity: Critical — code changes required when source_name changes in metadata tables

### 3.14 Decimal Scale=0 for NUMBER(N,0) Source Types (F20 - Critical)
When Oracle/source type is NUMBER(N,0), the DecimalType must have scale=0, not default DecimalType(38,18). Precision and scale must come from column_config table. For FLOAT source types, use DecimalType(38,18).

```python
# GOOD — precision and scale from column_config
def get_spark_type(source_type):
    """Convert source data type to Spark type using config-driven precision/scale."""
    if source_type.startswith("NUMBER"):
        # Parse NUMBER(precision, scale) from source_type string
        match = re.match(r'NUMBER\((\d+),\s*(\d+)\)', source_type)
        if match:
            precision, scale = int(match.group(1)), int(match.group(2))
            return DecimalType(precision, scale)
        return DecimalType(38, 0)  # NUMBER without scale defaults to 0
    elif source_type == "FLOAT":
        return DecimalType(38, 18)
    ...

# BAD — default DecimalType for all numeric types
def get_spark_type(source_type):
    if "NUMBER" in source_type or "DECIMAL" in source_type:
        return DecimalType(38, 18)  # Wrong: scale should be 0 for NUMBER(N,0)
```
- Severity: Critical — incorrect scale causes data precision loss in Bronze/Silver tables

### 3.15 Soft Delete Support (az_flag_is_delete) (F24 - Critical)
When records exist in the target but not in the source during SCD1/merge, they must be soft-deleted by setting az_flag_is_delete=True and az_flag_current_record=False. Hard deletes are not acceptable.

```python
# GOOD — soft delete via whenNotMatchedBySource
delta_table.alias("target").merge(
    source_df.alias("source"),
    "target.employee_id = source.employee_id"
).whenMatchedUpdateAll(
).whenNotMatchedInsertAll(
).whenNotMatchedBySourceUpdate(
    set={
        "az_flag_is_delete": "true",
        "az_flag_current_record": "false",
        "az_update_datetime": "current_timestamp()"
    }
).execute()

# BAD — no soft delete handling; deleted source records remain active in target
delta_table.alias("target").merge(
    source_df.alias("source"),
    "target.employee_id = source.employee_id"
).whenMatchedUpdateAll(
).whenNotMatchedInsertAll(
).execute()
# Records deleted at source remain as active records in target forever
```
- Severity: Critical — stale/deleted records persist as active in target tables

### 3.16 Hash Auto-Generation for Tables Without PK (F25 - Critical)
When target_primary_key is missing/empty in metadata config, auto-create az_hash from all non-audit business columns. This hash serves as a synthetic key for merge operations.

```python
# GOOD — auto-generate hash when PK is missing
def get_merge_key(df, primary_key_columns, audit_column_prefixes=("az_",)):
    """Get merge key columns; auto-generate hash if PK is missing."""
    if primary_key_columns:
        return primary_key_columns
    # Auto-generate hash from all non-audit business columns
    business_cols = [c for c in df.columns if not c.startswith(audit_column_prefixes)]
    df = df.withColumn("az_hash", F.md5(F.concat_ws("|", *[F.col(c).cast("string") for c in sorted(business_cols)])))
    return ["az_hash"]

# BAD — fail or skip merge when PK is missing
if not primary_key_columns:
    raise ValueError("No primary key defined")  # Fails instead of auto-generating
# OR
if not primary_key_columns:
    df.write.mode("append")  # Skips merge entirely, creates duplicates on re-run
```
- Severity: Critical — tables without PK either fail or create duplicates

### 3.17 Partial Success Tracking for File-Based Sources (F27 - Critical)
File-based processing must NOT mark entire batch as SUCCESS when some files failed. Use granular status tracking per file.

```python
# GOOD — granular per-file status tracking
file_statuses = []
for file_path in files_to_process:
    try:
        process_file(file_path)
        file_statuses.append({"file": file_path, "status": "SUCCESS"})
    except SchemaValidationError:
        file_statuses.append({"file": file_path, "status": "FORMAT_VALIDATION_FAILED"})
    except Exception as e:
        file_statuses.append({"file": file_path, "status": "FAILED", "error": str(e)})

# Update tracker table with individual file statuses
update_file_tracker(spark, file_statuses)

# Set overall status based on individual results
if all(s["status"] == "SUCCESS" for s in file_statuses):
    overall_status = "SUCCESS"
elif any(s["status"] == "SUCCESS" for s in file_statuses):
    overall_status = "PARTIAL_SUCCESS"
else:
    overall_status = "FAILED"

# BAD — mark entire batch as SUCCESS even when some files failed
try:
    for file_path in files_to_process:
        process_file(file_path)
    status = "SUCCESS"  # All-or-nothing: one failure = entire batch fails
except Exception:
    status = "FAILED"
```
- Severity: Critical — masks individual file failures and prevents targeted recovery

### 3.18 Dynamic Schema Generation from Metadata (F36 - Major)
For API and file sources, support dynamic schema generation via column_config with flag (is_dbx_auto_schema_column). When flag='Y', auto-generate schema from metadata.

```python
# GOOD — dynamic schema from column_config
def build_schema_from_config(column_config_entries):
    """Build StructType schema dynamically from column_config metadata."""
    type_mapping = {
        "STRING": StringType(), "INTEGER": IntegerType(), "LONG": LongType(),
        "DOUBLE": DoubleType(), "BOOLEAN": BooleanType(), "DATE": DateType(),
        "TIMESTAMP": TimestampType(),
    }
    fields = []
    for entry in column_config_entries:
        col_name = entry["column_name"]
        col_type = entry["column_data_type"].upper()
        if col_type.startswith("DECIMAL"):
            precision, scale = parse_decimal(col_type)
            spark_type = DecimalType(precision, scale)
        else:
            spark_type = type_mapping.get(col_type, StringType())
        fields.append(StructField(col_name, spark_type, True))
    return StructType(fields)

# In notebook:
if config.get("is_dbx_auto_schema_column") == "Y":
    schema = build_schema_from_config(column_config)
    df = spark.read.schema(schema).format(file_format).load(path)
else:
    df = spark.read.format(file_format).load(path)  # Auto-infer

# BAD — hardcoded schema class per source
class SalesforceAccountSchema:
    schema = StructType([
        StructField("Id", StringType()),
        StructField("Name", StringType()),
        # ... hardcoded per object
    ])
```
- Severity: Major — hardcoded schemas require code changes for every new source object

---

## 4. Data Storage

- Use **Unity Catalog managed external volumes**, NOT DBFS (`/mnt/`, `dbfs:/`)
- Delta format for all layers
- **No manual table optimization** — do not use `OPTIMIZE`, `VACUUM`, or `ANALYZE` commands; rely on Databricks automated predictive optimization
- **Partitioning rules:** Only for tables >1TB, low-cardinality columns only, each partition >1GB

### Bronze Table Retention/Pruning + Archival (F30 - Major)
Bronze tables must implement retention policies. After the retention period, records must be pruned and archived to archive tables.

```python
# GOOD — retention-aware bronze management
# Archive old records before pruning
archive_cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
old_records = spark.table(bronze_table).filter(
    F.col("az_create_datetime") < archive_cutoff
)
old_records.write.format("delta").mode("append").saveAsTable(archive_table)

# Prune from bronze after successful archive
spark.sql(f"""
    DELETE FROM {bronze_table}
    WHERE az_create_datetime < '{archive_cutoff.isoformat()}'
""")

# BAD — bronze tables grow unbounded with no retention
# No pruning, no archival — table size grows forever
df.write.format("delta").mode("append").saveAsTable(bronze_table)
```
- Severity: Major — unbounded table growth increases storage costs and degrades query performance

### Gold Layer in Separate Storage Container (F32 - Medium)
Gold tables can be stored in a separate storage container to avoid cloud resource limits on concurrent data requests from reporting/ML workloads.

```python
# GOOD — gold layer in dedicated container
gold_table = f"{catalog}.gold.dim_employee"
# Gold schema/catalog points to separate storage container for isolation

# BAD — all layers in same container competing for throughput
# bronze, silver, and gold all in same storage account/container
```
- Severity: Medium — shared containers create resource contention for high-volume gold access

```python
# BAD — DBFS paths
path = "/mnt/landing/source/"
path = "dbfs:/mnt/bronze/"

# GOOD — Unity Catalog
spark.read.table("catalog.schema.customer")
path = "abfss://container@storage.dfs.core.windows.net/..."
```

---

## 5. Exception Handling

- **Granular try-catch blocks** — separate try blocks for config loading, data reading, transformations, and writes
- All failures must be logged to the audit table with: `source_type`, `cluster_id`, `job_id`, `run_id`, `execution_start_time`, `execution_end_time`, `error_details`
- Caller and callee must handle errors consistently — if callee raises, caller must catch and log
- **Raise exceptions for invalid values** — never silently default

```python
# GOOD — granular error handling
try:
    config = load_config(source_name)
except Exception as e:
    log_audit_failure("config_load", e)
    raise

try:
    df = read_source_data(config)
except Exception as e:
    log_audit_failure("data_read", e)
    raise
```

---

## 6. Workspace Boundaries

### DA Workspace (Source → Landing, Landing → Bronze):
- May use DA workspace Azure resources (storage accounts, key vaults, service principals)
- Source connections and landing zone writes

### BU Workspace (Bronze → Silver, Silver → Gold):
- Must NOT reference DA workspace resources
- Must NOT use DA storage accounts, key vaults, or service principals
- Only access Bronze/Silver/Gold layers in BU workspace

---

## 7. Additional Checks

- **Version History:** Each notebook must have a version history header at the top
- **Comments:** High-level comment for each code cell/block explaining purpose
- **Schema Definition:** `required=True` should NOT be set for nullable fields
- **Common Functions:** Must be in shared utils module, not copy-pasted across notebooks
- **Constants:** Must be in UPPERCASE, ideally in a constants module
- **UTC Timezone:** Use `current_timestamp()` (UTC by default in Databricks), never `datetime.now()`
- **Datetime over Date:** Use `TimestampType` when time component is available, not `DateType`

### Unit Tests Required for Pipeline Classes (F22 - Critical)
Medallion pipeline classes and critical transformation functions must have unit tests covering: full load, incremental load, SCD1, SCD2, append, overwrite, and soft delete. Test results must be submitted as evidence.

```python
# Required test scenarios for medallion pipeline classes:
# 1. Full load — overwrite mode, verify complete data replacement
# 2. Incremental load — append mode, verify only new records added
# 3. SCD Type 1 — verify in-place update of changed records
# 4. SCD Type 2 — verify old record expiry + new record insert
# 5. Soft delete — verify az_flag_is_delete set for missing source records
# 6. Idempotency — verify re-run produces identical results
# 7. Empty source — verify graceful handling of zero records

# Without passing test results, custom pipeline classes should NOT be accepted
```
- Severity: Critical — untested pipeline classes risk uncaught bugs in production

---

## 8. Best Recommended Practices

### 8.1 SCD Type 2 Pattern
- Use Delta Lake `MERGE` for atomic SCD2 updates in Silver layer
- Match on business key; when a tracked column changes, expire the old row and insert a new active row in a single MERGE statement
- Never implement SCD2 as separate UPDATE + INSERT statements — this risks partial failures leaving inconsistent state

```python
# GOOD — single atomic MERGE for SCD2
from delta.tables import DeltaTable

target = DeltaTable.forName(spark, "catalog.silver.customer")

target.alias("t").merge(
    source_df.alias("s"),
    "t.customer_id = s.customer_id AND t.az_date_effective_thru IS NULL"
).whenMatchedUpdate(
    condition="t.customer_name <> s.customer_name OR t.customer_address <> s.customer_address",
    set={
        "az_date_effective_thru": "current_timestamp()",
        "az_update_datetime": "current_timestamp()"
    }
).whenNotMatchedInsert(
    values={
        "customer_id": "s.customer_id",
        "customer_name": "s.customer_name",
        "customer_address": "s.customer_address",
        "az_date_effective_from": "current_timestamp()",
        "az_date_effective_thru": "NULL",
        "az_create_datetime": "current_timestamp()",
        "az_update_datetime": "current_timestamp()"
    }
).execute()

# After expiring old rows, insert new active versions for changed records
# (handle in second merge or unionAll + append depending on framework pattern)

# BAD — separate UPDATE then INSERT (non-atomic)
spark.sql("UPDATE silver.customer SET az_date_effective_thru = current_timestamp() WHERE ...")
spark.sql("INSERT INTO silver.customer SELECT ... FROM source WHERE ...")
```

### 8.2 Schema Evolution
- Use `mergeSchema` option **per-operation**, not as a global Spark config — global setting risks unintended schema drift
- Validate incoming schema against expected schema before writing — log any new or dropped columns
- Log schema changes to an audit table for lineage tracking

```python
# GOOD — per-operation mergeSchema
df.write.format("delta") \
    .option("mergeSchema", "true") \
    .mode("append") \
    .saveAsTable("catalog.bronze.orders")

# BAD — global config affects all writes in the session
spark.conf.set("spark.databricks.delta.schema.autoMerge.enabled", "true")
df.write.format("delta").mode("append").saveAsTable("catalog.bronze.orders")
```

```python
# GOOD — validate schema before write
expected_cols = set(spark.table(target_table).columns)
incoming_cols = set(df.columns)
new_cols = incoming_cols - expected_cols
dropped_cols = expected_cols - incoming_cols

if new_cols:
    log_schema_change(target_table, "added", new_cols)
if dropped_cols:
    log_schema_change(target_table, "removed", dropped_cols)
```

### 8.3 Performance Optimization
- Prefer **liquid clustering** over Z-ordering for new tables — liquid clustering is self-tuning and does not require periodic OPTIMIZE
- Use **broadcast joins** for small dimension tables (<100 MB) joined to large fact tables
- Avoid `collect()` on large DataFrames — use aggregations or `limit()` before collecting to the driver
- Prefer **DataFrame API** over `spark.sql()` for better compile-time validation and optimization

```python
# GOOD — broadcast join for small dimension
from pyspark.sql.functions import broadcast

result = fact_df.join(broadcast(dim_df), "dim_key")

# BAD — no broadcast hint, shuffle join on small table
result = fact_df.join(dim_df, "dim_key")
```

```python
# GOOD — aggregate then collect
max_watermark = df.agg({"az_create_datetime": "max"}).collect()[0][0]

# BAD — collect entire DataFrame to driver
all_rows = df.collect()  # OutOfMemoryError risk
max_watermark = max(row["az_create_datetime"] for row in all_rows)
```

```python
# GOOD — DataFrame API with compile-time checks
df = spark.table("catalog.bronze.orders") \
    .filter(col("load_type") == "incremental") \
    .select("order_id", "customer_id", "order_date")

# LESS PREFERRED — spark.sql string (no compile-time validation)
df = spark.sql("""
    SELECT order_id, customer_id, order_date
    FROM catalog.bronze.orders
    WHERE load_type = 'incremental'
""")
```

### 8.4 Data Quality Validation Framework
- Implement reusable DQ checks: null checks, uniqueness checks, referential integrity, range validation
- Store DQ rules in a central config (table or YAML), not hardcoded per notebook
- Log all DQ violations to a dedicated `dq_results` table with severity, column, rule, and failed record count
- DQ failures should NOT throw exceptions by default — log and flag, let the pipeline decide severity

```python
# GOOD — reusable DQ check functions
def check_nulls(df, columns, source_name, entity_name):
    """Check for null values in required columns."""
    results = []
    for col_name in columns:
        null_count = df.filter(col(col_name).isNull()).count()
        if null_count > 0:
            results.append({
                "source_name": source_name,
                "entity_name": entity_name,
                "rule": "not_null",
                "column": col_name,
                "failed_count": null_count,
                "check_datetime": datetime.utcnow()
            })
    return results

def check_uniqueness(df, key_columns, source_name, entity_name):
    """Check for duplicate records on key columns."""
    dup_count = df.groupBy(key_columns).count().filter("count > 1").count()
    if dup_count > 0:
        return [{"rule": "unique", "columns": key_columns, "failed_count": dup_count}]
    return []

# BAD — inline hardcoded checks per notebook
if df.filter(col("customer_id").isNull()).count() > 0:
    raise Exception("Null customer_id found!")
```

### 8.5 Change Data Feed (CDF)
- Enable **Change Data Feed** on Silver tables that feed downstream Gold aggregations
- Use `readChangeFeed` for incremental Gold processing instead of re-reading the entire Silver table
- CDF provides `_change_type`, `_commit_version`, and `_commit_timestamp` columns for efficient incremental consumption

```python
# GOOD — enable CDF on Silver table
spark.sql("""
    ALTER TABLE catalog.silver.orders
    SET TBLPROPERTIES (delta.enableChangeDataFeed = true)
""")

# GOOD — read changes incrementally in Gold notebook
changes_df = spark.read.format("delta") \
    .option("readChangeFeed", "true") \
    .option("startingVersion", last_processed_version) \
    .table("catalog.silver.orders")

# BAD — re-read entire Silver table every Gold run
silver_df = spark.table("catalog.silver.orders")
gold_df = silver_df.groupBy("region").agg(sum("amount"))
```

### 8.6 Auto Loader for Landing Ingestion
- Use **Auto Loader** (`cloudFiles` format) for landing-to-bronze ingestion — handles file discovery, schema inference, and exactly-once processing
- Prefer **file notification mode** over directory listing for high-volume landing zones (reduces API calls)
- Auto Loader is inherently idempotent — files are tracked in a checkpoint and never reprocessed

```python
# GOOD — Auto Loader with file notification
df = spark.readStream.format("cloudFiles") \
    .option("cloudFiles.format", "parquet") \
    .option("cloudFiles.useNotifications", "true") \
    .option("cloudFiles.schemaLocation", checkpoint_path) \
    .load(landing_path)

df.writeStream.format("delta") \
    .option("checkpointLocation", checkpoint_path) \
    .trigger(availableNow=True) \
    .toTable("catalog.bronze.orders")

# BAD — manual file listing and tracking
files = dbutils.fs.ls(landing_path)
for f in files:
    df = spark.read.parquet(f.path)
    df.write.mode("append").saveAsTable("catalog.bronze.orders")
```

### 8.7 Idempotent Notebook Design
- Every notebook must be **safe to re-run** without producing duplicate data or inconsistent state
- Use `MERGE` for upserts, not `INSERT` — `INSERT` on re-run creates duplicates
- Update state (watermarks, audit logs) **only after** successful data write, never before
- Avoid side effects (notifications, external API calls) before the data write commits

```python
# GOOD — idempotent pattern
try:
    # 1. Read source data
    source_df = read_bronze(config)

    # 2. Transform
    transformed_df = apply_transforms(source_df)

    # 3. Write (MERGE is idempotent)
    merge_to_silver(transformed_df, target_table, merge_keys)

    # 4. Update state AFTER successful write
    update_watermark(config["source_id"], new_watermark)
    log_audit(status="success", rows=transformed_df.count())

except Exception as e:
    # State NOT updated — safe to retry
    log_audit(status="failed", error=str(e))
    raise

# BAD — non-idempotent pattern
update_watermark(config["source_id"], new_watermark)  # Updated before write!
df.write.mode("append").saveAsTable(target_table)      # Append creates dupes on re-run
send_notification("Load complete")                      # Side effect before commit
```
