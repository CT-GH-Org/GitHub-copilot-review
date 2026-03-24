# Copilot Instructions

## Repository Summary

This repository is a proof-of-concept (POC) for using GitHub Copilot as an automated PR reviewer. It contains a Databricks Asset Bundle project generated from the `default_python` template (`databricks/bundle-examples`), which provisions an ETL pipeline and a scheduled job on a Databricks workspace.

## Languages, Frameworks & Runtimes

| Technology | Role |
|---|---|
| **Python 3.10–3.12** | Source code, notebooks, unit tests |
| **Databricks Asset Bundles (DAB)** | Infrastructure-as-code for Databricks resources |
| **YAML** | Bundle configuration (`databricks.yml`, resource definitions) |
| **uv** | Python package and virtual environment management |
| **pytest** | Unit testing framework |
| **Databricks CLI** | Deploy, run, and manage bundles |

## Project Layout

```
default_python/
├── databricks.yml          # Root bundle config: targets (dev/prod), variables, artifact build
├── pyproject.toml          # Python project metadata, dependencies, build system (hatchling)
├── resources/              # YAML definitions for Databricks resources
│   ├── *.pipeline.yml      # DLT pipeline definitions
│   └── *.job.yml           # Workflow job definitions (schedule, tasks)
├── src/
│   └── default_python/     # Installable Python package (shared ETL logic)
│       └── main.py         # Entry point exposed via pyproject.toml [project.scripts]
├── tests/                  # pytest unit tests for the Python package
└── fixtures/               # Sample datasets used by tests and pipelines
```

Key configuration files:
- **`databricks.yml`** – defines the bundle name, included resource YAMLs, the `python_artifact` wheel build, and `dev`/`prod` target workspaces with variable overrides.
- **`pyproject.toml`** – pins the Python version, declares runtime and dev dependencies, and configures the `hatchling` build backend.

## Build & Validation

### Prerequisites
- Databricks CLI installed and authenticated (`databricks configure`)
- `uv` installed ([https://docs.astral.sh/uv/](https://docs.astral.sh/uv/))

### Common commands

```bash
# Install dependencies locally
uv sync --dev

# Run unit tests
uv run pytest

# Validate bundle configuration without deploying
databricks bundle validate

# Deploy to the development target (default)
databricks bundle deploy --target dev

# Deploy to production
databricks bundle deploy --target prod

# Trigger a job or pipeline run
databricks bundle run <resource-name>

# Destroy all deployed resources for a target
databricks bundle destroy --target dev
```

The `dev` target uses `mode: development`, which prefixes all resource names with `[dev <username>]` and pauses all schedules automatically.

## Coding Standards & Best Practices

- **One resource per file** – keep each job and pipeline in its own YAML file under `resources/` for clarity and diff readability.
- **Use bundle variables** – parameterise environment-specific values (catalog, schema, workspace host) via `variables` in `databricks.yml` rather than hardcoding them in resource files.
- **Target-based configuration** – use `dev` / `prod` targets to separate deployment contexts; never share a `root_path` between targets.
- **Wheel artifacts** – package shared Python logic as a wheel (`uv build --wheel`) so jobs and pipelines pin an explicit version.
- **Test locally first** – run `uv run pytest` before deploying; use `databricks bundle validate` to catch YAML schema errors early.
- **Keep secrets out of YAML** – reference Databricks secrets via `{{secrets/scope/key}}` syntax; never commit credentials.
- **Pin dependency versions** – specify version ranges in `pyproject.toml` and commit the lock file to ensure reproducible builds.
