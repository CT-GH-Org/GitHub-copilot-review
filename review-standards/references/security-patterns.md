# Security Review Patterns

Domain-specific review patterns for security, compliance, and access control in a medallion architecture data lakehouse.

---

## 1. Secrets & Key Vault

### Scan Patterns — Flag Any of These:
```
password=, Password=, pwd=, PWD=
secret=, Secret=, api_key=, apikey=, API_KEY=
connectionstring=, ConnectionString=
Bearer eyJ, Basic dXNl, Authorization:
Server=...;User Id=...;Password=
AccountKey=, SharedAccessSignature=
client_secret=, tenant_id= (with actual values)
```

### Azure Key Vault Requirements:
- ALL secrets must be stored in Azure Key Vault
- Never log, print, or display secret values
- Never commit secrets to source control

### Databricks Secret Scope:
```python
# GOOD — from Key Vault via secret scope
connection_string = dbutils.secrets.get(scope="kv-scope", key="sql-connection-string")
api_key = dbutils.secrets.get(scope="kv-scope", key="api-key")

# BAD — hardcoded credentials
connection_string = "Server=myserver;Password=P@ssw0rd123;"
api_key = "sk-abc123def456"
```

### ADF Key Vault Integration:
```json
// GOOD — Key Vault reference
"type": "AzureKeyVaultSecret",
"store": { "referenceName": "ls_kv_edl", "type": "LinkedServiceReference" },
"secretName": "sql-connection-string"

// BAD — hardcoded in ADF
"connectionString": "Server=myserver;Password=abc123"
```

### ADF Web Activity for Secrets:
- Use Web Activity with Managed Identity to read Key Vault secrets
- Or use Key Vault linked service reference

### AzureDataBricks App Permissions:
- Read-only access to Key Vault (Key Vault Secrets User role)
- Must NOT have write/delete permissions on KV secrets

---

## 2. Authentication

### No User Credentials:
```python
# BAD — individual user credentials
username = "john.doe@company.com"
password = "..."

# BAD — hardcoded service principal credentials
client_id = "12345-abcde-..."
client_secret = "secret-value"
```

### Managed Identity:
```json
// GOOD — Managed Identity for ADF Web Activities
{
    "type": "WebActivity",
    "typeProperties": {
        "authentication": {
            "type": "MSI",
            "resource": "https://vault.azure.net"
        }
    }
}

// BAD — Basic auth
{
    "authentication": {
        "type": "Basic",
        "username": "admin",
        "password": "..."
    }
}
```

### OAuth2 for API Authentication:
```python
# GOOD — OAuth2 token-based
token = get_oauth2_token(client_id, client_secret_from_kv, token_url)
headers = {"Authorization": f"Bearer {token}"}

# BAD — API key in URL
url = f"https://api.example.com/data?api_key=abc123"
```

### HTTPS Required:
```python
# GOOD
url = "https://api.example.com/v2/data"

# BAD — unencrypted
url = "http://api.example.com/v2/data"
```

---

## 3. Access Control

### Least Privilege:
- Database roles for grouping user access (not individual user grants)
- Service principals with minimum required permissions
- BU teams: limited access via service principals scoped to their data

```sql
-- GOOD — role-based access
CREATE ROLE edl_reader;
GRANT SELECT ON SCHEMA::bronze TO edl_reader;

-- BAD — individual user grants with excessive permissions
GRANT ALL ON DATABASE::edl_db TO [john.doe@company.com];
```

### Workspace Boundaries:
- BU notebooks must NOT reference DA workspace resources
- Check for cross-workspace resource access:
  - DA storage account names in BU notebooks
  - DA key vault references in BU code
  - DA service principal credentials in BU workspace

### Separate Config/Audit Tables:
- When BU and DA are not co-managed, they should have separate config and audit tables

---

## 4. Data Protection

### Unity Catalog Governance:
- Tables should be registered in Unity Catalog
- Data lineage tracking enabled
- Access policies enforced at catalog level

### Encryption:
- Data encrypted at rest (Azure default for ADLS/SQL — verify not disabled)
- Data encrypted in transit (HTTPS, TLS)
- No unencrypted data transfers

### Audit Trails:
- All data access changes logged
- Pipeline executions audited
- Configuration changes tracked

### PII Handling:
- Identify columns that may contain PII (names, emails, SSNs, phone numbers, addresses)
- Verify PII columns have appropriate masking or encryption
- PII must NOT appear in logs, error messages, or comments

```python
# BAD — PII in error log
logger.error(f"Failed to process customer: {customer_name}, SSN: {ssn}")

# GOOD — no PII in logs
logger.error(f"Failed to process customer_id: {customer_id}")
```

### Row Filters and Column Masks:
```sql
-- PII protection in Unity Catalog
ALTER TABLE silver.customer
SET ROW FILTER pii_filter ON (customer_id);

ALTER TABLE silver.customer
ALTER COLUMN ssn SET MASK mask_ssn;
```

---

## 5. SQL Injection Prevention

### Parameterized Queries:
```python
# BAD — SQL injection risk
query = f"SELECT * FROM metadata_config WHERE source_name = '{source_name}'"
spark.sql(query)

# GOOD — parameterized
query = "SELECT * FROM metadata_config WHERE source_name = ?"
spark.sql(query, [source_name])

# ALSO GOOD — DataFrame API
df = spark.table("metadata_config").filter(col("source_name") == source_name)
```

```sql
-- BAD — dynamic SQL without parameterization
EXEC('SELECT * FROM ' + @TableName)

-- GOOD — parameterized dynamic SQL
EXEC sp_executesql N'SELECT * FROM metadata_config WHERE source_id = @id',
    N'@id INT', @id = @SourceID
```

---

## 6. Sensitive Data in Code

### No Sensitive Data In:
- Code comments
- Variable names that reveal security architecture
- Error messages that expose internal structure
- Log statements that include credentials or PII
- Git commit messages
- Configuration files checked into source control

```python
# BAD — sensitive values in config
config = {
    "server": "production-server.database.windows.net",
    "admin_password": "P@ssw0rd",
    "api_key": "sk-live-..."
}

# GOOD — references to Key Vault secrets
config = {
    "server_secret_name": "sql-server-name",
    "password_secret_name": "sql-admin-password",
    "api_key_secret_name": "api-key"
}
```

### .gitignore Verification:
- Sensitive files must be excluded from version control
- Check for `.env`, credentials files, key files, certificate files

---

## 7. Best Recommended Practices

### 7.1 Private Endpoints
- Deploy **private endpoints** for all Azure resources accessed by the EDL: Azure SQL, ADLS Gen2, Key Vault, Databricks workspace
- **Disable public network access** on resources once private endpoints are configured
- Private endpoints ensure traffic stays on the Azure backbone and never traverses the public internet

```json
// GOOD — private endpoint configured, public access disabled
{
    "resource": "sql_metadata_db",
    "private_endpoint": "pe-sql-metadata-edl",
    "public_network_access": "Disabled"
}

// BAD — public network access enabled
{
    "resource": "sql_metadata_db",
    "public_network_access": "Enabled"
}
```
- Severity: Major — public endpoints expose data stores to internet-based attacks

### 7.2 Credential Lifecycle Management
- Prefer **Managed Identity** over Service Principals — eliminates credential rotation entirely
- When Service Principals are required, rotate secrets every **90 days**
- Set Key Vault secret expiry dates and configure **Azure Monitor alerts** for upcoming expirations
- Never use long-lived credentials (>1 year) for any service

```python
# GOOD — Managed Identity (no credentials to manage)
# ADF: authentication.type = "MSI"
# Databricks: Unity Catalog with MI

# WHEN SP IS REQUIRED — track expiry
# Key Vault secret with expiry:
#   Name: sp-edl-client-secret
#   Expiry: 90 days from creation
#   Alert: Azure Monitor at 14 days before expiry

# BAD — never-expiring Service Principal secret
# client_secret created 2 years ago, no expiry set, no rotation schedule
```

### 7.3 Column-Level Masking
- Apply **Unity Catalog column masks** on all PII columns (names, emails, SSNs, phone numbers, addresses)
- Create centralized masking functions that can be reused across tables
- Masking functions should return partial values for authorized users and fully masked values for others

```sql
-- GOOD — centralized masking function
CREATE FUNCTION mask_email(email STRING)
RETURNS STRING
RETURN CASE
    WHEN IS_MEMBER('pii_authorized')
        THEN email
    ELSE CONCAT(LEFT(email, 2), '***@***.***')
END;

-- Apply to table
ALTER TABLE catalog.silver.customer
ALTER COLUMN customer_email SET MASK mask_email;

-- GOOD — SSN masking
CREATE FUNCTION mask_ssn(ssn STRING)
RETURNS STRING
RETURN CASE
    WHEN IS_MEMBER('pii_authorized') THEN ssn
    ELSE CONCAT('***-**-', RIGHT(ssn, 4))
END;
```

### 7.4 Row-Level Security
- Implement **Unity Catalog row filters** to restrict data access by user group or business region
- Row filters are enforced at the catalog level — users cannot bypass them via direct table access

```sql
-- GOOD — row filter by business unit
CREATE FUNCTION region_filter(region STRING)
RETURNS BOOLEAN
RETURN CASE
    WHEN IS_MEMBER('admin_group') THEN TRUE
    WHEN IS_MEMBER('bu_west') AND region = 'West' THEN TRUE
    WHEN IS_MEMBER('bu_east') AND region = 'East' THEN TRUE
    ELSE FALSE
END;

ALTER TABLE catalog.gold.sales
SET ROW FILTER region_filter ON (sales_region);
```

### 7.5 Security Monitoring and Alerting
- Enable **Azure Monitor** and route security-relevant logs to a central Log Analytics workspace
- Enable **Databricks audit logs** and forward to the same Log Analytics workspace
- Configure alerts for anomalous patterns: unusual login locations, bulk data downloads, privilege escalation, failed authentication spikes

```
-- Key alerts to configure:
1. Failed login attempts > 5 in 10 minutes → High priority
2. New Service Principal created → Medium priority
3. Key Vault secret accessed by unknown identity → High priority
4. Databricks cluster created with public IP → Critical priority
5. Large data export (>1GB) to external location → High priority
```

### 7.6 Data Classification Tags
- Tag all columns in Unity Catalog with classification labels: `PII`, `SENSITIVE`, `CONFIDENTIAL`, `PUBLIC`
- Classification drives masking policies, access controls, and compliance reporting
- Unclassified columns should default to `CONFIDENTIAL` until reviewed

```sql
-- GOOD — classification tags in Unity Catalog
ALTER TABLE catalog.silver.customer
ALTER COLUMN customer_name SET TAGS ('classification' = 'PII');

ALTER TABLE catalog.silver.customer
ALTER COLUMN customer_email SET TAGS ('classification' = 'PII');

ALTER TABLE catalog.silver.customer
ALTER COLUMN customer_segment SET TAGS ('classification' = 'PUBLIC');

-- Tag at table level for overall sensitivity
ALTER TABLE catalog.silver.customer
SET TAGS ('data_sensitivity' = 'HIGH');
```

### 7.7 TLS Enforcement
- All connections must use **TLS 1.2 or higher**
- Flag any `http://` URL as a Critical severity finding — all traffic must use `https://`
- Verify TLS minimum version is set on Azure SQL Server, Storage Accounts, and Key Vault

```python
# GOOD — HTTPS enforced
api_url = "https://api.source-system.com/v2/data"

# BAD — unencrypted HTTP (Critical severity)
api_url = "http://api.source-system.com/v2/data"
```

```json
// GOOD — TLS 1.2 minimum on Azure SQL
{
    "resource": "sql_metadata_server",
    "minimalTlsVersion": "1.2"
}

// BAD — TLS 1.0 allowed
{
    "resource": "sql_metadata_server",
    "minimalTlsVersion": "1.0"
}
```
- Severity: Critical — unencrypted connections expose data in transit

### 7.8 Diagnostic Settings on All Azure Resources
- Enable **diagnostic settings** on every Azure resource: ADF, SQL Server, ADLS, Key Vault, Databricks
- Route all diagnostic logs to a **central Log Analytics workspace**
- Set retention to **90 days minimum** for compliance and troubleshooting
- Missing diagnostic settings means security incidents cannot be investigated

```json
// GOOD — diagnostic settings enabled
{
    "resource": "adf_edl_production",
    "diagnosticSettings": {
        "logs": ["ActivityRuns", "PipelineRuns", "TriggerRuns"],
        "destination": "la-edl-central",
        "retentionDays": 90
    }
}
```
- Severity: Major — missing diagnostics prevents incident investigation

### 7.9 Compliance Mapping
- Map EDL architecture components to compliance framework controls: **SOC 2**, **ISO 27001**, **GDPR** (if applicable)
- Document which EDL component satisfies which control (e.g., Key Vault = SOC 2 CC6.1 encryption)
- Schedule **quarterly reviews** of compliance alignment — architecture changes may introduce gaps

```
-- Example compliance mapping:
| EDL Component         | SOC 2 Control | ISO 27001 Control |
|---|---|---|
| Key Vault secrets     | CC6.1         | A.10.1.1          |
| Unity Catalog RBAC    | CC6.3         | A.9.4.1           |
| Audit logging         | CC7.2         | A.12.4.1          |
| Private endpoints     | CC6.6         | A.13.1.1          |
| TLS enforcement       | CC6.7         | A.10.1.1          |
| Data classification   | CC6.5         | A.8.2.1           |
```

### 7.10 Secure Development Practices
- Maintain a comprehensive `.gitignore` that excludes: `.env`, `*.pem`, `*.pfx`, `*.key`, `credentials.json`, `local.settings.json`, `*.parameters.json` (ARM parameter files with secrets)
- Enable **CI/CD secret scanning** (e.g., GitHub Advanced Security, Azure DevOps credential scanner) to block commits containing secrets
- Never commit ARM parameter files that contain actual secret values — use Key Vault references instead

```
# GOOD — .gitignore entries for EDL project
.env
*.pem
*.pfx
*.key
credentials.json
local.settings.json
**/arm/*.parameters.*.json
**/*.secret.*

# CI/CD — enable secret scanning
# GitHub: Settings > Code security > Secret scanning = Enabled
# Azure DevOps: Install "Credential Scanner" task in build pipeline
```

```json
// GOOD — ARM parameter references Key Vault, not actual secret
{
    "parameters": {
        "sqlAdminPassword": {
            "reference": {
                "keyVault": { "id": "/subscriptions/.../Microsoft.KeyVault/vaults/kv-edl" },
                "secretName": "sql-admin-password"
            }
        }
    }
}

// BAD — actual secret in ARM parameter file (Critical severity)
{
    "parameters": {
        "sqlAdminPassword": {
            "value": "P@ssw0rd123!"
        }
    }
}
```
- Severity: Critical — secrets in source control are permanently exposed in git history
