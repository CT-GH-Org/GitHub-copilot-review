# Standard Operating Procedure
# ATCO EDL Automated Code Review Utility

| Field | Value |
|---|---|
| **Document ID** | SOP-EDL-CR-001 |
| **Version** | 1.0 |
| **Effective Date** | 2026-03-20 |
| **Classification** | ATCO Confidential |
| **Prepared By** | Data & Analytics Engineering Team |
| **Approved By** | — |

---

## Document History

| Version | Date | Author | Description |
|---|---|---|---|
| 1.0 | 2026-03-20 | D&A Engineering | Initial version — covers all 5 review domains, 229 checks, 30 ATCO-specific feedback-derived patterns |

---

## Table of Contents

1. [Purpose](#1-purpose)
2. [Scope](#2-scope)
3. [Audience](#3-audience)
4. [Prerequisites](#4-prerequisites)
5. [Utility Architecture](#5-utility-architecture)
6. [How to Run a Code Review](#6-how-to-run-a-code-review)
7. [Understanding the Review Report](#7-understanding-the-review-report)
8. [Follow-Up Reviews (Progress Tracking)](#8-follow-up-reviews-progress-tracking)
9. [Review Checklist Summary](#9-review-checklist-summary)
10. [How to Add or Modify Checks](#10-how-to-add-or-modify-checks)
11. [Roles and Responsibilities](#11-roles-and-responsibilities)
12. [Standard Review Workflow](#12-standard-review-workflow)
13. [Severity Definitions and SLA](#13-severity-definitions-and-sla)
14. [Troubleshooting](#14-troubleshooting)
15. [File Map and Architecture Reference](#15-file-map-and-architecture-reference)
16. [Appendix A — Complete Check Count by Domain](#appendix-a--complete-check-count-by-domain)
17. [Appendix B — Feedback Integration Log](#appendix-b--feedback-integration-log)

---

## 1. Purpose

This SOP defines the standard process for using the ATCO EDL Automated Code Review Utility to review all code artifacts in the Enterprise Data Lakehouse (EDL) before they are promoted to production.

The utility automates the enforcement of **229 review checks** across 5 domains — ADF Pipelines, Databricks Notebooks, SQL Scripts, Metadata Configuration, and Security — including **30 checks derived directly from ATCO SIT/UAT feedback** to eliminate repetitive manual review cycles.

### Goals

- Ensure every code submission meets ATCO EDL standards **before** reaching manual review
- Reduce manual review cycle time by catching standard violations automatically
- Provide consistent, reproducible review results regardless of reviewer
- Track resolution progress across review rounds via follow-up reports
- Serve as the single source of truth for EDL coding standards

---

## 2. Scope

### In Scope

| Artifact Type | File Patterns | Review Domain |
|---|---|---|
| ADF Pipeline JSON | `*.json` (containing `Microsoft.DataFactory`) | ADF Pipeline Reviewer |
| ADF Linked Services | `linkedService/*.json` | ADF Pipeline Reviewer |
| ADF Datasets | `dataset/*.json` | ADF Pipeline Reviewer |
| ADF Triggers | `trigger/*.json` | ADF Pipeline Reviewer |
| ADF ARM Parameters | `arm_template_parameters*.json` | ADF Pipeline + Security Reviewer |
| ADF Integration Runtimes | `integrationRuntime/*.json` | ADF Pipeline Reviewer |
| Databricks Python Notebooks | `*.py` (containing spark, dbutils, delta) | Databricks Notebook Reviewer |
| Databricks Jupyter Notebooks | `*.ipynb` | Databricks Notebook Reviewer |
| SQL DDL Scripts | `*.sql` (CREATE/ALTER TABLE) | SQL Schema Reviewer |
| SQL Stored Procedures | `*.sql` (CREATE PROCEDURE) | SQL Schema Reviewer |
| SQL Views | `*.sql` (CREATE VIEW) | SQL Schema Reviewer |
| Metadata Config Tables | Control table DDL, SPs, config data | Metadata Config Reviewer |
| All of the above | All file types | Security & Compliance Reviewer |

### Out of Scope

- Oracle/GCP/AWS cloud platform artifacts
- Power BI reports and dashboards
- Terraform/Infrastructure-as-Code (unless a new specialist prompt is created — see Section 10.4)
- Code deployed prior to the creation of this utility

---

## 3. Audience

| Role | How They Use This SOP |
|---|---|
| **Developers / Vendors** | Run reviews before submitting PRs; fix flagged issues; understand what checks are enforced |
| **Data Engineers** | Run reviews on their Databricks notebooks and ADF pipelines during development |
| **Sr. Data Architects** | Review reports, validate severity classifications, approve/reject submissions |
| **D&A Governance Specialists** | Audit review coverage, verify compliance checks, extend security patterns |
| **Project Leads** | Track review progress across rounds, monitor resolution rates |
| **New Team Members** | Understand EDL coding standards and how to extend the utility |

---

## 4. Prerequisites

### 4.1 Software Requirements

| Requirement | Details |
|---|---|
| **GitHub Copilot for VS Code** | Must be installed and have Agent mode enabled — this is the runtime for the utility |
| **Claude Opus model in Copilot** | Switch model to Claude Opus (4.6) in Copilot Chat for best results |
| **Git** | Repository must be cloned locally |
| **GitHub CLI (gh)** | Required only for PR-based reviews |

### 4.2 Repository Setup

Clone the repository:

```bash
git clone <repository-url>
cd ATCO_EDL_INGESTION_COPILOT
```

Verify the utility structure exists:

```bash
ls .github/prompts/          # Should show 8 .prompt.md files
ls review-standards/references/  # Should show 5 pattern .md files
```

### 4.3 Code Placement

Place the code to be reviewed in the `temp/` directory:

```
temp/
├── adf/
│   └── pl_master_source/
│       ├── pipeline/*.json
│       ├── linkedService/*.json
│       ├── dataset/*.json
│       └── ...
├── databricks/
│   └── project_name/
│       ├── config/constants.py
│       ├── utils/*.py
│       └── src/**/*.py
└── sql/
    ├── ddl/*.sql
    └── stored_procedures/*.sql
```

---

## 5. Utility Architecture

### 5.1 Component Overview

```
┌────────────────────────────────────────────────────────────┐
│           code-reviewer.prompt.md (Orchestrator)            │
│  Discovers files → Classifies → Reviews domains → Reports   │
└────────────┬──────────┬──────────┬──────────┬──────────────┘
             │          │          │          │
             ▼          ▼          ▼          ▼       (sequential)
    ┌────────────┐ ┌────────┐ ┌───────┐ ┌──────────┐
    │ADF Domain  │ │Databr. │ │ SQL   │ │ Metadata │
    │  Review    │ │Domain  │ │Domain │ │ Domain   │
    │            │ │Review  │ │Review │ │ Review   │
    └─────┬──────┘ └───┬────┘ └──┬────┘ └────┬─────┘
          │             │         │            │
          ▼             ▼         ▼            ▼
    ┌──────────┐  ┌──────────┐ ┌────────┐ ┌──────────┐
    │adf-      │  │databricks│ │sql-    │ │metadata- │
    │patterns  │  │-patterns │ │patterns│ │patterns  │
    │.md       │  │.md       │ │.md     │ │.md       │
    └──────────┘  └──────────┘ └────────┘ └──────────┘

    ┌────────────────────────────────────────────────┐
    │         Security Domain Review                  │
    │      (Always runs as final domain step)         │
    │          Reads: security-patterns.md            │
    └────────────────────────────────────────────────┘
```

### 5.2 How It Works (Step by Step)

1. **User attaches** `code-reviewer.prompt.md` in GitHub Copilot Chat (Agent mode) and types the review request
2. **Orchestrator (`code-reviewer.prompt.md`)** scans the target directory and classifies file types
3. **Orchestrator detects** whether a previous review exists (for follow-up tracking)
4. **Domain reviews run sequentially** — ADF → Databricks → SQL → Metadata → Security, each reading its pattern file
5. **Each domain review** checks the code against all rules and builds a findings list
6. **Orchestrator consolidates** findings, de-duplicates, classifies severity
7. **Report is saved** to `review/{type}/{type}_{timestamp}.md`

### 5.3 Knowledge Sources (Single Source of Truth)

| What | Where | Who Reads It |
|---|---|---|
| ADF-specific review rules (76 checks) | `review-standards/references/adf-patterns.md` | Orchestrator (ADF domain step) |
| Databricks-specific rules (57 checks) | `review-standards/references/databricks-patterns.md` | Orchestrator (Databricks domain step) |
| SQL-specific rules (33 checks) | `review-standards/references/sql-patterns.md` | Orchestrator (SQL domain step) |
| Metadata framework rules (33 checks) | `review-standards/references/metadata-patterns.md` | Orchestrator (Metadata domain step) |
| Security rules (30 checks) | `review-standards/references/security-patterns.md` | Orchestrator (Security domain step) |
| Orchestration, report format, severity | `code-reviewer.prompt.md` | GitHub Copilot (loaded by user) |
| Cross-cutting standards | `copilot-instructions.md` (auto-loaded) | All prompt files |

---

## 6. How to Run a Code Review

### 6.1 Method A — Using the Prompt File

1. Open **GitHub Copilot Chat** in VS Code
2. Switch to **Agent mode**
3. Select **Claude Opus** as the model
4. Click **`+`** (Add Context) and attach `.github/prompts/code-reviewer.prompt.md`
5. Type your review request (see examples in Methods B–D below)

Copilot runs the full review pipeline using the attached prompt as its instructions.

### 6.2 Method B — Natural Language Request

```
Review all code in temp/adf/pl_master_source/
```

```
Review the Databricks notebooks in temp/databricks/dummy_erp_hr/
```

```
Review all SQL scripts in temp/sql/
```

```
Review everything in temp/
```

### 6.3 Method C — PR-Based Review

```
Review PR #42
```

Claude fetches the PR diff, identifies changed files, and reviews only the changes.

### 6.4 Method D — Targeted Review

```
Check the SQL stored procedures in temp/sql/ for naming and GETUTCDATE compliance
```

```
Review temp/databricks/silver_employees.py for SCD2 compliance only
```

### 6.5 What Happens During a Review

| Step | What Happens | Duration |
|---|---|---|
| 1. Discovery | Files scanned and classified by type | ~5 seconds |
| 2. Previous Review Detection | Checks `review/` folder for matching prior reports | ~5 seconds |
| 3. Pattern Load | Reads applicable `review-standards/references/*.md` files | ~10 seconds |
| 4. Domain Reviews | ADF → Databricks → SQL → Metadata → Security (sequential) | 2-4 minutes per domain |
| 5. Consolidation | Findings merged, de-duplicated, severity classified | ~15 seconds |
| 6. Report Save | Markdown report saved to `review/{type}/` | ~5 seconds |

**Typical total time:** 8-15 minutes for a full mixed review; 2-5 minutes for a single-domain review.

---

## 7. Understanding the Review Report

### 7.1 Report Location

Reports are saved as markdown files:

```
review/
├── adf/
│   └── adf_20260320_143022.md
├── databricks/
│   └── databricks_20260320_150115.md
├── sql/
│   └── sql_20260320_160430.md
├── metadata/
│   └── metadata_20260320_170000.md
└── mixed/
    └── mixed_20260320_180000.md    (when multiple types in one review)
```

**Naming convention:** `{type}_{YYYYMMDD_HHmmss_IST}.md`

### 7.2 Report Sections (First Review)

| Section | What It Contains |
|---|---|
| **Header** | Files reviewed, date, agents used, review type |
| **Executive Summary** | Total issues by severity, APPROVE / APPROVE WITH CHANGES / REQUIRES REWORK recommendation |
| **Critical Issues** | Each with: category tag, file:line, Current/Required/Reference, Code Snippet, Suggested Fix |
| **Major Issues** | Same format as Critical |
| **Medium Issues** | Same format as Critical |
| **Minor Issues** | Same format; Code Snippet optional |
| **Per-File Breakdown** | Table with every file listed individually showing issue counts |
| **What Passed** | At least 5 specific positive findings with evidence |
| **Review Checklist Status** | 14-category PASS/FAIL table with detailed notes |
| **Summary** | Total counts, recommendation, numbered priority remediation order |

### 7.3 How to Read an Issue

```
3. **[Hardcoded Value]** `ls_azure_sql_db.json:7` — Environment-specific server name hardcoded
   - **Current:** connectionString contains 'sql-contoso-prod-001.database.windows.net'
   - **Required:** Connection string via Key Vault or ARM template parameter
   - **Reference:** adf-patterns.md Section 7.2
   - **Code Snippet:**
     ```json
     "connectionString": "...data source=sql-contoso-prod-001.database.windows.net..."
     ```
   - **Suggested Fix:**
     ```json
     "connectionString": {
         "type": "AzureKeyVaultSecret",
         "store": { "referenceName": "kv_edl" },
         "secretName": "sql-metadata-connection-string"
     }
     ```
```

| Field | How to Use It |
|---|---|
| **[Category]** | Tells you what type of violation (Hardcoded Value, Naming, SQL Injection, etc.) |
| **file:line** | Exact location — open the file and go to that line |
| **Current** | What the code does NOW (the problem) |
| **Required** | What it SHOULD do (the fix) |
| **Reference** | Which rule from which pattern file — for context on WHY |
| **Code Snippet** | Actual violating code copied from the file |
| **Suggested Fix** | Copy-pasteable corrected code |

---

## 8. Follow-Up Reviews (Progress Tracking)

### 8.1 How Follow-Up Detection Works

When you re-review the same files, the utility automatically:

1. Scans `review/{type}/*.md` for previous reports
2. Compares file basenames (50%+ overlap = match)
3. Produces a **follow-up report** instead of a standalone report

### 8.2 Follow-Up Report Adds These Sections

| Section | What It Shows |
|---|---|
| **Executive Summary Table** | Previous Total → Resolved → Still Open → New → Current Total → Resolution Rate → Trend |
| **Resolved Issues** | What was fixed and how |
| **Still Open Issues** | Tagged `[STILL OPEN]` with First Reported date and Days Open count |
| **New Issues** | Tagged `[NEW]` — found for first time |
| **Trend Analysis** | Per-severity direction arrows (↓ improving, → stable, ↑ degrading) |
| **Checklist Trend** | Previous vs Current status with FIXED/REGRESSED indicators |

### 8.3 Trend Definitions

| Trend | Condition |
|---|---|
| **IMPROVING** | Resolution rate ≥ 30% AND new issues ≤ still-open issues |
| **STABLE** | Resolution rate < 30% AND new issues ≤ resolved issues |
| **DEGRADING** | New issues > previous total OR (resolution rate < 10% AND new > still-open) |

### 8.4 Forcing Comparison Against a Specific Review

```
Review temp/adf/pl_master_gold/ and compare against review/adf/adf_20260305_125136.md
```

---

## 9. Review Checklist Summary

The utility enforces **229 checks** across 5 domains:

| Domain | Check Count | Pattern File |
|---|---|---|
| ADF Pipeline | 76 | `review-standards/references/adf-patterns.md` |
| Databricks Notebook | 57 | `review-standards/references/databricks-patterns.md` |
| SQL Scripts | 33 | `review-standards/references/sql-patterns.md` |
| Metadata / Config | 33 | `review-standards/references/metadata-patterns.md` |
| Security & Compliance | 30 | `review-standards/references/security-patterns.md` |
| **Total** | **229** | |

### By Severity

| Severity | Count | Meaning |
|---|---|---|
| Critical | ~65 | Must fix before merge — causes production failures, data loss, or security vulnerabilities |
| Major | ~105 | Should fix — breaks standards, will be flagged in manual review |
| Medium | ~45 | Recommended — best practice improvements |
| Minor | ~14 | Suggestions — style and readability |

The complete check-by-check inventory is available in:
```
temp/feedbacks/ATCO_EDL_Complete_Review_Checklist.xlsx
```

---

## 10. How to Add or Modify Checks

### 10.1 Quick Reference — Which Method to Use

| Goal | Method | Time | Skill Needed |
|---|---|---|---|
| Add one review rule to existing domain | Edit pattern file | 2 min | Basic markdown |
| Set severity for a cross-domain rule | Edit `code-reviewer.prompt.md` severity section | 3 min | Basic markdown |
| Add a universal standard | Edit `copilot-instructions.md` | 5 min | Basic markdown |
| Change how a domain review works | Edit the specialist prompt file | 10 min | Understand prompt workflow |
| Review a new artifact type | Create new prompt + pattern file | 15 min | Understand prompt framework |
| Large new rule set for existing domain | Create new reference file | 10 min | Basic markdown |
| Change overall review workflow | Edit `code-reviewer.prompt.md` workflow sections | 15 min | Understand orchestration |
| Don't want to edit files | Tell Copilot in natural language | 1 min | Natural language only |

### 10.2 Adding a Check to an Existing Pattern File

**This is the most common operation.** Here's the step-by-step:

1. **Identify the domain:** ADF, Databricks, SQL, Metadata, or Security

2. **Open the pattern file:**
   ```
   review-standards/references/{domain}-patterns.md
   ```

3. **Find the right section** (Naming, Parameterization, Feedback-Derived, Best Practices, etc.)

4. **Add your check using this template:**
   ````markdown
   ### X.XX Check Name (Severity)
   One-line description of what this check validates and why.

   ```json   (or ```python or ```sql)
   // GOOD — compliant pattern
   "example": "compliant_value"

   // BAD — violating pattern
   "example": "non_compliant_value"
   ```
   - Severity: Critical / Major / Medium / Minor — impact statement
   ````

5. **Save the file.** Next review run automatically enforces the new rule.

### 10.3 Adding via Natural Language (No File Editing)

Simply tell Claude:

```
Add a new check to ADF patterns: all WebActivity calls to Logic App must include
a timeout of 5 minutes maximum. Make it a Major severity.
```

Claude will:
- Read the current adf-patterns.md
- Find the right section
- Add the check with GOOD/BAD examples
- Confirm what was added

### 10.4 Creating a New Specialist Prompt

For reviewing artifact types not currently covered (e.g., Terraform, Power BI, dbt):

1. **Create the prompt file** at `.github/prompts/review-{name}.prompt.md` with the standard frontmatter:
   ```yaml
   ---
   mode: 'agent'
   description: 'Reviews [type] for ATCO EDL compliance.'
   tools:
     - read_file
     - list_dir
     - find_files
     - search_files
     - run_terminal_command
     - create_file
   ---
   ```

2. **Create the pattern file** at `review-standards/references/{name}-patterns.md`

3. **Register in `code-reviewer.prompt.md`** — add to the domain dispatch section in Step 3 and file detection in Step 2

### 10.5 Rules for Adding Checks

| Rule | Rationale |
|---|---|
| Every check MUST have a GOOD and BAD example | Agents need concrete patterns to match against |
| Every check MUST have a severity classification | Determines report ordering and remediation priority |
| Use existing section numbering (e.g., 4.19 after 4.18) | Maintains sequential ordering |
| Do NOT duplicate checks across pattern files | Each rule lives in ONE file; agents handle overlap via de-duplication |
| Test the check by running a review after adding | Verify the agent catches the pattern correctly |

---

## 11. Roles and Responsibilities

| Role | Responsibility |
|---|---|
| **Developer / Vendor** | Run `code-reviewer.prompt.md` via Copilot Chat before submitting PR. Fix all Critical and Major issues. Provide explanation for any unfixed items. |
| **Code Reviewer (D&A Team)** | Validate automated review report. Verify suggested fixes are correct. Approve or request changes. |
| **Sr. Data Architect** | Review Critical findings. Make severity override decisions. Approve exceptions. |
| **Utility Maintainer** | Add new checks from feedback. Keep pattern files current. Onboard new artifact types. Verify agent behavior. |
| **D&A Governance** | Audit security checks coverage. Verify compliance mapping. Review access control findings. |

---

## 12. Standard Review Workflow

### 12.1 First-Time Review Process

```
Developer                    Utility                      Reviewer
    │                           │                            │
    │  1. Place code in temp/   │                            │
    │─────────────────────────► │                            │
    │                           │                            │
    │  2. Run code-reviewer     │                            │
    │     .prompt.md in Copilot │                            │
    │─────────────────────────► │                            │
    │                           │  3. Discover + classify    │
    │                           │  4. Domain reviews         │
    │                           │     (sequential)           │
    │                           │  5. Review all files       │
    │                           │  6. Consolidate + save     │
    │  7. Read report           │                            │
    │◄───────────────────────── │                            │
    │                           │                            │
    │  8. Fix Critical + Major  │                            │
    │                           │                            │
    │  9. Re-run review         │                            │
    │─────────────────────────► │                            │
    │                           │  10. Follow-up report      │
    │                           │      (shows resolved/open) │
    │  11. Submit PR            │                            │
    │────────────────────────────────────────────────────────►│
    │                           │                            │
    │                           │  12. Reviewer validates    │
    │                           │      report + code         │
    │  13. Final approval       │                            │
    │◄────────────────────────────────────────────────────────│
```

### 12.2 Acceptance Criteria by Severity

| Severity | Requirement for PR Approval |
|---|---|
| **Critical** | ALL must be resolved. Zero tolerance. |
| **Major** | ALL should be resolved. Exceptions require Sr. Architect written approval with justification. |
| **Medium** | Should be resolved. May be deferred to next sprint with tracking ticket. |
| **Minor** | Optional. Acknowledged in review comments. |

### 12.3 Review Cadence

| Phase | When to Run |
|---|---|
| **During Development** | Developer runs as self-check before PR |
| **PR Submission** | Automated review attached to PR |
| **After Fix Round** | Follow-up review to track resolution |
| **Before UAT** | Full review on final codebase |
| **Before Production** | Final review — must show APPROVE or APPROVE WITH CHANGES |

---

## 13. Severity Definitions and SLA

### 13.1 Severity Definitions

| Severity | Definition | Examples |
|---|---|---|
| **Critical** | Causes production failures, data loss, data quality issues, or security vulnerabilities. Must fix before merge. | Hardcoded secrets, plaintext passwords, SQL injection, missing error handling, wrong datetime function, DBFS usage, missing audit columns, upserts in Bronze, skipping Silver layer, watermark advancing past failures |
| **Major** | Breaks EDL standards and will be flagged in ATCO manual review. Should fix before merge. | Naming violations, missing retry config, wrong metadata column names, inconsistent parameters, missing version history, constants not uppercase, column_recast with source_name guards |
| **Medium** | Best practice improvements that reduce future review cycles. Recommended. | Missing comments, manual OPTIMIZE, per-stage emails, missing batchCount, performance tuning opportunities |
| **Minor** | Style, readability, and minor convention items. Suggestions only. | Documentation, minor formatting, activity naming inconsistencies |

### 13.2 Resolution SLA

| Severity | Resolution Target | Escalation |
|---|---|---|
| **Critical** | Within 2 business days | Escalate to Sr. Architect if not resolved in 3 days |
| **Major** | Within 5 business days | Escalate to Project Lead if not resolved in 7 days |
| **Medium** | Within current sprint | Track in sprint backlog |
| **Minor** | Best effort | No formal tracking required |

---

## 14. Troubleshooting

### 14.1 Common Issues

| Issue | Cause | Solution |
|---|---|---|
| "No files found" | Wrong directory or empty temp/ folder | Verify files are placed in `temp/` with correct structure |
| Copilot timeout | Very large file set (100+ files) | Split into smaller batches by domain — attach `review-adf.prompt.md` or `review-databricks.prompt.md` instead |
| Review misses a known issue | Check not in pattern file | Add the check following Section 10.2 |
| Report not saved | Missing `review/` directory | Utility creates it automatically; check write permissions |
| Follow-up not detected | File basenames changed between rounds | Use explicit comparison: `compare against review/adf/adf_20260305.md` |
| Wrong patterns used | Prompt file references wrong pattern file | Verify the `Before reviewing, read these files` section in the prompt file |
| Severity seems wrong | Pattern in wrong severity bucket | Check `code-reviewer.prompt.md` severity classification section; move the pattern |

### 14.2 Verifying a New Check Works

After adding a check to a pattern file:

1. Place a file in `temp/` that deliberately violates the new rule
2. Open Copilot Chat (Agent mode, Claude Opus), attach `code-reviewer.prompt.md`, run a review
3. Verify the violation appears in the report at the correct severity
4. If not caught: check the pattern file for formatting errors (missing ```code blocks```, wrong section placement)

### 14.3 Getting Help

- **Utility issues:** Check this SOP first, then raise with Utility Maintainer
- **Review disagreements:** Escalate to Sr. Data Architect
- **New domain requests:** Request via Utility Maintainer (Section 10.4)

---

## 15. File Map and Architecture Reference

```
ATCO_EDL_INGESTION_COPILOT/
├── .github/
│   ├── copilot-instructions.md                ← Auto-loaded by Copilot: cross-cutting standards
│   └── prompts/
│       ├── code-reviewer.prompt.md            ← Orchestrator: full review + auto-remediation
│       ├── review-adf.prompt.md               ← ADF pipelines specialist review
│       ├── review-databricks.prompt.md        ← Databricks notebooks specialist review
│       ├── review-sql.prompt.md               ← SQL scripts specialist review
│       ├── review-metadata.prompt.md          ← Metadata/config specialist review
│       ├── review-security.prompt.md          ← Security review across all types
│       ├── auto-remediate.prompt.md           ← Fix Critical/Major issues found in review
│       └── lint-reviewer.prompt.md            ← Python + SQL linting only (ruff + sqlfluff)
├── review-standards/
│   ├── references/
│   │   ├── adf-patterns.md                    ← ADF review rules (76 checks)
│   │   ├── databricks-patterns.md             ← Databricks review rules (57 checks)
│   │   ├── sql-patterns.md                    ← SQL review rules (33 checks)
│   │   ├── metadata-patterns.md               ← Metadata review rules (33 checks)
│   │   ├── security-patterns.md               ← Security review rules (30 checks)
│   │   └── generate_html_report.py            ← Converts .md reports to .html
│   └── lint-scripts/
│       ├── lint-ruff.py                       ← Ruff runner with ATCO convention mapping
│       └── lint-embedded-sql.py               ← Embedded SQL linter for spark.sql() calls
├── temp/                                      ← INPUT: Place code to review here
│   ├── adf/
│   ├── databricks/
│   ├── sql/
│   └── feedbacks/
│       ├── ATCO_EDL_Complete_Review_Checklist.xlsx  ← Full 229-check inventory
│       └── Gap_Analysis_Feedback_vs_Existing_Checks.xlsx  ← 30 feedback-derived gap analysis
├── review/                                    ← OUTPUT: Review reports saved here
│   ├── adf/
│   ├── databricks/
│   ├── sql/
│   ├── metadata/
│   ├── mixed/
│   └── lint/
├── pyproject.toml                             ← Ruff configuration
├── .sqlfluff                                  ← SQLFluff configuration (SparkSQL dialect)
├── README.md                                  ← Project overview and quick start
└── SOP_EDL_Code_Review_Utility.md             ← This document
```

### What Each File Controls

| File | What It Controls | Who Edits It |
|---|---|---|
| `code-reviewer.prompt.md` | Overall workflow, report format, severity definitions, domain dispatch | Utility Maintainer |
| `review-standards/references/*.md` | Domain-specific review rules and patterns | Utility Maintainer, Sr. Architect |
| `review-*.prompt.md` | How each specialist domain review runs (process, output format, notes) | Utility Maintainer |
| `copilot-instructions.md` | Cross-cutting standards auto-loaded into every Copilot session | Sr. Architect |

---

## Appendix A — Complete Check Count by Domain

| Domain | Section | Check Count |
|---|---|---|
| **ADF Pipeline** | 1. Naming Conventions | 9 |
| | 2. Parameterization | 12 |
| | 3. Retry & Timeout | 6 |
| | 4. Feedback-Derived Patterns | 18 |
| | 5. Error Handling | 6 |
| | 6. Additional Checks | 7 |
| | 7. Best Practices | 18 |
| | **ADF Subtotal** | **76** |
| **Databricks** | 1. Layer Architecture | 11 |
| | 2. Audit Columns | 7 |
| | 3. Feedback-Derived Patterns | 17 |
| | 4. Data Storage | 6 |
| | 5. Exception Handling | 3 |
| | 6. Workspace Boundaries | 2 |
| | 7. Additional Checks | 8 |
| | 8. Best Practices | 3 (representative) |
| | **Databricks Subtotal** | **57** |
| **SQL** | 1. Naming Conventions | 5 |
| | 2. Data Types | 5 |
| | 3. Constraints | 4 |
| | 4. Stored Procedures | 9 |
| | 5. SQL in Python | 1 |
| | 6. Best Practices | 9 |
| | **SQL Subtotal** | **33** |
| **Metadata** | 1. Control Table Columns | 6 |
| | 2. Column Name Checks | 1 (10 pairs) |
| | 3. Watermark Handling | 5 |
| | 4. Feedback-Derived Patterns | 15 |
| | 5. Audit Logging | 4 |
| | 6. Notifications | 2 |
| | **Metadata Subtotal** | **33** |
| **Security** | 1. Secrets & Key Vault | 5 |
| | 2. Authentication | 4 |
| | 3. Access Control | 3 |
| | 4. Data Protection | 4 |
| | 5. SQL Injection | 2 |
| | 6. Sensitive Data | 2 |
| | 7. Best Practices | 10 |
| | **Security Subtotal** | **30** |
| **GRAND TOTAL** | | **229** |

---

## Appendix B — Feedback Integration Log

The following 30 checks were added based on ATCO SIT/UAT feedback from 18 project review rounds covering LPSS, ADMS, AMR, ATS, CIS, CROW, ESRI-Electric, ESRI-Gas, GTech, IDM, Salesforce, and GitHub Analytics projects.

| ID | Check Name | Severity | Frequency | Target File |
|---|---|---|---|---|
| F1 | Cross-Stage Watermark Safety | Critical | 2 rounds | adf-patterns.md |
| F2 | BIGINT Watermark Type Support | Critical | 4+ sources | adf-patterns.md |
| F3 | source_query Null/Not-Null Handling | Major | 3+ sources | adf-patterns.md |
| F4 | adf_master_pipeline_name Parameter | Major | 1 round | adf-patterns.md |
| F5 | Retry Value Must Be Exactly 3 | Major | 1 round + guideline | adf-patterns.md |
| F8 | Pipeline Performance via Audit | Medium | Guideline + checklist | adf-patterns.md |
| F9 | ADLS Container = "landing" | Medium | Guideline | adf-patterns.md |
| F10 | Dataset Naming Inherits LS Type Prefix | Medium | Guideline | adf-patterns.md |
| F11 | Stored Procedure Source Type Handling | Critical | 1 source | adf-patterns.md |
| F12 | SP Parameters from Config Table | Critical | 1 source | adf-patterns.md |
| F13 | Scalable File Listing | Major | 1 round | adf-patterns.md |
| F15 | write_mode + is_initial_load_required | Major | 1 source | adf-patterns.md |
| F19 | column_recast No source_name Guards | Critical | 5+ sources | databricks-patterns.md |
| F20 | Decimal Scale=0 for NUMBER(N,0) | Critical | 6 sources | databricks-patterns.md |
| F22 | Unit Tests for Pipeline Classes | Critical | 2 rounds | databricks-patterns.md |
| F24 | Soft Delete (az_flag_is_delete) | Critical | 1 round | databricks-patterns.md |
| F25 | Hash Auto-Gen for Tables Without PK | Critical | 1 round | databricks-patterns.md |
| F27 | Partial Success Tracking | Critical | 1 round | databricks-patterns.md |
| F29 | az_create_datetime INSERT-Only | Critical | Guideline | databricks-patterns.md |
| F30 | Bronze Retention/Pruning + Archival | Major | Guideline | databricks-patterns.md |
| F32 | Gold Separate Storage Container | Medium | Guideline | databricks-patterns.md |
| F34 | Folder Path source_name Prefix | Medium | 3 sources | metadata-patterns.md |
| F35 | File Processing Tracker Table | Critical | 1 round | metadata-patterns.md |
| F36 | Dynamic Schema from Metadata | Major | 2 sources | databricks-patterns.md |
| F38 | Notification on Notebook FAILED Status | Major | 1 round | adf-patterns.md |
| F46 | watermark_type Column Required | Major | 3+ sources | metadata-patterns.md |
| F47 | execution_frequency Column | Medium | 2 sources | metadata-patterns.md |
| F50 | stored_procedure_config Table | Major | 1 source | metadata-patterns.md |
| F51 | column_config Completeness | Major | 3+ sources | metadata-patterns.md |
| F52 | Metadata Entry Count Validation | Medium | 3 sources | metadata-patterns.md |

---

*End of SOP*
