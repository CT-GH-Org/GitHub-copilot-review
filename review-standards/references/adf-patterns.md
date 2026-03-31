# ADF Pipeline Review Patterns

Domain-specific review patterns for Azure Data Factory pipeline JSON in a medallion architecture data lakehouse.

---

## 1. Naming Conventions

### Activity Names — Title Case:
```json
// GOOD
"name": "Copy Source Data"
"name": "Lookup Config Table"
"name": "Set Watermark Value"

// BAD
"name": "copy_source_data"
"name": "copySourceData"
"name": "COPY SOURCE DATA"
```

### Pipeline Names:
- Must include `pl_` prefix
- Master pipelines must include `master` in name
- Full-load pipelines must include `full` in name
- Incremental pipelines must include `incr` in name
- **No environment-specific prefixes:** `dev_`, `prod_`, `test_`, `uat_` are FORBIDDEN

### Datasets, Linked Services, Variables, Parameters — snake_case:
```json
// GOOD
"name": "source_dataset"
"name": "sql_metadata_db"

// BAD
"name": "SourceDataset"
"name": "SqlMetadataDB"
```

### Linked Service Names — Must include type prefix:
- `sftp_` for SFTP connections
- `sql_` for SQL databases
- `http_` for HTTP/REST endpoints
- `adls_` for Azure Data Lake Storage
- `databricks_` for Databricks
- `kv_` for Key Vault

### Switch Activities — No numeric case values:
```json
// GOOD
"cases": [{ "value": "full" }, { "value": "incremental" }]

// BAD
"cases": [{ "value": "1" }, { "value": "2" }]
```

---

## 2. Parameterization

### Hardcoded Values — CRITICAL:
All of the following must come from parameters, metadata config, or environment config — never hardcoded:
- Notebook paths → `@item().notebook_path`
- Environment values → `@pipeline().parameters.source_name`
- Secrets/credentials → Key Vault via Web Activity
- Storage paths, database names, API URLs

### Pipeline Parameters:
- Defined at master pipeline level and passed to child pipelines
- Dataset parameters used where connection details vary
- **No `environment` parameter** — use `source_name` filtering instead
- Global parameters for shared notebook paths
- `processing_mode` (not `mode`) for consistency
- `adf_master_pipeline_run_id` (not `adf_run_id`) for run ID parameters

### Remove Unused Parameters:
- Flag parameters defined at pipeline level but never referenced in activities
- Unused parameters add confusion and maintenance burden
- Severity: Major

### adf_master_pipeline_name Parameter (F4):
- `adf_master_pipeline_name` must be passed as a parameter from master to child pipelines AND stored in the audit table. This enables audit queries to identify which master pipeline triggered execution.

```json
// GOOD — adf_master_pipeline_name passed from master and logged in audit
{
    "name": "Execute Child Pipeline",
    "type": "ExecutePipeline",
    "typeProperties": {
        "parameters": {
            "adf_master_pipeline_name": { "value": "@pipeline().Pipeline", "type": "Expression" },
            "adf_master_pipeline_run_id": { "value": "@pipeline().RunId", "type": "Expression" }
        }
    }
}

// BAD — adf_master_pipeline_name not passed to child; audit cannot trace master origin
{
    "name": "Execute Child Pipeline",
    "type": "ExecutePipeline",
    "typeProperties": {
        "parameters": {
            "adf_master_pipeline_run_id": { "value": "@pipeline().RunId", "type": "Expression" }
        }
    }
}
```
- Severity: Major — audit records cannot identify which master pipeline triggered execution

### Dataset Naming Must Inherit Linked Service Type Prefix (F10):
- Dataset name must copy the linked service type prefix for disambiguation. Generic names like `sftp_dataset` are insufficient — use `sftp_omft_dataset`. The name should reflect both connection type AND specific source/purpose.

```json
// GOOD — dataset name includes linked service type prefix and source context
"name": "sftp_omft_dataset"
"name": "sql_metadata_config_dataset"
"name": "adls_landing_csv_dataset"

// BAD — generic dataset name without linked service type context
"name": "sftp_dataset"
"name": "source_dataset"
"name": "landing_dataset"
```
- Severity: Medium — ambiguous dataset names cause confusion in large pipeline estates

---

## 3. Retry & Timeout Configuration

### Copy and Lookup Activities — Required:
```json
"policy": {
    "retry": 3,
    "retryIntervalInSeconds": 30
}
```

### Retry Value Must Be Exactly 3 (F5):
- The retry value must be exactly **3** for all applicable activities — not 0, not 1, not 2.
- Inconsistent values (some activities with retry=2, others with retry=3) are not acceptable.
- All **Lookup, Copy, Web, Stored Procedure, Script, and Databricks Notebook** activities must have `retry: 3`.

```json
// GOOD — consistent retry=3 across all activities
"policy": { "retry": 3, "retryIntervalInSeconds": 30 }

// BAD — inconsistent or missing retry values
"policy": { "retry": 2, "retryIntervalInSeconds": 30 }  // Copy Activity
"policy": { "retry": 3, "retryIntervalInSeconds": 30 }  // Lookup Activity
// Some activities have retry=0 or no retry policy at all
```
- Severity: Major — inconsistent retry policies cause unpredictable failure behavior

### Lookup Activity Timeout (fast queries):
```json
"policy": {
    "timeout": "00:10:00"
}
```

### SQL Query Timeout:
```json
"queryTimeout": "00:05:00"
```

### Copy/GetMetadata Activity Timeout:
```json
"policy": {
    "timeout": "00:10:00"
}
```

- Flag any activity with default 7-day timeout (`"7.00:00:00"`) that should be shorter

---

## 4. Feedback-Derived Patterns

### 4.1 Null + Empty String Check Pattern
Where clauses that filter on string values from metadata must check for BOTH null and empty string:

```
// GOOD
@not(or(equals(item().source_where_clause, ''), equals(item().source_where_clause, null)))

// BAD — only checks one condition
@not(equals(item().source_where_clause, null))
@not(equals(item().source_where_clause, ''))
```

### 4.2 @pipeline().TriggerTime for load_start_time
```json
// GOOD — consistent, reflects when pipeline was triggered
"value": "@pipeline().TriggerTime"

// BAD — varies with execution time
"value": "@utcNow()"
```

### 4.3 Don't Fail for Zero Records on Incremental
- When incremental load returns zero records, this is valid (no new data since last load)
- Do NOT treat zero records as a failure condition for incremental loads
- Only fail for zero records on full loads (which should always return data)

### 4.4 Partition with Integer Columns Only
- When partitioning landing files, use integer-type columns (not strings or dates)
- Severity: Medium

### 4.5 Combine source_query and source_where_clause Properly
- When both `source_query` and `source_where_clause` exist in metadata, combine them correctly
- The source_where_clause should be appended as an additional WHERE/AND condition
- Do not override source_query with source_where_clause

### 4.6 Consistent Watermark Activity Naming
- Watermark-related activities (Lookup, Set Variable, Stored Procedure) should have consistent naming
- Example: `Lookup Watermark`, `Set Watermark Value`, `Update Watermark`

### 4.7 Copy Activity Name Must Match Audit Reference
- The name of a Copy activity must exactly match what is logged in the audit table
- Mismatches between activity name and audit `activity_name` cause tracking issues

### 4.8 Master Pipeline Concurrency = 1
```json
"concurrency": 1
```
- Master pipelines must have `concurrency: 1` to prevent parallel execution conflicts

### 4.9 Summary Email at Final Stage Only
- Send ONE consolidated summary email at the very end of the master pipeline
- Do NOT send emails per-stage or per-entity
- Severity: Medium

### 4.10 DQ Check Failures Don't Throw Exceptions
- Data quality check failures should be logged and reported, not throw pipeline-level exceptions
- DQ failures should result in a notification but allow the pipeline to continue or complete gracefully
- Severity: Medium

### 4.11 Cross-Stage Watermark Safety (F1 - Critical)
Watermark must NOT advance when downstream pipelines (Bronze/Gold) fail. When landing pipeline succeeds and updates watermark but Bronze/Gold fails, data is permanently skipped. Watermark should only advance after ALL downstream stages succeed, OR a reprocessing mechanism must exist.

```json
// BAD — watermark updated in landing pipeline; if bronze fails, data skipped
// pl_landing_process updates watermark → pl_bronze_process fails → next run skips that data

// GOOD — watermark updated only after final stage succeeds
// OR: recovery mechanism re-processes from last successful watermark per stage
// Each layer (landing, bronze, silver, gold) tracks its own last-loaded timestamp
```
- Severity: Critical — causes permanent data loss on transient failures

### 4.12 BIGINT Watermark Type Support (F2 - Critical)
ADF incremental copy activities must support BOTH watermark_type=DATETIME and watermark_type=BIGINT using type-based switch/conditional expressions. Hardcoding DATETIME-only watermark logic will fail for BIGINT entities.

```json
// GOOD — type-based switch for watermark expression
@if(
  equals(pipeline().parameters.watermark_type, 'DATETIME'),
  concat(pipeline().parameters.watermark_column, ' > TO_TIMESTAMP(''', pipeline().parameters.watermark_last_loaded_timestamp, ''',''YYYY-MM-DD"T"HH24:MI:SS'')'),
  concat(pipeline().parameters.watermark_column, ' > ''', string(pipeline().parameters.watermark_last_loaded_bigint), '''')
)

// BAD — hardcoded DATETIME-only assumption
@concat(pipeline().parameters.watermark_column, ' > ''', pipeline().parameters.watermark_last_loaded_timestamp, '''')
```
- Severity: Critical — incremental loads fail silently for BIGINT watermark entities

### 4.13 source_query Null/Not-Null Handling (F3 - Major)
Copy activity must handle three scenarios: (1) source_query is NULL → construct from schema.entity; (2) source_query is populated → use the custom query; (3) In both cases, append where_clause as AND condition if not null/empty.

```json
// GOOD — handles all three cases
@if(
  or(equals(item().source_query, ''), equals(item().source_query, null)),
  concat('SELECT * FROM [', item().source_schema, '].[', item().source_entity, ']',
    if(not(or(equals(item().where_clause, ''), equals(item().where_clause, null))),
       concat(' WHERE ', item().where_clause), '')),
  concat(item().source_query,
    if(not(or(equals(item().where_clause, ''), equals(item().where_clause, null))),
       concat(' AND ', item().where_clause), ''))
)

// BAD — assumes source_query is always populated
@concat(item().source_query, ' AND ', item().where_clause)

// BAD — ignores where_clause when source_query is null
@if(equals(item().source_query, null),
    concat('SELECT * FROM [', item().source_schema, '].[', item().source_entity, ']'),
    item().source_query)
```
- Severity: Major — missing data when source_query is null or where_clause is ignored

### 4.14 Stored Procedure Source Type Handling (F11 - Critical)
ADF pipelines must conditionally handle source_entity_type (TABLE vs STORED_PROCEDURE vs VIEW). When source_entity_type=STORED_PROCEDURE, different logic is required for watermark computation, copy activity source query, metadata updates, and parameter passing.

```json
// GOOD — conditional execution based on source_entity_type
{
    "name": "If Source Is Stored Procedure",
    "type": "IfCondition",
    "typeProperties": {
        "expression": {
            "value": "@equals(item().source_entity_type, 'STORED_PROCEDURE')",
            "type": "Expression"
        },
        "ifTrueActivities": [ /* SP-specific pipeline execution */ ],
        "ifFalseActivities": [ /* Table/View pipeline execution */ ]
    }
}

// BAD — same unconditional logic path for tables and stored procedures
// Tables and SPs share identical copy activity without source_entity_type check
```
- Severity: Critical — SP-specific logic (parameter passing, watermark computation) breaks if treated as table

### 4.15 SP Parameters from Config Table (F12 - Critical)
Stored procedure execution parameters must be configurable via metadata table (e.g., stored_procedure_config). Must support any number of parameters, any value including ADF expressions, constants, and pipeline parameters. Hardcoded SP parameters targeting one specific SP are not acceptable.

```json
// GOOD — SP parameters driven by config table lookup
// stored_procedure_config table has: sp_name, param_name, param_type, param_value, sp_load_type
{
    "name": "Lookup SP Parameters",
    "type": "Lookup",
    "typeProperties": {
        "source": {
            "sqlReaderStoredProcedureName": "[dbo].[usp_get_sp_parameters]",
            "storedProcedureParameters": {
                "source_entity_name": { "value": "@item().source_entity_name" },
                "sp_load_type": { "value": "@pipeline().parameters.load_type" }
            }
        }
    }
}

// BAD — hardcoded SP parameters
"storedProcedureParameters": {
    "start_date": { "value": "2017-01-01" },
    "end_date": { "value": "2050-01-01" }
}
```
- Severity: Critical — hardcoded parameters prevent reuse for new stored procedures

### 4.16 write_mode Conditional on is_initial_load_required (F15 - Major)
write_mode in audit activities must account for is_initial_load_required flag: overwrite when load_type='FULL' OR is_initial_load_required=True, append when incremental and is_initial_load_required=False.

```json
// GOOD — write_mode considers is_initial_load_required
"write_mode": {
    "value": "@if(or(equals(pipeline().parameters.load_type, 'FULL'), equals(pipeline().parameters.is_initial_load_required, true)), 'overwrite', 'append')",
    "type": "Expression"
}

// BAD — only checks load_type, ignores initial load flag
"write_mode": "@if(equals(pipeline().parameters.load_type, 'FULL'), 'overwrite', 'append')"
```
- Severity: Major — initial incremental load with append creates incorrect state

### 4.17 Scalable File Listing via Status-Based Tracking (F13 - Major)
For file-based sources, pipelines must use status-based tracking (query tracker table for PENDING/FAILED files) rather than scanning all directories with GetMetadata or Lookup. Directory-scanning does not scale.

```json
// GOOD — query tracker table for unprocessed files only
{
    "name": "Lookup Unprocessed Files",
    "type": "Lookup",
    "typeProperties": {
        "source": {
            "sqlReaderQuery": "SELECT file_path, file_name FROM file_processing_tracker WHERE status IN ('PENDING', 'FAILED') AND source_name = '@{pipeline().parameters.source_name}'"
        }
    }
}

// BAD — scan all directories (does not scale)
{
    "name": "Get All Landing Files",
    "type": "GetMetadata",
    "typeProperties": {
        "fieldList": ["childItems"],
        "dataset": { "referenceName": "ds_adls_landing" }
    }
}
```
- Severity: Major — directory scanning degrades with file count growth

### 4.18 Notification on Notebook FAILED Status Return (F38 - Major)
When a Databricks notebook returns a FAILED status (not just throws an exception), the ADF child pipeline must send a notification email. Check for both exception-based failures (Failed dependency) AND status-based failures (notebook returns "FAILED" string).

```json
// GOOD — check both exception and returned status
{
    "name": "If Notebook Status Failed",
    "type": "IfCondition",
    "typeProperties": {
        "expression": {
            "value": "@equals(activity('Run Notebook').output.runOutput.status, 'FAILED')",
            "type": "Expression"
        },
        "ifTrueActivities": [
            { "name": "Send Failure Notification", "type": "WebActivity" }
        ]
    }
}

// BAD — only handles exception, not returned FAILED status
// Only a Failed dependency handler exists; no check on notebook output status
```
- Severity: Major — silent failures when notebook returns FAILED without throwing exception

---

## 5. Error Handling

### Failure Notification — CRITICAL:
Every failure path (including inside ForEach activities) must have a Web Activity that sends a failure notification:

```json
{
    "name": "Send Failure Notification",
    "type": "WebActivity",
    "dependsOn": [
        { "activity": "...", "dependencyConditions": ["Failed"] }
    ]
}
```

Check for:
- Missing failure paths (activities with no `Failed` dependency handler)
- ForEach activities without internal failure handling
- Missing audit logging on failure paths

### Audit Activities:
- Must exist on BOTH success AND failure paths
- `write_mode` logic: `overwrite` for full, `append` for incremental

### Architecture Patterns:
- **Switch vs If-Else:** Use Switch activity for >2 cases
- **Authentication:** Managed Identity for Web Activity, Service Principal where MI is not available
- **Metadata-Driven:** Use `is_initial_load_required` from metadata (not Get Metadata activity)

---

## 6. Additional Checks

- Parse the full JSON structure — check nested activities inside ForEach, If, Switch, Until
- Check BOTH the pipeline definition AND any linked ARM template parameters
- Verify parameters defined at pipeline level are actually used (no orphan parameters)
- Check that dataset references use parameterized linked services
- If a pipeline is a child pipeline, verify it receives necessary parameters from parent

### Pipeline Performance via Audit (F8):
- Audit tables must capture `duration_seconds`. Pipeline execution times should be reviewable via audit tables for performance monitoring.

```json
// GOOD — audit stored procedure captures duration
"storedProcedureParameters": {
    "pipeline_name": { "value": "@pipeline().Pipeline" },
    "run_id": { "value": "@pipeline().RunId" },
    "start_time": { "value": "@pipeline().TriggerTime" },
    "end_time": { "value": "@utcNow()" },
    "duration_seconds": { "value": "@div(sub(ticks(utcNow()), ticks(pipeline().TriggerTime)), 10000000)", "type": "Expression" }
}

// BAD — audit table has no duration or timing columns
"storedProcedureParameters": {
    "pipeline_name": { "value": "@pipeline().Pipeline" },
    "run_id": { "value": "@pipeline().RunId" },
    "status": { "value": "SUCCESS" }
}
```
- Severity: Medium — missing duration data prevents performance monitoring and SLA tracking

### ADLS Container Must Be "landing" (F9):
- The ADLS container name for source data must always be `landing`.
- Subsequent folder pattern: `landing/<project_name>/<table_name>/<current_date>/`.

```json
// GOOD — correct container and folder structure
"folderPath": {
    "value": "landing/@{pipeline().parameters.project_name}/@{item().table_name}/@{formatDateTime(pipeline().TriggerTime, 'yyyy-MM-dd')}",
    "type": "Expression"
}

// BAD — wrong container name or flat folder structure
"folderPath": "raw/data/files"
"folderPath": "bronze/ingestion"
```
- Severity: Medium — non-standard container naming breaks downstream pipeline expectations

---

## 7. Best Recommended Practices

### 7.1 ForEach Optimization
- Always set `batchCount` explicitly — default is 1 (sequential), which is unnecessarily slow for independent items
- Recommended range: **5–10** for most workloads; higher values increase parallelism but also resource contention
- Use **Execute Pipeline** inside ForEach for complex multi-activity logic — keeps the inner pipeline testable independently

```json
// GOOD — explicit batch count
{
    "type": "ForEach",
    "typeProperties": {
        "isSequential": false,
        "batchCount": 10,
        "items": { "value": "@activity('Lookup Config').output.value" },
        "activities": [
            {
                "type": "ExecutePipeline",
                "typeProperties": {
                    "pipeline": { "referenceName": "pl_child_load_entity" },
                    "parameters": { "source_id": "@item().source_id" }
                }
            }
        ]
    }
}

// BAD — default sequential, complex logic inline
{
    "type": "ForEach",
    "typeProperties": {
        "items": { "value": "@activity('Lookup Config').output.value" },
        "activities": [
            { "type": "Copy", "name": "Copy Data" },
            { "type": "SqlServerStoredProcedure", "name": "Update Watermark" },
            { "type": "WebActivity", "name": "Send Notification" }
        ]
    }
}
```
- Severity: Medium — missing `batchCount` degrades pipeline throughput

### 7.2 Linked Service Parameterization
- Parameterize server names, database names, and container names in linked services — never hardcode environment-specific values
- Use **Key Vault linked service** for all credentials (connection strings, passwords, API keys)
- Use ARM parameter files (`*.parameters.json`) per environment to inject values at deployment time

```json
// GOOD — parameterized linked service
{
    "name": "sql_metadata_db",
    "properties": {
        "type": "AzureSqlDatabase",
        "typeProperties": {
            "connectionString": {
                "type": "AzureKeyVaultSecret",
                "store": { "referenceName": "kv_edl", "type": "LinkedServiceReference" },
                "secretName": "@linkedService().secret_name"
            }
        },
        "parameters": {
            "secret_name": { "type": "String" }
        }
    }
}

// BAD — hardcoded connection in linked service
{
    "name": "sql_metadata_db",
    "properties": {
        "typeProperties": {
            "connectionString": "Server=devserver.database.windows.net;Database=edl_metadata;..."
        }
    }
}
```
- Severity: Critical — hardcoded linked services prevent environment promotion

### 7.3 Modular Child Pipelines
- Each child pipeline should have **one responsibility** (e.g., load one entity, run one DQ check)
- Master pipeline orchestrates; child pipelines execute — master should contain no Copy or transform activities directly
- Pass all context via parameters; child pipelines should never depend on global state

```
// GOOD architecture
pl_master_landing_to_bronze (orchestrator)
  └── ForEach → pl_child_landing_to_bronze (one entity)
                  ├── Copy Activity
                  ├── Update Watermark
                  └── Audit Logging

// BAD architecture
pl_master_landing_to_bronze (everything inline)
  └── ForEach
        ├── Copy Activity
        ├── Stored Procedure 1
        ├── Stored Procedure 2
        ├── Web Activity (notification)
        └── Web Activity (audit)
```

### 7.4 Copy Activity Performance Tuning
- Set **parallel copy** explicitly (4–8) for large data volumes; default auto-tune may under-allocate
- Use **staging** (via Azure Blob) for cross-region or heterogeneous source-to-sink copies
- Let **DIU (Data Integration Units)** auto-tune unless you have measured a specific bottleneck — avoid hardcoding DIU values

```json
// GOOD — explicit parallel copy
{
    "type": "Copy",
    "typeProperties": {
        "parallelCopies": 8,
        "enableStaging": true,
        "stagingSettings": {
            "linkedServiceName": { "referenceName": "adls_staging" }
        }
    }
}

// BAD — hardcoded DIU, no staging for cross-region
{
    "type": "Copy",
    "typeProperties": {
        "dataIntegrationUnits": 2
    }
}
```

### 7.5 Diagnostic Settings
- Enable **Azure Monitor diagnostic settings** on every ADF instance
- Route logs to **Log Analytics workspace** for cross-pipeline querying and alerting
- ADF retains activity run logs for only **45 days** — diagnostic settings ensure long-term retention
- Severity: Medium — missing diagnostics hinders production troubleshooting

### 7.6 Secure Input/Output on Sensitive Activities
- Set `secureOutput: true` on any activity that retrieves secrets (Web Activity reading Key Vault, Lookup on credentials table)
- Set `secureInput: true` on downstream activities that consume secret values as parameters
- Prevents secrets from appearing in ADF monitoring, run logs, and Log Analytics

```json
// GOOD — secure output on KV read
{
    "name": "Get Secret From Key Vault",
    "type": "WebActivity",
    "policy": {
        "secureOutput": true
    },
    "typeProperties": {
        "url": "https://kv-edl.vault.azure.net/secrets/sql-password?api-version=7.0",
        "method": "GET",
        "authentication": { "type": "MSI", "resource": "https://vault.azure.net" }
    }
}

// BAD — secret visible in monitoring logs
{
    "name": "Get Secret From Key Vault",
    "type": "WebActivity",
    "typeProperties": {
        "url": "https://kv-edl.vault.azure.net/secrets/sql-password?api-version=7.0",
        "method": "GET",
        "authentication": { "type": "MSI", "resource": "https://vault.azure.net" }
    }
}
```
- Severity: Critical — secrets exposed in plaintext monitoring logs

### 7.7 Activity Dependencies
- Every activity must have an **explicit dependency** (except the first activity in the pipeline)
- No orphan activities — activities without dependencies or dependents are dead code
- Use `Completed` dependency condition for cleanup/notification activities that must always run regardless of upstream success or failure

```json
// GOOD — explicit dependency chain with always-run handler
{
    "name": "Log Audit Always",
    "dependsOn": [
        { "activity": "Copy Source Data", "dependencyConditions": ["Completed"] }
    ]
}

// BAD — orphan activity with no dependency
{
    "name": "Orphan Cleanup",
    "dependsOn": []
}
```

### 7.8 Network Security
- Deploy **private endpoints** for all data stores accessed by ADF: Azure SQL, ADLS Gen2, Key Vault
- Disable public network access on SQL Server, Storage Accounts, and Key Vault when private endpoints are configured
- Use **Self-Hosted Integration Runtime (SHIR)** inside a VNet for on-premises or private-network sources
- Severity: Major — public endpoints expose data to internet-based attacks

### 7.9 Managed Identity First
- Prefer **System-assigned Managed Identity** over Service Principals for ADF authentication
- Managed Identity eliminates credential rotation, secret storage, and expiry monitoring
- Use Service Principals only when Managed Identity is not supported by the target resource

```json
// GOOD — Managed Identity authentication
{
    "type": "WebActivity",
    "typeProperties": {
        "authentication": {
            "type": "MSI",
            "resource": "https://database.windows.net"
        }
    }
}

// LESS PREFERRED — Service Principal (requires secret rotation)
{
    "type": "WebActivity",
    "typeProperties": {
        "authentication": {
            "type": "ServicePrincipal",
            "servicePrincipalId": "@pipeline().parameters.sp_client_id",
            "servicePrincipalKey": {
                "type": "AzureKeyVaultSecret",
                "store": { "referenceName": "kv_edl" },
                "secretName": "sp-client-secret"
            }
        }
    }
}
```
