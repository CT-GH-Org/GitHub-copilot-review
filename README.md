# ATCO EDL Automated Code Review Utility

Automated code review and auto-remediation system for the Enterprise Data Lakehouse (EDL). Uses GitHub Copilot agents (Claude Opus) to review Databricks notebooks, ADF pipelines, SQL scripts, and metadata configurations against **229 checks** across 5 domains — then automatically fixes Critical and Major issues.

---

## Quick Start

### 1. Place code in `temp/`

```
temp/
├── adf/
│   └── pl_master_source/
│       ├── pipeline/*.json
│       ├── linkedService/*.json
│       ├── dataset/*.json
│       └── trigger/*.json
├── databricks/
│   └── project_name/
│       ├── config/constants.py
│       ├── utils/*.py
│       └── src/**/*.py
└── sql/
    ├── ddl/*.sql
    └── stored_procedures/*.sql
```

### 2. Run a review

Open **Copilot Chat** in VS Code, switch to **Agent mode**, select **Claude Opus** as the model, then use natural language:

```
Review all code in temp/adf/pl_master_source/
Review the Databricks notebooks in temp/databricks/project_name/
Review all SQL scripts in temp/sql/
Review everything in temp/
Review PR #42
```

Or attach the prompt file directly:
1. Click `+` (Add Context) in Copilot Chat
2. Select `.github/prompts/code-reviewer.prompt.md`
3. Type your review request

### 3. Get two HTML reports

The system produces **two deliverables**:

| Report | What It Shows |
|---|---|
| **Report 1: Initial Analysis** | All issues found in the original code |
| **Report 2: Post-Remediation** | Remaining issues after automatic fixes |

Both are saved as Markdown + interactive HTML dashboards in `review/{type}/`.

---

## What Gets Reviewed (229 Checks)

| Domain | Checks | Pattern File | What's Checked |
|---|---|---|---|
| **ADF Pipelines** | 76 | `adf-patterns.md` | Naming, parameterization, retry/timeout, error handling, ForEach, linked services, failure notifications |
| **Databricks Notebooks** | 57 | `databricks-patterns.md` | Layer architecture, audit columns, hardcoding, SCD2, workspace boundaries, column_recast, soft delete |
| **SQL Scripts** | 33 | `sql-patterns.md` | Data types, constraints, stored procedures, naming, GETUTCDATE, dynamic SQL |
| **Metadata/Config** | 33 | `metadata-patterns.md` | Column completeness, watermark handling, audit logging, notifications, control tables |
| **Security** | 30 | `security-patterns.md` | Hardcoded secrets, Key Vault, authentication, PII, SQL injection, Unity Catalog |

Includes **30 checks derived from ATCO SIT/UAT feedback** across 18 project review rounds.

---

## Complete Workflow (7 Steps)

```
User: "Review temp/adf/" (in Copilot Chat, Agent mode)
    │
    ▼
┌─ Step 1-2: Discover & Classify ────────────────────────┐
│  find_files/search_files → classify ADF / Databricks /  │
│  SQL / Metadata                                         │
└─────────────────────────┬──────────────────────────────┘
                          ▼
┌─ Step 2.5: Detect Previous Review ─────────────────────┐
│  Scan review/ folder → basename overlap ≥ 50%?          │
│  YES → Follow-Up mode (track resolved/still-open/new)   │
│  NO  → First Review mode                                │
└─────────────────────────┬──────────────────────────────┘
                          ▼
┌─ Step 2.8 + Step 3: Lint + Sequential Domain Reviews ──┐
│  Orchestrator runs ruff/sqlfluff                        │
│  + reviews ADF → Databricks → SQL → Metadata            │
│  + Security review ALWAYS runs across all artifact types│
└─────────────────────────┬──────────────────────────────┘
                          ▼
┌─ Step 4-4.5: Consolidate + Compare ────────────────────┐
│  De-duplicate across domains → classify findings         │
│  Follow-up: compute resolution rate + trend              │
└─────────────────────────┬──────────────────────────────┘
                          ▼
┌─ Step 5: Save Report 1 (Initial Analysis) ─────────────┐
│  ├── review/{type}/{type}_{timestamp}.md                 │
│  └── review/{type}/{type}_{timestamp}.html               │
└─────────────────────────┬──────────────────────────────┘
                          ▼
                   Critical > 0 OR Major > 0?
                   ┌──YES──┐        ┌──NO──┐
                   ▼       │        ▼      │
┌─ Step 6: Auto-Remediation Loop ─┐ │  Skip to │
│  (max 3 iterations)             │ │  Step 7  │
│                                 │ │          │
│  STEP A: Apply Fixes            │ │          │
│    • search_files ALL patterns  │ │          │
│    • Fix EVERY file             │ │          │
│    • Validate syntax            │ │          │
│                                 │ │          │
│  STEP B: Full Review Pipeline   │ │          │
│    • Re-run Steps 1-5           │ │          │
│    • All 5 domains + linters    │ │          │
│                                 │ │          │
│  STEP C: Evaluate               │ │          │
│    • CLEAN → exit loop          │ │          │
│    • Still issues → next iter   │ │          │
└─────────────────┬───────────────┘ │          │
                  ▼                 │          │
┌─ Step 7: Final Post-Remediation Report ─────┤
│  Fresh review on fixed code                  │
│  ├── review/{type}/{type}_post_remediation.md│
│  └── review/{type}/{type}_post_remediation.html
│  + Remediation Summary                       │
│  + Before vs After comparison table          │
└──────────────────────────────────────────────┘
```

### Step-by-Step Detail

| Step | What Happens | Duration |
|---|---|---|
| **1. Identify Target** | Determine files/directories from user request | Instant |
| **2. Discover & Classify** | find_files/search_files scan, classify by artifact type | ~5s |
| **2.5. Previous Review Detection** | Check `review/` for prior reports, compare basenames (≥50% overlap = match) | ~5s |
| **2.8. Run Linters** | Orchestrator runs ruff + sqlfluff + embedded SQL lint | ~30s |
| **3. Domain Reviews** | Each domain reviewed sequentially — reads pattern file, reviews all files of that type | 2-4 min per domain |
| **4. Consolidate** | De-duplicate findings across domain + security reviews | ~15s |
| **4.5. Compare** | (Follow-up only) Classify: RESOLVED / STILL OPEN / NEW, compute metrics | ~15s |
| **5. Save Report 1** | Markdown + HTML dashboard (Initial Analysis) | ~10s |
| **6. Auto-Remediation Loop** | Fix → Re-review → Evaluate (max 3 iterations) | 2-5 min per iteration |
| **7. Post-Remediation Report** | Fresh review on fixed code → Report 2 (MD + HTML) + Remediation Summary | 2-3 min |

**Typical total time:** 8-15 minutes depending on file count and number of issues.

---

## Auto-Remediation (Step 6)

When the initial review finds Critical or Major issues, the system **automatically** fixes them:

### How It Works

1. **Remediation** reads all 5 pattern files (following `auto-remediate.prompt.md`), then:
   - Uses `search_files` to find ALL occurrences of each violation pattern across ALL files (not just reported lines)
   - Applies fixes using `replace_in_file`
   - Validates: JSON parse, Python compile, SQL syntax
   - Cross-file consistency check (linked service names, parameter refs, dataset refs)
   - Classifies each fix: `SAFE` / `REQUIRES_VALIDATION` / `MANUAL_ONLY`

2. **Full Review Pipeline** re-runs (all 5 domain reviews + linters) to validate fixes

3. **Evaluate**: if Critical = 0 and Major = 0 → CLEAN; otherwise → next iteration

4. **Max 3 iterations** — if not clean after 3, status = REQUIRES MANUAL INTERVENTION

### What Gets Fixed

| Domain | Example Auto-Fixes |
|---|---|
| **ADF JSON** | Parameterize hardcoded values, add retry:3/retryInterval:30, PascalCase→snake_case params, add MSI auth, add failure notifications |
| **Databricks** | `datetime.now()`→UTC, remove DBFS paths, add audit columns, fix merge to preserve `az_create_datetime`, remove commented code |
| **SQL** | `GETDATE()`→`GETUTCDATE()`, `VARCHAR`→`NVARCHAR`, add `SET NOCOUNT ON`, parameterize dynamic SQL |
| **Security** | Secrets→Key Vault, `http`→`https`, remove hardcoded emails, add `.gitignore` entries |

### Scope

| Severity | Auto-Fixed? |
|---|---|
| Critical | Always |
| Major | Always |
| Medium | Only if user requests "fix all" |
| Minor | Never (style preferences for developer) |

---

## Prompt Files (Specialist Reviewers)

| Prompt File | Location | Role |
|---|---|---|
| **code-reviewer.prompt.md** | `.github/prompts/` | Main orchestrator: 7-step workflow, report format, severity |
| **review-adf.prompt.md** | `.github/prompts/` | Reviews ADF pipeline JSON — naming, parameterization, retry, timeout, error handling |
| **review-databricks.prompt.md** | `.github/prompts/` | Reviews Python notebooks — layer architecture, audit columns, SCD2, workspace boundaries |
| **review-sql.prompt.md** | `.github/prompts/` | Reviews SQL DDL/SPs — naming, data types, constraints, GETUTCDATE, dynamic SQL |
| **review-metadata.prompt.md** | `.github/prompts/` | Reviews control tables — column completeness, watermark handling, audit logging (#1 feedback area) |
| **review-security.prompt.md** | `.github/prompts/` | Reviews ALL file types — secrets, Key Vault, auth, PII, SQL injection (always runs) |
| **auto-remediate.prompt.md** | `.github/prompts/` | Fixes code based on review findings — single pass, orchestrator validates |
| **lint-reviewer.prompt.md** | `.github/prompts/` | On-demand linting only (ruff + sqlfluff) |

All prompt files:
- Read their pattern file from `review-standards/references/` before reviewing
- Use `mode: 'agent'` with full tool access (`read_file`, `search_files`, `run_terminal_command`, etc.)
- Domain reviewers can be used standalone for targeted reviews

---

## Lint Integration

Linting is **orchestrator-owned** — runs alongside domain reviews.

| Linter | Target | Script | Config |
|---|---|---|---|
| **Ruff** | Python `.py` files | `review-standards/lint-scripts/lint-ruff.py` | `pyproject.toml` |
| **SQLFluff** | Standalone `.sql` files | Direct `sqlfluff lint` | `.sqlfluff` |
| **Embedded SQL** | `spark.sql()` blocks in `.py` | `review-standards/lint-scripts/lint-embedded-sql.py` | `.sqlfluff` |

Logs saved to `.ruff_logs/` and `.sqlfluff_logs/` with:
- Raw JSON output
- Structured reports with ATCO EDL convention mapping
- Per-file human-readable logs

**Standalone linting** is also available by attaching `lint-reviewer.prompt.md` in Copilot Chat.

---

## Report Output

### File Structure

```
review/
├── adf/
│   ├── adf_20260324_193532.md                    ← Report 1: Initial Analysis
│   ├── adf_20260324_193532.html                  ← HTML dashboard
│   ├── adf_20260324_193532_remediation_iter1.md   ← Iteration 1 fixes
│   ├── adf_20260324_201242.md                    ← Follow-up after iteration 1
│   ├── adf_20260324_201242.html                  ← HTML dashboard
│   ├── adf_20260324_210000_post_remediation.md   ← Report 2: Post-Remediation
│   ├── adf_20260324_210000_post_remediation.html ← HTML dashboard
│   └── adf_20260324_193532_remediation_summary.md ← Consolidated summary
├── databricks/
├── sql/
├── metadata/
└── mixed/
```

- **Path convention:** `review/{type}/{type}_{timestamp_ist}.md`
- **Timestamp:** IST (UTC+5:30), formatted as `YYYYMMDD_HHmmss`
- **Types:** `adf`, `databricks`, `sql`, `metadata`, `mixed`

### HTML Dashboard Features

The HTML report is a self-contained, single-file interactive dashboard with:
- KPI cards with animated severity counters
- Tabbed issue viewer (Critical/Major/Medium/Minor) with expandable cards
- Syntax-highlighted code blocks with copy buttons
- Sortable per-file breakdown table
- Severity filter buttons and text search
- Sticky sidebar navigation with scroll-spy
- PASS/FAIL checklist badges
- Priority remediation cards
- Print-friendly CSS

### First Review Report Sections

| Section | Contents |
|---|---|
| **Header** | Files reviewed, date, review domains used, review type |
| **Executive Summary** | Total issues by severity, recommendation (APPROVE / APPROVE WITH CHANGES / REQUIRES REWORK) |
| **Critical Issues** | Category tag, file:line, Current/Required/Reference, Code Snippet, Suggested Fix |
| **Major Issues** | Same format as Critical |
| **Medium Issues** | Same format as Critical |
| **Minor Issues** | Same format; Code Snippet optional |
| **Lint Results** | Ruff + SQLFluff + Embedded SQL per-file tables |
| **Per-File Breakdown** | Every file listed individually with issue counts |
| **What Passed** | At least 5 specific positive findings with evidence |
| **Review Checklist** | 14-category PASS/FAIL table with detailed notes |
| **Summary** | Total counts, recommendation, numbered priority remediation order |

### Follow-Up Review Additions

| Section | Contents |
|---|---|
| **Executive Summary** | Previous Total → Resolved → Still Open → New → Resolution Rate → Trend |
| **Resolved Issues** | Table of fixed issues with how each was resolved |
| **Still Open Issues** | Tagged `[STILL OPEN]` with First Reported date, Days Open count |
| **New Issues** | Tagged `[NEW]` with full detail |
| **Checklist Trend** | Previous vs Current with FIXED/REGRESSED indicators |
| **Trend Analysis** | Per-severity direction arrows (IMPROVING/STABLE/DEGRADING) |

---

## Follow-Up Reviews

When you re-review the same files, the system automatically detects prior reviews and tracks progress.

**Detection logic:**
- Scans `review/{type}/*.md` for candidate reports
- Compares **basenames** (filename only, ignoring directory paths)
- `overlap_ratio ≥ 50%` → follow-up mode with the most recent matching review

**Trend definitions:**

| Trend | Condition |
|---|---|
| **IMPROVING** | Resolution rate ≥ 30% AND new issues ≤ still-open |
| **STABLE** | Resolution rate < 30% AND new issues ≤ resolved |
| **DEGRADING** | New issues > previous total OR (resolution rate < 10% AND new > still-open) |

**Force comparison against a specific review:**
```
Review temp/adf/pl_master_gold/ and compare against review/adf/adf_20260305_125136.md
```

---

## Severity Levels and SLA

| Level | Definition | Auto-Fixed? | Acceptance Criteria | Resolution Target |
|---|---|---|---|---|
| **Critical** | Production failures, data loss, security vulnerabilities | Yes | ALL must be resolved — zero tolerance | 2 business days |
| **Major** | Breaks EDL standards, flagged in manual review | Yes | ALL should be resolved — exceptions need Sr. Architect approval | 5 business days |
| **Medium** | Best practice improvements | On request | May defer to next sprint with ticket | Current sprint |
| **Minor** | Style and readability | Never | Optional — acknowledged in comments | Best effort |

---

## Top Issues Caught

These are the most frequently flagged patterns:

1. **Hardcoding** — Storage paths, database names, API URLs, notebook paths, watermark values, environment strings
2. **Metadata compliance** — Wrong column names (`mode` instead of `load_type`), missing required columns, wrong control table
3. **Where clause validation** — Not checking both NULL and empty string
4. **UTC datetime** — `GETDATE()` instead of `GETUTCDATE()`, `datetime.now()` instead of `current_timestamp()`
5. **Environment config** — Using `environment` parameter instead of `source_name`, hardcoded CASE statements

---

## Architecture

### File Map

```
ATCO_EDL_INGESTION_COPILOT/
├── .github/
│   ├── copilot-instructions.md              ← Auto-loaded context for all Copilot sessions
│   └── prompts/
│       ├── code-reviewer.prompt.md          ← Main orchestrator: 7-step workflow
│       ├── review-adf.prompt.md             ← ADF specialist reviewer
│       ├── review-databricks.prompt.md      ← Databricks specialist reviewer
│       ├── review-sql.prompt.md             ← SQL specialist reviewer
│       ├── review-metadata.prompt.md        ← Metadata specialist reviewer
│       ├── review-security.prompt.md        ← Security reviewer (always runs)
│       ├── auto-remediate.prompt.md         ← Auto-fixer
│       └── lint-reviewer.prompt.md          ← On-demand lint skill
├── review-standards/
│   ├── references/
│   │   ├── adf-patterns.md                 ← ADF review rules (76 checks)
│   │   ├── databricks-patterns.md          ← Databricks review rules (57 checks)
│   │   ├── sql-patterns.md                 ← SQL review rules (33 checks)
│   │   ├── metadata-patterns.md            ← Metadata review rules (33 checks)
│   │   ├── security-patterns.md            ← Security review rules (30 checks)
│   │   └── generate_html_report.py         ← HTML dashboard generator
│   └── lint-scripts/
│       ├── lint-ruff.py                    ← Ruff runner with convention mapping
│       └── lint-embedded-sql.py            ← Extracts spark.sql() blocks + lints
├── temp/                                   ← INPUT: Place code to review here
├── review/                                 ← OUTPUT: Review reports saved here
├── SOP_EDL_Code_Review_Utility.md          ← Standard Operating Procedure
├── pyproject.toml                          ← Ruff + project config
├── .sqlfluff                               ← SQLFluff config
└── README.md                              ← This file
```

### Knowledge Sources (Single Source of Truth)

| What | Where | Who Reads It |
|---|---|---|
| Auto-loaded context for all sessions | `.github/copilot-instructions.md` | GitHub Copilot (auto) |
| Orchestration, report format, severity, 7-step workflow | `.github/prompts/code-reviewer.prompt.md` | Main review sessions |
| Domain-specific review rules | `review-standards/references/*.md` | Corresponding prompt file |
| Prompt file behavior and process | `.github/prompts/review-*.prompt.md` | Each domain review |
| Lint configuration (Python) | `pyproject.toml` | Ruff via orchestrator |
| Lint configuration (SQL) | `.sqlfluff` | SQLFluff via orchestrator |

---

## Adding or Modifying Checks

| Goal | Method | Time |
|---|---|---|
| Add one review rule | Edit the relevant `review-standards/references/*.md` pattern file | 2 min |
| Add a rule via natural language | Tell GitHub Copilot: "Add a check to ADF patterns: ..." | 1 min |
| Change severity classification | Edit severity section in `code-reviewer.prompt.md` | 3 min |
| Add a universal standard | Edit `.github/copilot-instructions.md` | 5 min |
| Review a new artifact type | Create new `.github/prompts/review-{type}.prompt.md` + pattern file + register in `code-reviewer.prompt.md` | 15 min |

Every check must have: a GOOD example, a BAD example, and a severity classification.

See **Section 10** of `SOP_EDL_Code_Review_Utility.md` for detailed instructions.

---

## Standard Review Workflow (Roles)

```
Developer                    Utility                      Reviewer
    │                           │                            │
    │  1. Place code in temp/   │                            │
    │─────────────────────────► │                            │
    │  2. Open Copilot Chat     │                            │
    │     (Agent mode,          │                            │
    │      Claude Opus)         │                            │
    │─────────────────────────► │                            │
    │                           │  3-5. Review + Report 1    │
    │                           │  6. Auto-fix loop          │
    │                           │  7. Report 2               │
    │  8. Read reports          │                            │
    │◄───────────────────────── │                            │
    │  9. Fix remaining issues  │                            │
    │  10. Submit PR            │                            │
    │────────────────────────────────────────────────────────►│
    │                           │  11. Reviewer validates    │
    │  12. Final approval       │      reports + code        │
    │◄────────────────────────────────────────────────────────│
```

---

## Prerequisites

| Requirement | Details |
|---|---|
| **GitHub Copilot for VS Code** | Installed with Claude Opus model access |
| **Git** | Repository cloned locally |
| **Python (uv)** | For ruff + sqlfluff linting (auto-installed via `uv sync`) |
| **GitHub CLI (gh)** | Required only for PR-based reviews |
