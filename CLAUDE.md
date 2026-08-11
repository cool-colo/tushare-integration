# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Syncs [Tushare Pro](https://tushare.pro/) financial data (A-share stocks, indexes, futures) into a local analytical database (ClickHouse primarily; MySQL/Doris/StarRocks via templates). Built on Scrapy for concurrent, rate-limited collection. Beyond raw ingestion (ODS), it builds a layered warehouse (ODS → DWD → DWS) with point-in-time correctness and a data-quality validation framework.

All commands run from the repo root — `config.yaml`, `jobs.yaml`, and `tushare_integration/schema/` are opened by relative path at runtime.

## Commands

```bash
# Run the CLI (Typer). Sub-apps: run, query, dwd, dws, quality
python main.py --help

# Collection (ODS layer) — spider names are directory-path style
python main.py run spider "stock/quotes/daily"     # single spider (regex/wildcard match)
python main.py run job stock/quotes                 # run a named job from jobs.yaml
python main.py run job stock/quotes -u full         # override update dimension (incremental|daily / full|fully)
python main.py query list                           # list all spider names

# DWD / DWS layers (SQL-transform managers, not spiders)
python main.py dwd list
python main.py dwd sync dwd_stock_eod_price          # sync one; use `all` for every table
python main.py dwd sql  dwd_stock_eod_price          # render the sync SQL without executing
python main.py dws sync dws_stock_factor_wide

# Data quality
python main.py quality run <table> --layer ods       # validate one table (layer: ods|dwd|dws)
python main.py quality run all                        # validate everything, all layers
python main.py quality dqc --layer dws --all          # systematic DQC (drift/spot-check/factor cross-check)

# Tests (unittest-style, discovered by pytest). No live DB needed — DB is mocked (see tests/*.py DummyDB).
pytest                                    # all
pytest tests/test_quality_validation.py   # one file
pytest tests/test_quality_validation.py::ClassName::test_method   # one test

# Format (config in pyproject.toml: black line-length 120, isort black profile)
black . && isort .
```

## Configuration

`config.yaml` (repo root) is parsed into `TushareIntegrationSettings` (Pydantic, `settings.py`). **Any field can be overridden by an environment variable** (e.g. `TUSHARE_TOKEN`, `DB_HOST`, `DB_TYPE`, `CONCURRENT_REQUESTS`) — env wins over the file. Request rate is auto-derived from `tushare_point` (積分) via `point_frequency` unless `tushare_max_concurrent_requests` is set; `download_delay` is computed from it.

`config.yaml` currently contains a live `tushare_token` and a DingTalk webhook — treat as secrets; do not commit new ones or echo them.

## Architecture

### Collection flow (ODS)
`CrawlManager` (`manager.py`) drives Scrapy. A **spider = one Tushare API endpoint**. Spider `name` is a slash path (`stock/quotes/daily`) that also locates its YAML schema at `tushare_integration/schema/<name>.yaml`.

Spiders subclass one of four bases in `spiders/tushare.py` (see `docs/develop.md`):
- `TushareSpider` — base; auto-creates the latest + `_raw` tables on start, builds HTTP requests.
- `DailySpider` — iterates missing trading days from the `trade_cal` table; incremental by default, `MIN_CAL_DATE`/`BACKFILL_DAYS` via `custom_settings`.
- `TSCodeSpider` — iterates `ts_code`s from a basic table (default `stock_basic`).
- `FinancialReportSpider` — uses VIP bulk endpoints when `tushare_point >= 5000`, else per-`ts_code`.

**Dependency resolution:** each schema's `dependencies:` list (e.g. `daily` depends on `stock_basic`, `trade_cal`) is walked by `CrawlManager.get_all_spiders`, and prerequisites run first. Disabled when `parallel_mode: true` (collection is **not** concurrency-safe with auto-deps). `closespider_errorcount: 1` means a single error aborts the run; `run_job` reports via configured reporters and re-raises non-rate-limit signals.

**Pipeline chain** (`pipelines.py`, ordered in config): FillNA → TransformDType → **Data** (writes both a `<table>_raw` audit table with nullable columns + `_raw_json`, and the deduped latest `<table>`; upserts on `primary_key`, else appends) → RecordLog (writes `tushare_integration_log` per batch).

### Layered warehouse (ODS → DWD → DWS)
- **ODS** = raw Tushare tables produced by spiders (schema in `schema/<domain>/...`).
- **DWD** (`dwd.py`, `DWDManager`) = cleaned/conformed, point-in-time tables (`dwd_*`). Schemas in `schema/dwd/`. Adds SCD-style columns (`sys_from`/`sys_to`, `event_date`, `available_trade_date`, `instrument_id`) via `COMMON_DWD_COLUMNS`. Sync = render Jinja/SQL and execute against the DB.
- **DWS** (`dws.py`, `DWSManager`, the largest module) = wide analytical/factor tables (`dws_*`, e.g. `dws_stock_factor_wide` and its matrix form). Depends on multiple DWD tables (see `STOCK_FACTOR_WIDE_SOURCES`); has build-priority ordering and uses ClickHouse UDFs (`factors/`, `deploy/clickhouse/user_defined_functions/`). `factor_mapping.py` + a CSV map factor names to source columns.

Both DWD and DWS managers follow the same shape: `list_tables()`, `create_table()`, `sync_table()`/`sync_all()`, `render_sync_sql()`, and call into `QualityManager` before publishing.

### Schema system
YAML schemas (`schema/**/*.yaml`) are the single source of truth: `name`, `primary_key`, `dependencies`, and `columns` (`data_type` ∈ str/int/float/number/date/datetime/json). `storage.py` derives the `_raw` schema (nullable + metadata cols `_source`/`_api_name`/`_batch_id`/`_ingest_time`/`_record_hash`) and the latest schema (adds metadata cols) from the base. DDL/DML is rendered from Jinja templates under `schema/template/<db_type>/` (`table.jinja2`, `insert.jinja2`, `upsert.jinja2`) — **adding a new database backend = adding those three templates** plus a `DBEngine` subclass.

### Database abstraction (`db_engine.py`)
`DatabaseEngineFactory.create(settings)` returns a `DBEngine`. ClickHouse uses the native `clickhouse-connect` client (and auto-`ALTER TABLE ADD COLUMN` for schema drift via `sync_missing_columns`); MySQL/Doris go through SQLAlchemy. Type mapping (str→String, date→Date32, etc.) lives in `ClickhouseEngine.column_type_sql`.

### Data quality (`quality.py`, ~145k lines — the validation core)
`QualityManager` runs declarative rules per (layer, table) and blocks or warns on publish based on `ValidationMode` (`strict`/`warn_only`/`skip`), configurable globally, per-layer, or per-table in `config.yaml`'s `quality:` block. `DqcManager` runs systematic checks (rolling-baseline drift, deterministic spot-checks, factor business cross-checks). Results are recorded to result tables. `dwd`/`dws` sync commands accept `--skip-validation` and `--validation-mode`.

## Jobs & deployment
`jobs.yaml` groups spiders into named jobs (e.g. `stock/quotes`, `stock/financial`); each spider entry may set `update_type` (`full`/`incremental`), `enabled: false` (with `disabled_reason`), etc. `pre_job.yaml` defines prerequisite bootstrap jobs. `scripts/run_daily_market_jobs.sh` / `run_pre_market_jobs.sh` (+ `scripts/lib/market_job_runner.sh`) orchestrate collection + DWD/DWS sync as Kubernetes Jobs; `deploy/` holds the Helm chart and ClickHouse config/UDFs. `scripts/generate_jobs.py` regenerates `jobs.yaml`. Container entrypoint is `python main.py` (Dockerfile).

## Conventions
- Comments, table `comment:` fields, and reporter messages are in Chinese — match that when editing.
- Extensive design/analysis docs live in `docs/` (e.g. `daily_quant_data_layer_design.md`, `dqc_design.md`, `develop.md`, `current_pit_support_matrix.md`) — consult before changing warehouse layering, PIT semantics, or factor logic.
