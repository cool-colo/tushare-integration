# Generic DQC Design

This project separates two data quality concerns:

- Publish validation keeps DWD/DWS table replacement safe with lightweight blocker rules.
- Systematic DQC records daily observability metrics, semantic failures, consistency failures, drift signals, and samples for monitoring and alerting.

The DQC framework is generic. DWS stock factor checks are the first suite, but the result tables and manager are designed for future ADS suites such as portfolio, risk, signal, and backtest DQC.

## Architecture

`DqcManager` owns generic DQC orchestration:

- resolves `layer`, `suite_name`, `table_name`, `as_of_date`, and mode
- dispatches to a registered suite
- persists run, result, metric, consistency, and sample records
- computes drift from historical `dq_dqc_metric` rows
- raises in `strict` mode only when `BLOCKER` checks fail

The first suite is:

```text
layer: dws
domain: factor
suite_name: stock_factor_panel
tables:
  - dws_stock_factor_wide
  - dws_stock_factor_wide_matrix
```

Future ADS DQC should add new suites behind the same manager instead of creating ADS-specific result tables.

## Result Tables

DQC uses generic tables:

- `dq_dqc_run`: one row per DQC run.
- `dq_dqc_result`: one row per rule outcome.
- `dq_dqc_metric`: daily numeric metrics for monitoring and drift.
- `dq_dqc_consistency`: table-pair consistency checks.
- `dq_dqc_sample`: failed-key and deterministic spot-check samples.

Each table carries generic dimensions such as `layer`, `domain`, `suite_name`, and `table_name`, so the same tables can store DWS and ADS results.

## DWS Stock Factor Suite

Completeness checks:

- target trade-date row count is nonzero
- required key and lineage fields are populated
- numeric null and zero ratios are profiled
- matrix `factor_count` matches the configured factor mapping count

Freshness checks:

- latest DWS `trade_date` reaches the latest open trading day from `dwd_trade_calendar`
- `available_trade_date` and `build_time` are recorded as metrics

Statistical profiling:

- per numeric column and factor: row count, non-null count, null ratio, zero ratio, mean, stddev, min, max, q01, q05, q50, q95, q99
- drift checks compare current metrics with prior `dq_dqc_metric` baselines
- before `quality.dqc_min_baseline_days` exists, drift emits `MONITOR` warm-up results

Semantic checks:

- OHLC consistency for `dws_stock_factor_wide`
- nonnegative volume, amount, shares, market value, margin, and holding fields
- finite numeric values only, no NaN or Inf
- PIT safety: `available_trade_date >= trade_date`
- bounded fields: `0 <= winner_rate <= 100`, `0 <= qb_rsi_14 <= 100`
- matrix lineage points to `dws_stock_factor_wide`
- matrix factor error payload is empty
- matrix factor values match their business definitions in `docs/prd/factor_mapping_readable.csv`

Consistency checks:

- key-set equality on `(instrument_id, trade_date)`
- row-count ratio and instrument-count ratio between wide and matrix
- deterministic missing-key samples
- deterministic spot-check samples by stock/date/entity for audit navigation

Business factor cross-validation:

- `dqc_factor_business_cross_validation` samples matrix `(instrument_id, trade_date, factor_id)` pairs deterministically.
- For each sampled factor, DQC reads `factor_mapping_readable.csv` and uses the factor expression as the business definition.
- DQC fetches the required historical source fields from `dws_stock_factor_wide`, including field aliases such as `$volume -> vol`, `$vwap -> avg_price`, and `$turnover -> coalesce(turnover_rate_f, turn_over)`.
- DQC recomputes the expected value with a reference evaluator implemented separately from the production `FactorEngine` and ClickHouse executable UDF path.
- The expected value is compared with `dws_stock_factor_wide_matrix.<factor_id>` using absolute and relative tolerances.
- Evaluated comparisons are written to `dq_dqc_sample` with `sample_type=factor_cross_check_passed` or `sample_type=factor_cross_check_failed`; the JSON payload includes the factor expression, actual value, expected value, diffs, and history window.
- Unsupported expression operators are reported as a `MONITOR` coverage result instead of being treated as pass.

## Configuration

```yaml
quality:
  dqc_mode: warn_only
  dqc_baseline_window_days: 60
  dqc_min_baseline_days: 20
  dqc_spot_check_samples: 50
  dqc_factor_cross_check_samples: 20
  dqc_factor_cross_check_history_rows: 260
  dqc_factor_cross_check_abs_tolerance: 1.0e-8
  dqc_factor_cross_check_rel_tolerance: 1.0e-6
  dqc_create_result_tables: true
```

`warn_only` is the default so daily jobs can establish baselines before DQC becomes a strict operational gate.

## CLI

Run the full DWS factor panel suite:

```bash
python main.py quality dqc --layer dws --suite stock_factor_panel --as-of-date 2026-05-26
```

Run one table:

```bash
python main.py quality dqc --layer dws --table dws_stock_factor_wide --as-of-date 2026-05-26
```

Run all tables in the default DWS suite:

```bash
python main.py quality dqc --layer dws --all --as-of-date 2026-05-26
```

## Extension Pattern For ADS

An ADS suite should define:

- supported tables
- suite domain, for example `portfolio`, `risk`, `signal`, or `backtest`
- table-level completeness and freshness metrics
- semantic rules specific to ADS outputs
- cross-table or source-to-output consistency checks
- monitoring metrics that can be drifted through `dq_dqc_metric`

The suite should return generic `DqcResult`, `DqcMetric`, `DqcConsistency`, and `DqcSample` records. It should not create ADS-specific result tables unless there is a proven reporting need that cannot be handled by the generic schema.
