#!/usr/bin/env python3
"""Lint Python files with ruff and log violations with convention mapping.

Runs ruff check with JSON output, maps each violation to the ATCO EDL
convention section it violates (from pyproject.toml), and saves structured
JSON logs to .ruff_logs/.

Does NOT fix code — only logs linting errors and convention violations.

Exit code 0 = clean, 1 = violations found.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

# Project root for locating pyproject.toml and log dirs
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
LOG_DIR = os.path.join(PROJECT_ROOT, ".ruff_logs")

# ---------------------------------------------------------------------------
# Ruff rule code prefix -> ATCO EDL convention mapping
# Derived from pyproject.toml [tool.ruff.lint] sections
# ---------------------------------------------------------------------------
CONVENTION_MAP = {
    # E — pycodestyle errors
    "E1": {"convention": "PEP 8 — Indentation", "rule": "4-space indentation, no tabs"},
    "E2": {"convention": "PEP 8 — Whitespace", "rule": "Proper whitespace around operators/keywords"},
    "E3": {"convention": "PEP 8 — Blank lines", "rule": "Correct blank line usage between functions/classes"},
    "E4": {"convention": "PEP 8 — Imports", "rule": "Import formatting and placement"},
    "E5": {"convention": "PEP 8 — Line length", "rule": "Max 120 characters per line"},
    "E7": {"convention": "PEP 8 — Statements", "rule": "One statement per line"},
    "E9": {"convention": "PEP 8 — Runtime errors", "rule": "Syntax errors in source"},
    # W — pycodestyle warnings
    "W1": {"convention": "PEP 8 — Indentation warnings", "rule": "Indentation consistency"},
    "W2": {"convention": "PEP 8 — Whitespace warnings", "rule": "Trailing whitespace"},
    "W3": {"convention": "PEP 8 — Blank line warnings", "rule": "Blank line at end of file"},
    "W6": {"convention": "PEP 8 — Deprecation warnings", "rule": "Deprecated features"},
    # F — Pyflakes
    "F4": {"convention": "Code Quality — Imports", "rule": "No wildcard imports, no duplicate imports"},
    "F5": {"convention": "Code Quality — Assertions", "rule": "No assert with tuple, valid format strings"},
    "F6": {"convention": "Code Quality — Annotations", "rule": "Valid annotations"},
    "F7": {"convention": "Code Quality — Syntax", "rule": "Valid syntax patterns"},
    "F8": {"convention": "Code Quality — Variables", "rule": "No unused imports/variables, no undefined names"},
    "F9": {"convention": "Code Quality — Encoding", "rule": "Valid file encoding"},
    # I — isort
    "I0": {"convention": "Import Organisation", "rule": "stdlib -> third-party -> local; sorted within sections"},
    # N — pep8-naming
    "N8": {"convention": "Naming Conventions", "rule": "Classes=PascalCase, functions/vars=snake_case, constants=UPPER_SNAKE_CASE"},
    # B — flake8-bugbear
    "B0": {"convention": "Bug Prevention", "rule": "Common bug patterns (mutable defaults, assert, except)"},
    # ANN — flake8-annotations
    "ANN0": {"convention": "Type Hints — Arguments", "rule": "Type annotations required for function arguments"},
    "ANN2": {"convention": "Type Hints — Return types", "rule": "Return type annotations required"},
    "ANN4": {"convention": "Type Hints — General", "rule": "Type annotation standards"},
    # D — flake8-docstrings (Google style)
    "D1": {"convention": "Documentation — Missing docstrings", "rule": "Public modules/classes/functions must have Google-style docstrings"},
    "D2": {"convention": "Documentation — Formatting", "rule": "Docstring formatting (summary, blank lines, quotes)"},
    "D3": {"convention": "Documentation — Whitespace", "rule": "Docstring indentation and line breaks"},
    "D4": {"convention": "Documentation — Content", "rule": "Docstring content (imperative mood, sections)"},
    # SIM — flake8-simplify
    "SIM1": {"convention": "Code Simplification", "rule": "Simplify boolean/conditional expressions"},
    "SIM2": {"convention": "Code Simplification", "rule": "Simplify control flow"},
    "SIM3": {"convention": "Code Simplification", "rule": "Simplify comparisons"},
    "SIM9": {"convention": "Code Simplification", "rule": "Simplify exception handling"},
    # G — flake8-logging-format
    "G0": {"convention": "Structured Logging", "rule": "Use structured logging (no f-strings/% in log calls)"},
    "G1": {"convention": "Structured Logging", "rule": "Logging format patterns"},
    "G2": {"convention": "Structured Logging", "rule": "Logging extra parameters"},
    # UP — pyupgrade
    "UP0": {"convention": "Python Modernisation", "rule": "Use modern Python patterns (3.11+ target)"},
    # RET — flake8-return
    "RET5": {"convention": "Return Statements", "rule": "Clean return patterns (no unnecessary else/assign before return)"},
    # S — flake8-bandit (security)
    "S1": {"convention": "Security — Hardcoded values", "rule": "No hardcoded passwords, temp files, or secrets"},
    "S3": {"convention": "Security — Calls", "rule": "No dangerous function calls (eval, exec, pickle)"},
    "S5": {"convention": "Security — Crypto", "rule": "Safe cryptographic patterns"},
    "S6": {"convention": "Security — Injection", "rule": "No SQL injection, shell injection, or XSS"},
    # RUF — Ruff-specific
    "RUF0": {"convention": "Ruff Rules", "rule": "Ruff-specific code quality checks"},
}


def get_convention(rule_code: str) -> dict:
    """Map a ruff rule code to its ATCO EDL convention section."""
    # Try exact prefix matches from longest to shortest
    for length in range(len(rule_code), 0, -1):
        prefix = rule_code[:length]
        if prefix in CONVENTION_MAP:
            return CONVENTION_MAP[prefix]

    # Fallback by first letter group
    letter_prefix = ""
    for ch in rule_code:
        if ch.isalpha():
            letter_prefix += ch
        else:
            break

    prefix_map = {
        "E": "PEP 8 — pycodestyle error",
        "W": "PEP 8 — pycodestyle warning",
        "F": "Code Quality — Pyflakes",
        "I": "Import Organisation",
        "N": "Naming Conventions",
        "B": "Bug Prevention",
        "ANN": "Type Hints",
        "D": "Documentation",
        "SIM": "Code Simplification",
        "G": "Structured Logging",
        "UP": "Python Modernisation",
        "RET": "Return Statements",
        "S": "Security",
        "RUF": "Ruff Rules",
    }
    category = prefix_map.get(letter_prefix, "Python convention")
    return {"convention": category, "rule": f"Rule {rule_code}"}


def run_ruff(target: str) -> tuple[list[dict], str]:
    """Run ruff check with JSON output. Returns (parsed_violations, raw_json)."""
    try:
        result = subprocess.run(
            [
                "uv",
                "run",
                "ruff",
                "check",
                "--output-format=json",
                target,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        raw_output = result.stdout
        violations = []

        try:
            ruff_results = json.loads(raw_output)
            for v in ruff_results:
                code = v.get("code", "")
                conv = get_convention(code)
                violations.append(
                    {
                        "file": v.get("filename", ""),
                        "line": v.get("location", {}).get("row", 0),
                        "column": v.get("location", {}).get("column", 0),
                        "end_line": v.get("end_location", {}).get("row", 0),
                        "end_column": v.get("end_location", {}).get("column", 0),
                        "code": code,
                        "message": v.get("message", ""),
                        "fixable": v.get("fix", {}).get("applicability", "") if v.get("fix") else None,
                        "convention": conv["convention"],
                        "convention_rule": conv["rule"],
                    }
                )
        except (json.JSONDecodeError, TypeError, KeyError):
            if result.returncode != 0:
                violations.append(
                    {
                        "file": target,
                        "line": 0,
                        "code": "PARSE_ERROR",
                        "message": (result.stdout + result.stderr).strip(),
                        "convention": "Unable to parse",
                        "convention_rule": "Raw output logged",
                    }
                )

        return violations, raw_output

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return [], f"Skipped: {e}"


def save_logs(target: str, report: dict, raw_json: str) -> tuple[str, str]:
    """Save structured report and raw JSON to .ruff_logs/."""
    os.makedirs(LOG_DIR, exist_ok=True)

    basename = os.path.basename(target.rstrip("/")) or "project"

    # Save structured report with convention mapping
    report_path = os.path.join(LOG_DIR, f"{basename}_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    # Save raw ruff JSON output
    raw_path = os.path.join(LOG_DIR, "ruff_results.json")
    with open(raw_path, "w") as f:
        f.write(raw_json)

    return report_path, raw_path


def main():
    if len(sys.argv) < 2:
        print("Usage: lint-ruff.py <file_or_dir> [file2 ...]", file=sys.stderr)
        sys.exit(1)

    ist = timezone(timedelta(hours=5, minutes=30))
    targets = sys.argv[1:]
    any_violations = False

    for target in targets:
        if not os.path.exists(target):
            print(f"Warning: {target} not found, skipping", file=sys.stderr)
            continue

        violations, raw_json = run_ruff(target)

        # Group violations by file
        files = {}
        for v in violations:
            fname = v["file"]
            if fname not in files:
                files[fname] = {"file": fname, "violations": [], "violation_count": 0}
            files[fname]["violations"].append(v)
            files[fname]["violation_count"] += 1

        # Convention summary: count violations per convention
        convention_counts = {}
        for v in violations:
            conv_key = v["convention"]
            if conv_key not in convention_counts:
                convention_counts[conv_key] = {"count": 0, "rule": v["convention_rule"], "codes": set()}
            convention_counts[conv_key]["count"] += 1
            convention_counts[conv_key]["codes"].add(v["code"])

        # Serialize sets to lists for JSON
        for conv in convention_counts.values():
            conv["codes"] = sorted(conv["codes"])

        report = {
            "target": target,
            "timestamp": datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST"),
            "total_violations": len(violations),
            "total_files": len(files),
            "files_with_violations": sum(1 for f in files.values() if f["violation_count"] > 0),
            "convention_summary": dict(
                sorted(convention_counts.items(), key=lambda x: -x[1]["count"])
            ),
            "per_file": list(files.values()),
        }

        if violations:
            any_violations = True

        # Save logs
        report_path, raw_path = save_logs(target, report, raw_json)
        report["log_paths"] = {"report": report_path, "raw": raw_path}

        # Also save per-file human-readable logs
        os.makedirs(LOG_DIR, exist_ok=True)
        for fname, file_data in files.items():
            file_basename = os.path.splitext(os.path.basename(fname))[0]
            per_file_path = os.path.join(LOG_DIR, f"{file_basename}.log")
            with open(per_file_path, "w") as f:
                f.write(f"# Ruff lint report: {fname}\n")
                f.write(f"# Generated: {report['timestamp']}\n")
                f.write(f"# Violations: {file_data['violation_count']}\n\n")
                for v in file_data["violations"]:
                    f.write(
                        f"Line {v['line']}, Col {v['column']} — {v['code']}: {v['message']}\n"
                        f"  Convention: {v['convention']} — {v['convention_rule']}\n"
                        f"  Fixable: {v.get('fixable', 'unknown')}\n\n"
                    )

        # Print summary JSON to stdout
        print(json.dumps(report, indent=2))

    sys.exit(1 if any_violations else 0)


if __name__ == "__main__":
    main()
