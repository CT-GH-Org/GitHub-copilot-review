# SQL Review Patterns

Domain-specific review patterns for SQL DDL, DML, stored procedures, and views in a medallion architecture data lakehouse.

---

## 1. Naming Conventions

### Tables, Columns, Views — All lowercase with underscores:
```sql
-- GOOD
CREATE TABLE metadata_config (
    source_id INT,
    source_name NVARCHAR(100),
    watermark_column NVARCHAR(255)
);

-- BAD
CREATE TABLE MetadataConfig (
    SourceId INT,
    SourceName NVARCHAR(100)
);
```

### Self-Explanatory Names — No abbreviations:
```sql
-- GOOD
watermark_last_loaded_timestamp
bronze_last_loaded_timestamp
landing_last_modified_date

-- BAD
wm_ts, brz_lst_ld, lmd
```

### No SQL Keyword Conflicts:
- Column names must not be SQL reserved words (e.g., `order`, `select`, `table`, `index`)

### Constraint Naming Prefixes:
| Type | Prefix | Example |
|---|---|---|
| Primary Key | `pk_` | `pk_metadata_config` |
| Foreign Key | `fk_` | `fk_metadata_config_source_id_source_master` |
| Unique | `unique_` | `unique_metadata_config_source_name` |
| Check | `check_` | `check_metadata_config_load_type_values` |
| Index | `index_` | `index_metadata_config_on_source_name` |

### Column Prefixes for Disambiguation:
```sql
-- GOOD — clear context
source_database_name
target_database_name
landing_container_name
bronze_catalog_name

-- BAD — ambiguous
database_name    -- which database?
container_name   -- which container?
```

---

## 2. Data Types

### NVARCHAR over VARCHAR:
```sql
-- GOOD — Unicode support
source_name NVARCHAR(100)

-- BAD — no Unicode support
source_name VARCHAR(100)
```

### VARCHAR/NVARCHAR Length:
- Length must accommodate maximum possible value
- Flag overly short lengths (e.g., `NVARCHAR(10)` for a file path)
- Flag overly long lengths without justification (e.g., `NVARCHAR(MAX)` for a status field)

### BIGINT for Large Values:
```sql
-- GOOD — when value may exceed INT range (2.1 billion)
watermark_last_loaded_bigint BIGINT

-- BAD — if values can exceed INT range
watermark_value INT
```

### Flag Columns — BIT or CHAR:
```sql
-- GOOD
is_active BIT DEFAULT 1
is_initial_load_required BIT DEFAULT 0

-- ALSO ACCEPTABLE
is_active CHAR(1) DEFAULT 'Y' CHECK (is_active IN ('Y', 'N'))

-- BAD
is_active INT DEFAULT 1
is_active NVARCHAR(5) DEFAULT 'true'
```

### IDENTITY for Surrogate Keys:
```sql
-- GOOD — auto-generated
source_id INT IDENTITY(1,1) PRIMARY KEY

-- BAD — manual ID without IDENTITY
source_id INT PRIMARY KEY  -- how is this populated?
```

---

## 3. Constraints

- **NOT NULL** on key columns (`source_id`, `source_name`, `load_type`)
- **Primary Keys** on ALL tables — flag any table without PK
- **Foreign Key Constraints** where referential integrity matters — FK column types must match referenced PK
- **Unique Constraints** where business rules require uniqueness beyond PK
- **Indexes** on columns used frequently in WHERE, JOIN, ORDER BY — flag large tables without non-PK indexes

---

## 4. Stored Procedures

### GETUTCDATE() — CRITICAL:
```sql
-- GOOD
SET @CurrentDateTime = GETUTCDATE()
UPDATE metadata_config SET az_update_datetime = GETUTCDATE()

-- BAD
SET @CurrentDateTime = GETDATE()
```

### Use source_id for Unambiguous Updates:
```sql
-- GOOD — unambiguous
UPDATE metadata_config
SET watermark_last_loaded_timestamp = @WatermarkValue
WHERE source_id = @SourceID

-- BAD — potentially ambiguous with duplicates
UPDATE metadata_config
SET watermark_last_loaded_timestamp = @WatermarkValue
WHERE source_name = @SourceName
```

### Single UPDATE for Related Columns:
```sql
-- GOOD — one statement
UPDATE metadata_config
SET watermark_last_loaded_timestamp = @WatermarkTimestamp,
    watermark_last_loaded_bigint = @WatermarkBigint,
    az_update_datetime = GETUTCDATE()
WHERE source_id = @SourceID

-- BAD — separate updates for related columns
UPDATE metadata_config SET watermark_last_loaded_timestamp = @Ts WHERE source_id = @ID
UPDATE metadata_config SET watermark_last_loaded_bigint = @Big WHERE source_id = @ID
UPDATE metadata_config SET az_update_datetime = GETUTCDATE() WHERE source_id = @ID
```

### Separate SPs for API vs Non-API:
- API sources have different metadata (endpoints, auth, pagination)
- Don't force API and non-API logic into a single SP

### Accept source_name Parameter (not environment):
```sql
-- GOOD
CREATE PROCEDURE sp_update_watermark
    @SourceID INT,
    @SourceName NVARCHAR(100)

-- BAD
CREATE PROCEDURE sp_update_watermark
    @Environment NVARCHAR(50)  -- should not use environment
```

### Environment Values from Config Table:
```sql
-- GOOD — from environment_config table
SELECT @StorageAccount = storage_account_name
FROM environment_config
WHERE source_name = @SourceName

-- BAD — hardcoded CASE statement
SET @StorageAccount = CASE
    WHEN @Environment = 'dev' THEN 'devstorageacct'
    WHEN @Environment = 'prod' THEN 'prodstorageacct'
END
```

### PascalCase SP Parameters:
```sql
-- GOOD — consistent PascalCase
@SourceID INT
@SilverID INT
@SilverTable NVARCHAR(255)
@BronzeTable NVARCHAR(255)

-- BAD — inconsistent
@sourceId INT        -- camelCase
@silver_id INT       -- snake_case
@tbl_silver NVARCHAR -- abbreviation
```

### BIGINT Watermark Support:
- Stored procedures must support both timestamp and BIGINT watermark types
- Include `watermark_last_loaded_bigint BIGINT` parameter where applicable

### duration_seconds Field:
- Audit-related stored procedures must include `duration_seconds` parameter
- This is the most commonly missing field in audit logging

---

## 5. SQL in Python (Embedded SQL)

### SQL Keywords in UPPERCASE:
```python
# GOOD
query = """
    SELECT source_name, watermark_column
    FROM metadata_config
    WHERE load_type = 'incremental'
    GROUP BY source_name
    ORDER BY source_name
"""

# BAD — lowercase keywords
query = """
    select source_name, watermark_column
    from metadata_config
    where load_type = 'incremental'
"""
```

### Rest of SQL in lowercase:
- Table names, column names, aliases — all lowercase
- Only SQL keywords are UPPERCASE

---

## 6. Best Recommended Practices

### 6.1 SET NOCOUNT ON
- Include `SET NOCOUNT ON` as the **first line** inside every stored procedure
- Prevents sending row-count messages for each statement, reducing network overhead and avoiding interference with some client libraries

```sql
-- GOOD
CREATE PROCEDURE sp_update_watermark
    @SourceID INT,
    @WatermarkValue DATETIME2
AS
BEGIN
    SET NOCOUNT ON;

    UPDATE metadata_config
    SET watermark_last_loaded_timestamp = @WatermarkValue,
        az_update_datetime = GETUTCDATE()
    WHERE source_id = @SourceID;
END

-- BAD — missing SET NOCOUNT ON
CREATE PROCEDURE sp_update_watermark
    @SourceID INT,
    @WatermarkValue DATETIME2
AS
BEGIN
    UPDATE metadata_config
    SET watermark_last_loaded_timestamp = @WatermarkValue
    WHERE source_id = @SourceID;
END
```

### 6.2 Idempotent Stored Procedures
- Every SP must be **safe to re-run** without creating duplicates or corrupting data
- Use `IF EXISTS` checks before INSERT to prevent duplicates
- Use `MERGE` for upsert scenarios instead of separate DELETE + INSERT

```sql
-- GOOD — idempotent upsert with MERGE
MERGE metadata_config AS target
USING (SELECT @SourceName AS source_name, @EntityName AS source_entity_name) AS source
ON target.source_name = source.source_name
   AND target.source_entity_name = source.source_entity_name
WHEN MATCHED THEN
    UPDATE SET az_update_datetime = GETUTCDATE()
WHEN NOT MATCHED THEN
    INSERT (source_name, source_entity_name, az_create_datetime, az_update_datetime)
    VALUES (source.source_name, source.source_entity_name, GETUTCDATE(), GETUTCDATE());

-- BAD — not idempotent, creates duplicates on re-run
INSERT INTO metadata_config (source_name, source_entity_name)
VALUES (@SourceName, @EntityName);
```

### 6.3 TRY-CATCH with Explicit Transactions
- Wrap all multi-statement DML in `BEGIN TRY / BEGIN CATCH` with explicit `BEGIN TRAN / COMMIT / ROLLBACK`
- Set `XACT_ABORT ON` to ensure the transaction is automatically rolled back on any error

```sql
-- GOOD — explicit transaction with error handling
CREATE PROCEDURE sp_process_entity
    @SourceID INT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    BEGIN TRY
        BEGIN TRANSACTION;

        UPDATE metadata_config
        SET bronze_last_loaded_timestamp = GETUTCDATE()
        WHERE source_id = @SourceID;

        INSERT INTO audit_log (source_id, status, log_datetime)
        VALUES (@SourceID, 'success', GETUTCDATE());

        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0
            ROLLBACK TRANSACTION;

        INSERT INTO audit_log (source_id, status, error_message, log_datetime)
        VALUES (@SourceID, 'failed', ERROR_MESSAGE(), GETUTCDATE());

        THROW;
    END CATCH
END

-- BAD — no transaction, no error handling
UPDATE metadata_config SET bronze_last_loaded_timestamp = GETUTCDATE() WHERE source_id = @SourceID;
INSERT INTO audit_log (source_id, status) VALUES (@SourceID, 'success');
```

### 6.4 Common Table Expressions (CTEs)
- Use named CTEs for multi-step transformations — each CTE should represent one logical step
- Prefer CTEs over nested subqueries for readability and maintainability

```sql
-- GOOD — clear CTE pipeline
WITH active_sources AS (
    SELECT source_id, source_name, load_type
    FROM metadata_config
    WHERE is_active = 1
),
incremental_sources AS (
    SELECT source_id, source_name
    FROM active_sources
    WHERE load_type = 'incremental'
)
SELECT s.source_id, s.source_name, w.watermark_last_loaded_timestamp
FROM incremental_sources s
JOIN watermark_history w ON s.source_id = w.source_id;

-- BAD — deeply nested subqueries
SELECT source_id, source_name, watermark_last_loaded_timestamp
FROM (
    SELECT source_id, source_name
    FROM (
        SELECT source_id, source_name, load_type
        FROM metadata_config
        WHERE is_active = 1
    ) a
    WHERE load_type = 'incremental'
) b
JOIN watermark_history w ON b.source_id = w.source_id;
```

### 6.5 Window Functions Over Cursors
- Use `ROW_NUMBER()` for deduplication, `RANK()` for ranking, `LAG()`/`LEAD()` for row comparison
- **Never use cursors** — there is always a set-based alternative
- Severity: Major — cursors cause severe performance degradation

```sql
-- GOOD — ROW_NUMBER for dedup
WITH ranked AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY source_name, source_entity_name
            ORDER BY az_update_datetime DESC
        ) AS rn
    FROM metadata_config
)
SELECT * FROM ranked WHERE rn = 1;

-- GOOD — LAG for change detection
SELECT source_id,
    watermark_last_loaded_timestamp,
    LAG(watermark_last_loaded_timestamp) OVER (
        PARTITION BY source_id ORDER BY az_update_datetime
    ) AS previous_watermark
FROM watermark_history;

-- BAD — cursor-based processing
DECLARE cursor_sources CURSOR FOR SELECT source_id FROM metadata_config;
OPEN cursor_sources;
-- ... row-by-row processing ...
```

### 6.6 EXISTS Over COUNT for Existence Checks
- Use `IF EXISTS (SELECT 1 ...)` instead of `IF (SELECT COUNT(*) ...) > 0`
- `EXISTS` short-circuits on the first match; `COUNT(*)` scans all matching rows

```sql
-- GOOD — short-circuit with EXISTS
IF EXISTS (SELECT 1 FROM metadata_config WHERE source_name = @SourceName)
BEGIN
    -- source already exists
    PRINT 'Source exists';
END

-- BAD — COUNT scans all rows
IF (SELECT COUNT(*) FROM metadata_config WHERE source_name = @SourceName) > 0
BEGIN
    PRINT 'Source exists';
END
```

### 6.7 Parameterized Dynamic SQL
- Always use `sp_executesql` with parameters for dynamic SQL
- **Never** use `EXEC()` with string concatenation — this is a SQL injection vector
- Severity: Critical — `EXEC(string concat)` enables SQL injection attacks

```sql
-- GOOD — parameterized dynamic SQL
DECLARE @SQL NVARCHAR(MAX);
DECLARE @Params NVARCHAR(MAX);

SET @SQL = N'SELECT * FROM metadata_config WHERE source_name = @name AND load_type = @type';
SET @Params = N'@name NVARCHAR(100), @type NVARCHAR(50)';

EXEC sp_executesql @SQL, @Params, @name = @SourceName, @type = @LoadType;

-- BAD — string concatenation (SQL injection risk)
DECLARE @SQL NVARCHAR(MAX);
SET @SQL = 'SELECT * FROM metadata_config WHERE source_name = ''' + @SourceName + '''';
EXEC(@SQL);
```

### 6.8 Avoid SELECT *
- Always use **explicit column lists** in SELECT statements
- `SELECT *` breaks when columns are added/removed, returns unnecessary data, and prevents covering index usage
- Exception: `SELECT *` is acceptable only inside `EXISTS (SELECT 1 ...)` or in ad-hoc debugging

```sql
-- GOOD — explicit columns
SELECT source_id, source_name, load_type, watermark_column
FROM metadata_config
WHERE is_active = 1;

-- BAD — SELECT * in production code
SELECT *
FROM metadata_config
WHERE is_active = 1;
```

### 6.9 View Naming and Patterns
- Views must use `vw_` prefix: `vw_active_sources`, `vw_gold_customer_summary`
- Use views to provide **user-friendly abstractions** over complex joins or business logic
- Use views for **column restriction** to limit PII exposure — grant access to the view, not the base table

```sql
-- GOOD — view with PII restriction
CREATE VIEW vw_customer_safe AS
SELECT
    customer_id,
    customer_region,
    customer_segment,
    az_create_datetime
FROM gold.customer
-- Excludes: customer_name, email, phone, ssn
;

-- GOOD — view for business-friendly abstraction
CREATE VIEW vw_active_incremental_sources AS
SELECT
    source_id,
    source_name,
    source_entity_name,
    watermark_column,
    watermark_last_loaded_timestamp
FROM metadata_config
WHERE is_active = 1
  AND load_type = 'incremental';
```
