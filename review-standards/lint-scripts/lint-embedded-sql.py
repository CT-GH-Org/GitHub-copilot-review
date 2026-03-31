#!/usr/bin/env python3
"""Lint embedded SQL in Python files and log violations with convention mapping.

Extracts SQL from spark.sql() calls, lints with sqlfluff using custom .sqlfluff
config, maps each violation to the ATCO EDL convention section it violates,
and saves structured JSON logs to .sqlfluff_logs/.

Does NOT fix code — only logs linting errors and convention violations.

Exit code 0 = clean or no SQL found, 1 = violations found.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta

# Exclude rules that are too noisy or irrelevant for embedded SQL
EXCLUDE_RULES = "LT05,ST06,RF04,LT02,AL01,LT13"

# Project root for locating .sqlfluff config and log dirs
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
LOG_DIR = os.path.join(PROJECT_ROOT, ".sqlfluff_logs")

# ---------------------------------------------------------------------------
# SQLFluff rule code -> ATCO EDL convention mapping
# Derived from .sqlfluff config sections
# ---------------------------------------------------------------------------
CONVENTION_MAP = {
    # Section 8.1 - Keyword & identifier case
    "CP01": {"convention": "Section 8.1 — Keywords UPPERCASE", "rule": "SQL keywords must be UPPERCASE"},
    "CP02": {"convention": "Section 8.1 & 6.2 — Identifiers UPPERCASE", "rule": "Column and table names must be UPPERCASE"},
    "CP03": {"convention": "Section 8.1 — Functions UPPERCASE", "rule": "Function names must be UPPERCASE"},
    "CP04": {"convention": "Section 8.1 — Literals UPPERCASE", "rule": "NULL, TRUE, FALSE must be UPPERCASE"},
    "CP05": {"convention": "Section 8.1 — Types UPPERCASE", "rule": "Data type keywords must be UPPERCASE (BIGINT, STRING, etc.)"},
    # Section 8.1 - Formatting
    "LT01": {"convention": "Section 8.1 — Whitespace", "rule": "Proper whitespace around operators and keywords"},
    "LT02": {"convention": "Section 8.1 — Indentation", "rule": "4-space indentation required"},
    "LT03": {"convention": "Section 8.1 — Operators", "rule": "Operators on correct line"},
    "LT04": {"convention": "Section 8.1 — Comma placement", "rule": "Leading commas required"},
    "LT05": {"convention": "Section 8.1 — Line length", "rule": "Max 120 characters per line"},
    "LT09": {"convention": "Section 8.1 — SELECT columns", "rule": "SELECT targets on separate lines"},
    "LT10": {"convention": "Section 8.1 — SELECT modifiers", "rule": "SELECT modifiers on same line"},
    "LT12": {"convention": "Section 8.1 — End of file", "rule": "Files must end with single newline"},
    "LT13": {"convention": "Section 8.1 — Start of file", "rule": "No leading whitespace at start of file"},
    # Section 8.1 - Indentation detail
    "LT19": {"convention": "Section 8.1 — Blank lines", "rule": "Proper blank line usage"},
    # Section 8.2 - JOIN Standards
    "AM05": {"convention": "Section 8.2 — Explicit JOINs", "rule": "No implicit joins; use explicit JOIN syntax"},
    "JJ01": {"convention": "Section 8.2 — JOIN types", "rule": "Fully qualify JOIN types (INNER JOIN, LEFT OUTER JOIN)"},
    "AL01": {"convention": "Section 8.2 — Table aliases", "rule": "Table aliases must be meaningful (no a, b, t1)"},
    "AL02": {"convention": "Section 8.2 — Column aliases", "rule": "Explicit column aliasing required"},
    "AL03": {"convention": "Section 8.2 — Expression aliases", "rule": "Explicit expression aliasing required"},
    # Section 8.4 - CTE Standards
    "ST01": {"convention": "Section 8.4 — CTE over subquery", "rule": "Use CTEs instead of subqueries"},
    "ST06": {"convention": "Section 8.4 — SELECT order", "rule": "Wildcards before column expressions in SELECT"},
    # Section 8.5 - SELECT Best Practices
    "AM04": {"convention": "Section 8.5 — No SELECT *", "rule": "No SELECT * in production code"},
    "AM06": {"convention": "Section 8.5 — GROUP BY/ORDER BY", "rule": "Explicit column references in GROUP BY/ORDER BY"},
    # Section 8.2 - Trailing comma
    "CV10": {"convention": "Section 8.2 — Trailing comma", "rule": "No trailing comma in SELECT"},
    # Aliasing
    "RF02": {"convention": "Section 8.2 — Qualified references", "rule": "Use qualified column references with table aliases"},
}


def get_convention(rule_code: str) -> dict:
    """Map a sqlfluff rule code to its ATCO EDL convention section."""
    # Strip numeric suffix variants (e.g., CP01a -> CP01)
    base_code = re.sub(r"[a-z]$", "", rule_code)
    if base_code in CONVENTION_MAP:
        return CONVENTION_MAP[base_code]
    # Fallback: categorize by prefix
    prefix_map = {
        "CP": "Capitalisation convention",
        "LT": "Layout/formatting convention",
        "AL": "Aliasing convention",
        "AM": "Ambiguity convention",
        "ST": "Structure convention",
        "RF": "Reference convention",
        "JJ": "JOIN convention",
        "CV": "Convention rule",
    }
    prefix = re.match(r"^[A-Z]+", rule_code)
    category = prefix_map.get(prefix.group(), "SQL convention") if prefix else "SQL convention"
    return {"convention": category, "rule": f"Rule {rule_code}"}


def extract_sql_blocks(content: str) -> list[dict]:
    """Extract SQL strings from Python content with match positions."""
    sql_blocks = []

    pattern = re.compile(
        r'spark\.sql\(\s*f?"""(.*?)"""\s*\)'
        r"|"
        r"spark\.sql\(\s*f?'''(.*?)'''\s*\)"
        r"|"
        r'spark\.sql\(\s*f?"([^"]*?)"\s*\)',
        re.DOTALL,
    )

    for match in pattern.finditer(content):
        sql = match.group(1) or match.group(2) or match.group(3)
        if sql and sql.strip():
            for g in (1, 2, 3):
                if match.group(g):
                    sql_start = match.start(g)
                    sql_end = match.end(g)
                    break
            line_no = content[: match.start()].count("\n") + 1
            sql_blocks.append(
                {
                    "sql": sql,
                    "line": line_no,
                    "start": sql_start,
                    "end": sql_end,
                }
            )

    return sql_blocks


def replace_fstring_vars(sql: str) -> tuple[str, list[tuple[str, str]]]:
    """Replace {variable} expressions with reversible uppercase placeholders."""
    replacements = []
    counter = [0]

    def make_placeholder(match):
        original = match.group(0)
        counter[0] += 1
        placeholder = f"FSTRVAR{counter[0]:03d}"
        replacements.append((placeholder, original))
        return placeholder

    def replace_qualified(match):
        cat = match.group(1)
        sch = match.group(2)
        table = match.group(3)
        counter[0] += 1
        cat_ph = f"FSTRVAR{counter[0]:03d}"
        replacements.append((cat_ph, "{" + cat + "}"))
        counter[0] += 1
        sch_ph = f"FSTRVAR{counter[0]:03d}"
        replacements.append((sch_ph, "{" + sch + "}"))
        return f"{cat_ph}.{sch_ph}.{table}"

    sql = re.sub(
        r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}\.\{([a-zA-Z_][a-zA-Z0-9_.]*)\}\.(\w+)",
        replace_qualified,
        sql,
    )

    def replace_two_part(match):
        cat = match.group(1)
        sch = match.group(2)
        counter[0] += 1
        cat_ph = f"FSTRVAR{counter[0]:03d}"
        replacements.append((cat_ph, "{" + cat + "}"))
        counter[0] += 1
        sch_ph = f"FSTRVAR{counter[0]:03d}"
        replacements.append((sch_ph, "{" + sch + "}"))
        return f"{cat_ph}.{sch_ph}"

    sql = re.sub(
        r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}\.\{([a-zA-Z_][a-zA-Z0-9_.]*)\}",
        replace_two_part,
        sql,
    )

    sql = re.sub(
        r"\{[a-zA-Z_][a-zA-Z0-9_.!:]*\}",
        make_placeholder,
        sql,
    )

    return sql, replacements


def restore_fstring_vars(sql: str, replacements: list[tuple[str, str]]) -> str:
    """Restore f-string expressions from placeholders."""
    for placeholder, original in reversed(replacements):
        sql = sql.replace(placeholder, original)
    return sql


def lint_sql_block(sql: str) -> tuple[bool, list[dict], str]:
    """Lint a single SQL block with sqlfluff JSON output.

    Returns (passed, parsed_violations, raw_output).
    """
    config_path = os.path.join(PROJECT_ROOT, ".sqlfluff")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False) as tmp:
        tmp.write(sql + "\n")
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [
                "uv",
                "run",
                "sqlfluff",
                "lint",
                "--format",
                "json",
                "--config",
                config_path,
                "--exclude-rules",
                EXCLUDE_RULES,
                tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        raw_output = result.stdout
        parsed_violations = []

        try:
            lint_results = json.loads(raw_output)
            for file_result in lint_results:
                for v in file_result.get("violations", []):
                    code = v.get("code", "")
                    conv = get_convention(code)
                    parsed_violations.append(
                        {
                            "line": v.get("start_line_no", 0),
                            "end_line": v.get("end_line_no", 0),
                            "column": v.get("start_line_pos", 0),
                            "code": code,
                            "description": v.get("description", ""),
                            "name": v.get("name", ""),
                            "convention": conv["convention"],
                            "convention_rule": conv["rule"],
                        }
                    )
        except (json.JSONDecodeError, TypeError, KeyError):
            # Fallback: treat raw output as text
            if result.returncode != 0 and "PASS" not in (result.stdout + result.stderr):
                parsed_violations.append(
                    {
                        "line": 0,
                        "code": "PARSE_ERROR",
                        "description": (result.stdout + result.stderr).strip(),
                        "convention": "Unable to parse",
                        "convention_rule": "Raw output logged",
                    }
                )

        passed = len(parsed_violations) == 0
        return passed, parsed_violations, raw_output

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return True, [], f"Skipped: {e}"
    finally:
        os.unlink(tmp_path)


def save_log(file_path: str, report: dict) -> str:
    """Save structured JSON log to .sqlfluff_logs/ directory."""
    os.makedirs(LOG_DIR, exist_ok=True)
    basename = os.path.splitext(os.path.basename(file_path))[0]
    log_path = os.path.join(LOG_DIR, f"{basename}_embedded.json")

    with open(log_path, "w") as f:
        json.dump(report, f, indent=2)

    return log_path


def main():
    if len(sys.argv) < 2:
        print("Usage: lint-embedded-sql.py <file.py> [file2.py ...]", file=sys.stderr)
        sys.exit(1)

    ist = timezone(timedelta(hours=5, minutes=30))
    all_reports = []
    any_violations = False

    for file_path in sys.argv[1:]:
        if not os.path.isfile(file_path):
            continue

        with open(file_path) as f:
            content = f.read()

        sql_blocks = extract_sql_blocks(content)

        report = {
            "file": file_path,
            "timestamp": datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST"),
            "blocks": len(sql_blocks),
            "results": [],
            "violations": [],
            "convention_summary": {},
        }

        if not sql_blocks:
            log_path = save_log(file_path, report)
            report["log_path"] = log_path
            all_reports.append(report)
            continue

        convention_counts = {}

        for i, block in enumerate(sql_blocks, 1):
            raw_sql = block["sql"]
            cleaned_sql, replacements = replace_fstring_vars(raw_sql)
            passed, violations, raw_output = lint_sql_block(cleaned_sql)

            status = "PASS" if passed else "FAIL"
            if not passed:
                any_violations = True

            # Map violations back to original line numbers in the .py file
            for v in violations:
                v["py_line"] = block["line"] + v.get("line", 0) - 1
                conv_key = v["convention"]
                convention_counts[conv_key] = convention_counts.get(conv_key, 0) + 1

            block_result = {
                "block": i,
                "line": block["line"],
                "sql_preview": raw_sql[:100].strip() + ("..." if len(raw_sql) > 100 else ""),
                "status": status,
                "violation_count": len(violations),
                "violations": violations,
            }

            report["results"].append(block_result)
            if not passed:
                report["violations"].extend(violations)

        # Convention summary: which conventions are NOT followed
        report["convention_summary"] = {
            conv: {"count": count, "rule": get_convention(conv).get("rule", conv)}
            for conv, count in sorted(convention_counts.items(), key=lambda x: -x[1])
        }
        report["total_violations"] = len(report["violations"])
        report["blocks_passed"] = sum(1 for r in report["results"] if r["status"] == "PASS")
        report["blocks_failed"] = sum(1 for r in report["results"] if r["status"] == "FAIL")

        # Save log file
        log_path = save_log(file_path, report)
        report["log_path"] = log_path

        all_reports.append(report)

    # Print summary JSON to stdout for skill/orchestrator consumption
    print(json.dumps(all_reports if len(all_reports) > 1 else (all_reports[0] if all_reports else {}), indent=2))

    sys.exit(1 if any_violations else 0)


if __name__ == "__main__":
    main()
