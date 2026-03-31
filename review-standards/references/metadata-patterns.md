# Metadata Framework Review Patterns

Domain-specific review patterns for metadata control tables, watermark handling, audit logging, and notifications in a medallion architecture data lakehouse.

---

## 1. Control Table Required Columns

### metadata_config (Landing & Bronze):
```sql
-- Identity & Classification
source_id                          -- INT IDENTITY, primary key
source_name                        -- NVARCHAR, identifies the source system
source_entity_name                 -- NVARCHAR, specific entity/table name
source_entity_type                 -- NVARCHAR, type classification
load_type                          -- NVARCHAR, 'full' or 'incremental' (NOT 'mode')
is_active                          -- BIT, whether this config is active
is_initial_load_required           -- BIT, use this NOT Get Metadata activity

-- Watermark Columns
watermark_column                   -- NVARCHAR, column name for incremental (NULL when N/A)
watermark_column_format            -- NVARCHAR, format of watermark value
watermark_type                     -- NVARCHAR, 'DATETIME' or 'BIGINT' (drives type-based switch logic)
watermark_last_loaded_timestamp    -- DATETIME2, last loaded timestamp watermark
watermark_last_loaded_bigint       -- BIGINT, last loaded integer watermark
watermark_column_secondary         -- NVARCHAR, secondary watermark column
watermark_column_secondary_format  -- NVARCHAR, secondary watermark format

-- Landing Configuration
landing_partition_column           -- NVARCHAR, partition column for landing
landing_container_name             -- NVARCHAR, ADLS container
landing_folder_path                -- NVARCHAR, path within container
landing_last_modified_date         -- DATETIME2, last modified tracking

-- Bronze Configuration
bronze_catalog_name                -- NVARCHAR, Unity Catalog name
bronze_schema_name                 -- NVARCHAR, schema name
bronze_table_name                  -- NVARCHAR, table name
bronze_last_loaded_timestamp       -- DATETIME2, last bronze load time

-- Scheduling
execution_frequency                -- NVARCHAR, 'Daily', 'Hourly', 'Manual' (scheduling metadata)

-- Source Configuration
source_database_name               -- NVARCHAR, source DB
source_schema_name                 -- NVARCHAR, source schema
source_catalog_name                -- NVARCHAR, source Unity Catalog (separate column)

-- Notebook Path
notebook_path                      -- NVARCHAR, parameterized notebook path

-- Audit
az_create_datetime                 -- DATETIME2, row creation time (UTC)
az_update_datetime                 -- DATETIME2, row update time (UTC)
```

### metadata_config_api (Landing & Bronze for API sources):
All standard `metadata_config` columns PLUS:
```sql
api_endpoint_template              -- NVARCHAR, parameterized URL template
api_authentication_type            -- NVARCHAR, OAuth2/API Key/etc.
api_pagination_type                -- NVARCHAR, offset/cursor/next-link
api_page_size                      -- INT, records per page
```

### metadata_config_silver:
```sql
write_mode                         -- NVARCHAR, 'overwrite' or 'merge'
silver_catalog_name                -- NVARCHAR, Unity Catalog
silver_schema_name                 -- NVARCHAR, schema
silver_table_name                  -- NVARCHAR, table
source_id                          -- INT, FK to metadata_config
```

### gold_entity_config:
```sql
gold_folder_path                   -- NVARCHAR, output path for gold (NOT hardcoded)
gold_catalog_name                  -- NVARCHAR, Unity Catalog
gold_schema_name                   -- NVARCHAR, schema
gold_table_name                    -- NVARCHAR, table
```

### General Rules:
- Source and destination Unity Catalog names in **separate columns** (not concatenated)
- Landing and Bronze share the same control table (`metadata_config`)
- Silver and Gold can use separate control tables
- API sources use a separate control table (`metadata_config_api`)
- `environment_config` table for environment-specific values (NOT hardcoded CASE statements)

---

## 2. Critical Column Name Checks

Flag wrong column names — these are frequently used incorrectly:

| Correct Name | Wrong Names to Flag |
|---|---|
| `watermark_column` | `incremental_parameter_name`, `incremental_column`, `wm_column` |
| `load_type` | `mode`, `processing_mode`, `load_mode` |
| `watermark_last_loaded_timestamp` | `last_watermark`, `wm_timestamp`, `last_loaded_ts` |
| `is_initial_load_required` | `initial_load`, `is_first_load`, `first_load_flag` |
| `source_name` (for filtering) | `environment`, `env`, `env_name` |
| `write_mode` (in silver config) | `mode`, `merge_type`, `write_type` |
| `watermark_column_format` | `wm_format`, `watermark_format` |
| `landing_partition_column` | `partition_column`, `partition_col` |
| `source_entity_type` | `entity_type`, `source_type` |
| `watermark_type` | `wm_type`, `watermark_data_type`, `wm_data_type` |

---

## 3. Watermark Handling

### Type Consistency:
- If `watermark_column` is a TIMESTAMP column, use `watermark_last_loaded_timestamp`
- If `watermark_column` is a BIGINT column, use `watermark_last_loaded_bigint`
- Type mismatches are a critical error

### Use source_id for Updates:
```sql
-- GOOD — unambiguous
UPDATE metadata_config
SET watermark_last_loaded_timestamp = @Value
WHERE source_id = @SourceID

-- BAD — potentially ambiguous
UPDATE metadata_config
SET watermark_last_loaded_timestamp = @Value
WHERE source_name = @SourceName AND source_entity_name = @EntityName
```

### NULL for Non-Applicable:
```sql
-- GOOD — actual NULL when watermark is not applicable
INSERT INTO metadata_config (source_name, watermark_column, load_type)
VALUES ('source_a', NULL, 'full')

-- BAD — placeholder values
VALUES ('source_a', 'N/A', 'full')
VALUES ('source_a', 'none', 'full')
VALUES ('source_a', '', 'full')
```

### Update After Success Only:
```python
# GOOD — update watermark ONLY after pipeline succeeds
try:
    load_bronze(config)
    update_watermark(source_id, new_watermark)  # after success
except Exception:
    # watermark NOT updated — can reprocess on retry
    raise

# BAD — watermark updated before confirming success
update_watermark(source_id, new_watermark)
load_bronze(config)  # if this fails, watermark already advanced
```

### Silver Watermark on az_create_datetime:
```python
# GOOD — silver watermark based on az_create_datetime
silver_watermark = bronze_df.agg(max("az_create_datetime")).collect()[0][0]

# BAD — silver watermark based on landing ingestion time
silver_watermark = landing_df.agg(max("ingestion_time")).collect()[0][0]
```

### Failure Recovery:
- Watermark-based recovery must allow reprocessing of missed data
- Next run must pick up from last successful watermark
- No data permanently skipped due to watermark advancement past failures

---

## 4. Feedback-Derived Patterns

### 4.1 Check for Duplicate Entries
- Control tables should not have duplicate entries for the same source entity
- Flag if `source_name` + `source_entity_name` combination appears more than once (unless intentional)

### 4.2 source_where_clause = Actual NULL Not String "NULL"
```sql
-- GOOD
source_where_clause = NULL

-- BAD — string literal "NULL"
source_where_clause = 'NULL'
source_where_clause = 'null'
source_where_clause = 'None'
```

### 4.3 Consistent Path Separators Ending with /
- All folder paths should use forward slashes and end with `/`
```sql
-- GOOD
landing_folder_path = 'source_system/entity_name/'

-- BAD — missing trailing slash or backslashes
landing_folder_path = 'source_system/entity_name'
landing_folder_path = 'source_system\entity_name\'
```

### 4.4 No Hardcoded Dates in Paths
- Landing folder paths should not contain hardcoded date components
- Use partition columns and dynamic path generation instead

### 4.5 write_mode Must Be Populated
- `write_mode` in `metadata_config_silver` must not be NULL or empty
- Valid values: `'overwrite'`, `'merge'`, `'upsert'`, `'append'`

### 4.6 is_initial_load_required Must Be Populated
- This column must have an explicit value (0 or 1), not NULL
- Used to determine whether to skip incremental logic on first load

### 4.7 watermark_type Must Be Populated
- When `load_type` = `'incremental'`, the watermark type/format columns must be populated
- NULL watermark columns with incremental load_type is a critical error

### 4.8 Secondary Watermarks from Config
- Secondary watermark columns (`watermark_column_secondary`, `watermark_column_secondary_format`) must come from config, not hardcoded

### 4.9 watermark_type Column Required for Incremental Loads (F46 - Major)
metadata_config and metadata_config_api must include a `watermark_type` column (values: 'DATETIME', 'BIGINT'). When `load_type` = 'incremental', `watermark_type` must be populated. This column drives type-based switch logic in ADF copy activities and stored procedures.

```sql
-- GOOD — watermark_type populated for incremental entities
INSERT INTO metadata_config (source_name, source_entity_name, load_type, watermark_column, watermark_type)
VALUES ('erp_hr', 'employees', 'incremental', 'modified_datetime', 'DATETIME');

INSERT INTO metadata_config (source_name, source_entity_name, load_type, watermark_column, watermark_type)
VALUES ('erp_hr', 'audit_log', 'incremental', 'log_sequence_id', 'BIGINT');

-- BAD — watermark_type missing for incremental entity
INSERT INTO metadata_config (source_name, source_entity_name, load_type, watermark_column, watermark_type)
VALUES ('erp_hr', 'employees', 'incremental', 'modified_datetime', NULL);
-- ADF pipeline cannot determine which switch branch to use
```
- Severity: Major — missing watermark_type breaks ADF type-based switch logic for incremental loads

### 4.10 execution_frequency Column (F47 - Medium)
metadata_config must include an `execution_frequency` column per entity (values: 'Daily', 'Hourly', 'Manual'). Entities set to 'Manual' should not be included in automated daily triggers. Deactivated entities must not have execution_frequency='Daily'.

```sql
-- GOOD — execution_frequency consistent with is_active
INSERT INTO metadata_config (source_name, source_entity_name, is_active, execution_frequency)
VALUES ('erp_hr', 'employees', 1, 'Daily');

INSERT INTO metadata_config (source_name, source_entity_name, is_active, execution_frequency)
VALUES ('erp_hr', 'legacy_archive', 0, 'Manual');

-- BAD — deactivated entity with Daily frequency
INSERT INTO metadata_config (source_name, source_entity_name, is_active, execution_frequency)
VALUES ('erp_hr', 'legacy_archive', 0, 'Daily');
-- Deactivated but scheduled = confusion
```
- Severity: Medium — inconsistent scheduling metadata causes operational confusion

### 4.11 landing_folder_path Must Start with source_name Prefix (F34 - Medium)
All landing_folder_path, bronze_folder_path, and silver_folder_path values must start with the source_name prefix for consistency across sources.

```sql
-- GOOD — paths start with source_name
landing_folder_path = 'esri_electric/ab_bd_crownland/'
bronze_folder_path = 'esri_electric/ab_bd_crownland/'
silver_folder_path = 'esri_electric/ab_bd_crownland/'

-- BAD — inconsistent prefix (uses 'esri' instead of 'esri_electric')
landing_folder_path = 'esri/ab_bd_crownland/'
-- OR missing source_name prefix entirely
landing_folder_path = 'ab_bd_crownland/'
```
- Severity: Medium — inconsistent path prefixes cause confusion and mis-routing

### 4.12 File Processing Tracker Table for File Sources (F35 - Critical)
For file-based sources, a `file_processing_tracker` table must exist to track individual file processing status. Recovery must re-process only FAILED/PENDING files. Must prevent duplicate insertion on retry.

```sql
-- GOOD — file processing tracker table
CREATE TABLE file_processing_tracker (
    tracker_id INT IDENTITY(1,1) PRIMARY KEY,
    source_name NVARCHAR(100) NOT NULL,
    source_entity_name NVARCHAR(255) NOT NULL,
    file_path NVARCHAR(1000) NOT NULL,
    file_name NVARCHAR(255) NOT NULL,
    status NVARCHAR(50) NOT NULL DEFAULT 'PENDING',
        -- Values: PENDING, PROCESSING, SUCCESS, FAILED,
        --         FORMAT_VALIDATION_FAILED, PARTIAL_SUCCESS
    error_message NVARCHAR(MAX),
    pipeline_run_id NVARCHAR(100),
    retry_count INT DEFAULT 0,
    az_create_datetime DATETIME2 NOT NULL DEFAULT GETUTCDATE(),
    az_update_datetime DATETIME2 NOT NULL DEFAULT GETUTCDATE(),
    CONSTRAINT check_file_tracker_status CHECK (
        status IN ('PENDING', 'PROCESSING', 'SUCCESS', 'FAILED',
                   'FORMAT_VALIDATION_FAILED', 'PARTIAL_SUCCESS')
    )
);

CREATE NONCLUSTERED INDEX index_file_tracker_on_status
    ON file_processing_tracker (source_name, status)
    INCLUDE (file_path, file_name);

-- Pipeline queries ONLY unprocessed files:
SELECT file_path, file_name
FROM file_processing_tracker
WHERE source_name = @SourceName
  AND status IN ('PENDING', 'FAILED')
ORDER BY az_create_datetime;

-- BAD — no file tracking; rely on directory scanning
-- GetMetadata activity scans all directories every run
-- No way to identify which files already processed
```
- Severity: Critical — without file tracking, failed files are skipped or duplicate data inserted on retry

### 4.13 stored_procedure_config Table for SP Sources (F50 - Major)
When source_entity_type='STORED_PROCEDURE', a dedicated stored_procedure_config table must exist.

```sql
-- GOOD — stored_procedure_config table
CREATE TABLE stored_procedure_config (
    sp_config_id INT IDENTITY(1,1) PRIMARY KEY,
    source_name NVARCHAR(100) NOT NULL,
    source_entity_name NVARCHAR(255) NOT NULL,
    sp_name NVARCHAR(255) NOT NULL,
    param_name NVARCHAR(100) NOT NULL,
    param_type NVARCHAR(50) NOT NULL,       -- 'STRING', 'DATETIME', 'INT'
    param_value NVARCHAR(MAX),              -- Supports ADF expressions
    sp_load_type NVARCHAR(20) NOT NULL,     -- 'FULL' or 'INCREMENTAL'
    sp_reference_db_type NVARCHAR(50),
    sp_reference_column_format NVARCHAR(100),
    is_active BIT DEFAULT 1,
    az_create_datetime DATETIME2 NOT NULL DEFAULT GETUTCDATE(),
    az_update_datetime DATETIME2 NOT NULL DEFAULT GETUTCDATE()
);

-- BAD — hardcoded SP parameters in ADF pipeline JSON
-- No stored_procedure_config table; parameters defined inline in pipeline
```
- Severity: Major — missing SP config table forces hardcoded parameters and prevents reuse

### 4.14 column_config Completeness and Precision/Scale Validation (F51 - Major)
column_config must have entries for EVERY column of EVERY source entity. For Decimal/Number types, precision and scale must be explicitly specified.

```sql
-- GOOD — complete column_config with precision/scale
INSERT INTO column_config (source_name, source_entity_name, column_name, column_data_type)
VALUES ('lpss_rla', 'billcode', 'uidbillcode', 'DecimalType(5,0)');

INSERT INTO column_config (source_name, source_entity_name, column_name, column_data_type)
VALUES ('lpss_rla', 'billcode', 'amount', 'DecimalType(18,2)');

INSERT INTO column_config (source_name, source_entity_name, column_name, column_data_type)
VALUES ('lpss_rla', 'billcode', 'rate', 'DecimalType(38,18)');  -- For FLOAT source type

-- BAD — missing column_config entries
-- Some columns of 'billcode' entity have no entry in column_config
-- Decimal types default to DecimalType(38,18) even for NUMBER(5,0) source type

-- BAD — missing precision/scale for numeric types
INSERT INTO column_config (source_name, source_entity_name, column_name, column_data_type)
VALUES ('lpss_rla', 'billcode', 'uidbillcode', 'DecimalType');  -- No precision/scale
```
- Severity: Major — incomplete column_config causes incorrect data types in Bronze/Silver

### 4.15 Metadata Entry Count Validation (F52 - Medium)
Active records in metadata_config must match expected entity count. No duplicates for same source_name + source_entity_name. Counts must be consistent across metadata_config, metadata_config_silver, and column_config.

```sql
-- GOOD — validate no duplicates
SELECT source_name, source_entity_name, COUNT(*) as cnt
FROM metadata_config
WHERE is_active = 1
GROUP BY source_name, source_entity_name
HAVING COUNT(*) > 1;
-- Result should be EMPTY (no duplicates)

-- GOOD — cross-table count validation
-- Every active entity in metadata_config should have entries in metadata_config_silver
SELECT mc.source_name, mc.source_entity_name
FROM metadata_config mc
LEFT JOIN metadata_config_silver mcs
    ON mc.source_name = mcs.source_name
    AND mc.source_entity_name = mcs.entity_name
WHERE mc.is_active = 1
  AND mcs.source_name IS NULL;
-- Result should be EMPTY (all entities have silver config)

-- BAD — duplicate entries
-- Two rows for 'lpss_rla' + 'billcode' in metadata_config
-- Causes: double processing, duplicate audit records, watermark conflicts
```
- Severity: Medium — duplicates cause double processing; missing entries cause skipped entities

---

## 5. Audit Logging

### Required Audit Fields:
Every pipeline execution must log:
```python
{
    "pipeline_id": pipeline_id,
    "activity_id": activity_id,
    "source_type": source_type,
    "target_entity": specific_table_name,  # NOT generic "bronze" or "silver"
    "write_mode": write_mode,              # "overwrite" for full, "append" for incremental
    "files_copied": files_count,
    "bytes_copied": bytes_count,
    "rows_read": rows_read,
    "rows_written": rows_written,
    "execution_start_time": start_time,
    "execution_end_time": end_time,
    "duration_seconds": duration,          # MUST be present
    "error_details": error_msg,            # NULL on success
    "status": "success" or "failed",
    "files_read": files_read,              # For file sources: @activity().output.filesRead
    "files_written": files_written,        # For file sources: @activity().output.filesWritten
    "data_read": data_read,                # For file sources: @activity().output.dataRead (bytes)
    "data_written": data_written,          # For file sources: @activity().output.dataWritten (bytes)
    "adf_master_pipeline_name": pipeline_name,  # Master pipeline name for audit traceability
}
```

**Note:** For file-based sources, the four file-level metrics (files_read, files_written, data_read, data_written) are required in addition to the standard fields.

### Critical Checks:
- `target_entity` must be specific file/table name (NOT generic "bronze", "silver")
- `duration_seconds` MUST be present — this is the most commonly missing field
- `write_mode`: `"overwrite"` for full, `"append"` for incremental
- Audit schema consistent across ALL layers (same columns in bronze, silver, gold audit)

### Audit on Both Paths:
```python
# GOOD — audit on both success and failure
try:
    result = process_data(config)
    log_audit(status="success", rows=result.count, duration=elapsed)
except Exception as e:
    log_audit(status="failed", error=str(e), duration=elapsed)
    raise
```

---

## 6. Notifications

### Failure Notification Requirements:
- Pipeline failures MUST trigger notification
- Notification on ALL failure paths, including inside ForEach activities
- Use Logic App for Azure notifications

### Consolidated Summary:
- Single summary notification at the final pipeline stage
- Do NOT send per-stage or per-entity notifications
- Summary should include: total entities processed, successes, failures, duration

---

## 7. Cross-Reference Checks

When reviewing metadata framework components, verify consistency across artifacts:

| Cross-Reference | What to Check |
|---|---|
| SQL DDL ↔ Stored Procedures | Column names in CREATE TABLE must match names in UPDATE/INSERT |
| SQL ↔ ADF Pipelines | ADF parameter names must match stored procedure parameter names |
| SQL ↔ Databricks Notebooks | Column names read in Python must match actual table columns |
| metadata_config ↔ metadata_config_api | API table should have all base columns plus API-specific |
| Control Tables ↔ Audit Tables | Audit `source_id`/`source_name` must exist in control tables |

---

## 8. Best Recommended Practices

### 8.1 Change Tracking on Control Tables
- Add `last_modified_by` and `last_modified_datetime` columns to every control table
- Maintain a `metadata_change_log` table that records every INSERT, UPDATE, and DELETE on control tables
- Change log enables auditing who changed what configuration and when — critical for troubleshooting production issues

```sql
-- GOOD — change tracking columns on control table
ALTER TABLE metadata_config ADD
    last_modified_by NVARCHAR(100) NOT NULL DEFAULT SYSTEM_USER,
    last_modified_datetime DATETIME2 NOT NULL DEFAULT GETUTCDATE();

-- GOOD — change log table
CREATE TABLE metadata_change_log (
    change_id INT IDENTITY(1,1) PRIMARY KEY,
    table_name NVARCHAR(100) NOT NULL,
    source_id INT NOT NULL,
    column_changed NVARCHAR(100),
    old_value NVARCHAR(MAX),
    new_value NVARCHAR(MAX),
    changed_by NVARCHAR(100) NOT NULL DEFAULT SYSTEM_USER,
    changed_datetime DATETIME2 NOT NULL DEFAULT GETUTCDATE()
);

-- BAD — no tracking of who or when config was changed
UPDATE metadata_config SET load_type = 'full' WHERE source_id = 42;
```

### 8.2 Bulk Onboarding via Config Files
- Support onboarding multiple source entities via a CSV or JSON config file
- Validate the entire batch before inserting any rows — reject the batch if validation fails
- Prevents partial inserts that leave the control table in an inconsistent state

```sql
-- GOOD — validate-then-insert pattern (in SP)
CREATE PROCEDURE sp_bulk_onboard_sources
    @ConfigJson NVARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;

    -- Step 1: Parse into temp table
    SELECT * INTO #staging
    FROM OPENJSON(@ConfigJson)
    WITH (
        source_name NVARCHAR(100),
        source_entity_name NVARCHAR(255),
        load_type NVARCHAR(50)
    );

    -- Step 2: Validate ALL rows before insert
    IF EXISTS (SELECT 1 FROM #staging WHERE source_name IS NULL OR source_entity_name IS NULL)
    BEGIN
        RAISERROR('Validation failed: NULL source_name or source_entity_name', 16, 1);
        RETURN;
    END

    IF EXISTS (
        SELECT 1 FROM #staging s
        JOIN metadata_config mc ON s.source_name = mc.source_name
            AND s.source_entity_name = mc.source_entity_name
    )
    BEGIN
        RAISERROR('Validation failed: duplicate source entities found', 16, 1);
        RETURN;
    END

    -- Step 3: Insert only after all validation passes
    INSERT INTO metadata_config (source_name, source_entity_name, load_type, az_create_datetime, az_update_datetime)
    SELECT source_name, source_entity_name, load_type, GETUTCDATE(), GETUTCDATE()
    FROM #staging;
END

-- BAD — insert one-by-one with no batch validation
INSERT INTO metadata_config (source_name, source_entity_name) VALUES ('src1', 'entity1');
INSERT INTO metadata_config (source_name, source_entity_name) VALUES ('src1', 'entity2');
-- If entity3 fails, entity1 and entity2 are already committed
```

### 8.3 Control Table Indexing
- Create a composite index on `(source_name, source_entity_name)` — this is the most common lookup pattern
- Index `is_active` and `load_type` columns for filtered queries used by pipeline Lookups
- Missing indexes cause slow Lookup activities that delay every pipeline run

```sql
-- GOOD — indexes aligned with query patterns
CREATE NONCLUSTERED INDEX index_metadata_config_on_source_entity
    ON metadata_config (source_name, source_entity_name);

CREATE NONCLUSTERED INDEX index_metadata_config_on_active_load
    ON metadata_config (is_active, load_type)
    INCLUDE (source_id, source_name, source_entity_name);

-- BAD — no non-PK indexes on frequently queried control table
-- ADF Lookup queries scan entire table every pipeline run
```
- Severity: Medium — missing indexes on control tables slow every pipeline execution

### 8.4 Self-Healing Watermarks
- Implement automatic watermark reset after N consecutive failures (e.g., 3) for the same source entity
- Provide a manual override SP (`sp_reset_watermark`) for emergency recovery
- **Never advance the watermark past a failed load** — this permanently skips data

```sql
-- GOOD — manual watermark reset SP
CREATE PROCEDURE sp_reset_watermark
    @SourceID INT,
    @ResetToTimestamp DATETIME2 = NULL
AS
BEGIN
    SET NOCOUNT ON;

    -- Log the reset action
    INSERT INTO metadata_change_log (table_name, source_id, column_changed, old_value, new_value)
    SELECT 'metadata_config', @SourceID, 'watermark_last_loaded_timestamp',
        CAST(watermark_last_loaded_timestamp AS NVARCHAR(50)),
        ISNULL(CAST(@ResetToTimestamp AS NVARCHAR(50)), 'NULL')
    FROM metadata_config
    WHERE source_id = @SourceID;

    -- Reset watermark
    UPDATE metadata_config
    SET watermark_last_loaded_timestamp = @ResetToTimestamp,
        az_update_datetime = GETUTCDATE()
    WHERE source_id = @SourceID;
END

-- GOOD — auto-reset after consecutive failures (checked in pipeline)
-- Pipeline logic: IF consecutive_failure_count >= 3, call sp_reset_watermark
```
- Severity: Critical — advancing watermark past failures causes permanent data loss

### 8.5 Pre-Execution Validation
- Validate metadata config records before the pipeline begins processing
- Check for: required columns populated, valid path formats, watermark consistency (type matches column), active flag set
- Fail fast with a clear error message rather than discovering bad config mid-pipeline

```python
# GOOD — pre-execution validation in notebook
def validate_config(config):
    """Validate metadata config before pipeline execution."""
    errors = []

    if not config.get("source_name"):
        errors.append("source_name is required")

    if config["load_type"] == "incremental" and not config.get("watermark_column"):
        errors.append("watermark_column required for incremental load_type")

    if config.get("landing_folder_path") and not config["landing_folder_path"].endswith("/"):
        errors.append("landing_folder_path must end with '/'")

    if config.get("watermark_column") and not config.get("watermark_column_format"):
        errors.append("watermark_column_format required when watermark_column is set")

    if errors:
        raise ValueError(f"Config validation failed for source_id={config['source_id']}: {'; '.join(errors)}")

# BAD — no validation, discover errors mid-pipeline
df = read_source(config)  # Fails here with cryptic error because landing_folder_path is NULL
```

### 8.6 Pipeline Observability
- Maintain a `pipeline_run_log` table that tracks every pipeline execution with: `run_id`, `source_name`, `entity_name`, `rows_read`, `rows_written`, `duration_seconds`, `status`, `error_message`
- Implement **90-day retention** on the run log — older records moved to archive or deleted
- Use the run log for trend analysis: degrading performance, increasing failure rates, growing load times

```sql
-- GOOD — pipeline run log table
CREATE TABLE pipeline_run_log (
    log_id INT IDENTITY(1,1) PRIMARY KEY,
    pipeline_run_id NVARCHAR(100) NOT NULL,
    source_name NVARCHAR(100) NOT NULL,
    source_entity_name NVARCHAR(255) NOT NULL,
    layer NVARCHAR(20) NOT NULL,  -- 'landing', 'bronze', 'silver', 'gold'
    rows_read BIGINT,
    rows_written BIGINT,
    duration_seconds INT,
    status NVARCHAR(20) NOT NULL,  -- 'success', 'failed', 'skipped'
    error_message NVARCHAR(MAX),
    execution_start_time DATETIME2 NOT NULL,
    execution_end_time DATETIME2,
    az_create_datetime DATETIME2 NOT NULL DEFAULT GETUTCDATE()
);

-- Retention: delete logs older than 90 days
CREATE PROCEDURE sp_cleanup_run_log
AS
BEGIN
    SET NOCOUNT ON;
    DELETE FROM pipeline_run_log
    WHERE az_create_datetime < DATEADD(DAY, -90, GETUTCDATE());
END
```

### 8.7 Governance — SPs as Write Interface
- All modifications to control tables (`metadata_config`, `metadata_config_silver`, `gold_entity_config`) must go through **stored procedures**
- Direct INSERT/UPDATE/DELETE access should be restricted to the SP execution role only
- This ensures validation, change logging, and audit tracking are never bypassed

```sql
-- GOOD — SP enforces validation and logging
CREATE PROCEDURE sp_update_load_type
    @SourceID INT,
    @NewLoadType NVARCHAR(50)
AS
BEGIN
    SET NOCOUNT ON;

    -- Validate
    IF @NewLoadType NOT IN ('full', 'incremental')
    BEGIN
        RAISERROR('Invalid load_type: %s. Must be full or incremental.', 16, 1, @NewLoadType);
        RETURN;
    END

    -- Log change
    INSERT INTO metadata_change_log (table_name, source_id, column_changed, old_value, new_value)
    SELECT 'metadata_config', @SourceID, 'load_type', load_type, @NewLoadType
    FROM metadata_config WHERE source_id = @SourceID;

    -- Update
    UPDATE metadata_config
    SET load_type = @NewLoadType, az_update_datetime = GETUTCDATE()
    WHERE source_id = @SourceID;
END

-- BAD — direct update bypasses validation and logging
UPDATE metadata_config SET load_type = 'incremental' WHERE source_id = 42;
```
