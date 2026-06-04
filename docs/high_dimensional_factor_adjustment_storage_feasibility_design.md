# Feasibility Design: PIT-Adjusted Storage for High-Dimensional Stock Factors

## 1. Executive Summary

The solution described in `docs/高维因子复权存储方案_增强版.md` is feasible to integrate into the current `tushare-integration` project, but it should not be implemented as a separate storage subsystem copied verbatim from the proposal.

The current project already has the most important primitives needed by the proposal:

- ODS raw tables preserve source-row metadata: `_source`, `_api_name`, `_batch_id`, `_ingest_time`, `_record_hash`, and `_raw_json`.
- DWD tables derive standardized security identifiers, `available_trade_date`, and system-version windows using `sys_from` and `sys_to`.
- DWD publishing and DWS publishing already use staging tables and atomic table replacement on ClickHouse.
- `dwd_stock_eod_price` and `dwd_stock_adj_factor` already exist as standardized inputs.
- `dws_stock_factor_wide` and `dws_stock_factor_wide_matrix` already define a factor-serving path.

The main gap is in the DWS layer. The current DWS build path uses only latest DWD versions (`sys_to = 9999-12-31`), joins raw price fields into the factor input table, and computes the matrix without an explicit replay timestamp, adjustment anchor, factor run identifier, or point-in-time factor version. Therefore, the proposal is directionally correct, but the appropriate project-local design is:

> Keep the existing ODS and DWD bitemporal foundation, add a ClickHouse-native adjusted-price projection, then make factor materialization PIT-aware and versioned at the DWS boundary.

This avoids a disruptive storage rewrite while solving the actual problem: adjusted prices and factors must be reproducible under the information set visible at a given decision date.

## 2. Problem Statement

High-dimensional stock factors often depend on cross-day price comparisons, rolling windows, returns, volatility, drawdown, and technical indicators. If these factors use unadjusted prices, corporate actions such as dividends, bonus issues, rights issues, splits, and consolidations create mechanical price discontinuities that are misread as market signals.

Using the latest forward-adjusted series everywhere is also incorrect for strict backtesting. A forward-adjusted historical price can change after a future corporate action, so recomputing old training or backtest samples with today's latest adjustment factor can introduce future information.

The system therefore needs to support:

- Raw price preservation.
- Adjustment factor versioning.
- Forward-adjusted price computation under a specific information set.
- Factor computation from adjusted or raw fields according to each factor's business meaning.
- Reproducible factor runs with data lineage.
- Efficient repeated access for training, backtesting, and daily inference.

## 3. Current Project Assessment

### 3.1 Existing Data Layers

The current ingestion pipeline writes both raw and latest tables. Raw tables preserve nulls and append source metadata, including `_ingest_time`, `_batch_id`, `_record_hash`, and `_raw_json`. Latest tables are optimized for current operational reads.

The DWD layer standardizes source tables into domain tables. DWD schemas include `instrument_id`, `instrument_type`, `exchange`, `source_code`, `event_date`, `available_trade_date`, `sys_from`, `sys_to`, `source`, `source_table`, `source_batch_id`, and `source_record_hash`.

For stock daily prices and adjustment factors, the relevant DWD tables are:

- `dwd_stock_eod_price`
- `dwd_stock_adj_factor`

Both use `trade_date` as the business event date and derive `available_trade_date` as the next trading day where possible.

### 3.2 Existing Factor Path

The DWS path currently has two materialized outputs:

- `dws_stock_factor_wide`: a wide stock panel assembled from DWD prices, adjustment factors, daily basics, quote metrics, financial statements, margin data, chip distribution, and other inputs.
- `dws_stock_factor_wide_matrix`: a physical factor matrix generated from `dws_stock_factor_wide` through the `dws_stock_factor_rows` ClickHouse executable UDF.

The matrix engine records a `mapping_hash` inside the intermediate JSON payload and derives `source_record_hash` from source hashes plus factor values. However, the final matrix table expands factor values into physical columns and does not persist a first-class `factor_mapping_hash`, `factor_run_id`, adjustment-anchor metadata, or replay timestamp.

### 3.3 Current PIT Capability

The project has partial PIT infrastructure but not a PIT-safe factor service:

- DWD tables can represent source-row revisions through `sys_from/sys_to`.
- DWD rows expose `available_trade_date`, which is the right trading-day visibility control for daily strategies.
- DWS queries currently filter upstream DWD tables to latest rows by `sys_to = 9999-12-31`.
- DWS does not accept or persist an explicit `asof_date`, `asof_trade_date`, or `replay_time`.
- Factor computation currently sees raw prices and the current latest adjustment factor, but does not compute PIT-safe forward-adjusted fields.

This means the project is close to the proposed architecture at the raw/DWD level, but not at the adjusted-price and factor-serving level.

## 4. Feasibility of Integrating the Proposal

### 4.1 Feasible Components

The following parts of the proposal fit the current project well:

- Raw market data should remain immutable and traceable.
- Adjustment factors should be versioned instead of overwritten.
- Forward-adjusted prices should be derived from raw prices and adjustment factors.
- High-use adjusted price fields should be materialized for daily data.
- Factor outputs should record input versions, factor expression versions, and calculation runs.
- Query semantics must distinguish business date from information availability date.
- Staging-to-production publication should be used to avoid half-published data.

### 4.2 Components That Need Adaptation

The proposal uses `asof_date` as the central PIT column. The current project already uses:

- `available_trade_date` for trading-day-level visibility.
- `sys_from/sys_to` for system-version replay.

Adding a separate `asof_date` everywhere would create duplicate semantics unless carefully defined. The recommended mapping is:

| Proposal Term | Project-Local Term | Meaning |
| --- | --- | --- |
| `trade_date` | `event_date` / `trade_date` | Market date of the observation. |
| `asof_date` | `available_trade_date` | Earliest trading date when the row may be used for a decision. |
| `version` | `sys_from`, `sys_to`, `source_batch_id`, `source_record_hash` | System version lineage. |
| `adj_factor_version` | selected `dwd_stock_adj_factor.source_record_hash` and `sys_from` | Adjustment-factor source version. |
| `factor_version` | `factor_mapping_hash` plus factor library version | Factor expression and parameter version. |

For external-facing queries and documentation, `asof_trade_date` can be introduced as an alias for `available_trade_date`, because it is clearer to research users. Internally, the existing column should remain authoritative.

### 4.3 Integration Difficulty

Integration difficulty is moderate, not high. The main work is in DWS SQL generation, schema additions, factor mapping changes, quality checks, and tests. No replacement of the ingestion pipeline or database engine is required for the first production-grade iteration.

The highest-risk implementation detail is not storage. It is correctly computing the adjustment anchor under the information set visible at the factor decision date.

## 5. Recommended Architecture

### 5.1 Design Choice

Use a ClickHouse-native bitemporal model:

```text
ODS raw append-only source records
  -> DWD standardized bitemporal source tables
  -> DWS adjusted-price projection
  -> DWS factor wide input with raw and adjusted fields
  -> DWS factor matrix with run/version metadata
```

This is more appropriate for the current project than a full lakehouse migration or a new standalone feature store, because the project already targets ClickHouse and already contains DWD/DWS builders.

### 5.2 Price Adjustment Formula

For a stock `s`, trade date `t`, and decision visibility date `A`:

```text
forward_adjusted_price(s, t, A)
  = raw_price(s, t, A) * adj_factor(s, t, A) / anchor_adj_factor(s, A)
```

Where:

- `raw_price(s, t, A)` is the visible raw price version for `s,t` at decision date `A`.
- `adj_factor(s, t, A)` is the visible adjustment-factor version for `s,t` at decision date `A`.
- `anchor_adj_factor(s, A)` is the adjustment factor for the latest trade date that is visible at decision date `A`.

For daily T+1 factors, `A` should normally be the row's `available_trade_date`. For a price row with `trade_date = D`, this usually means the factor becomes available on the next trading day, and the anchor is the latest completed trading day visible before that decision.

### 5.3 Versioned Adjusted-Price Store

Add a new DWS table:

```text
dws_stock_adjusted_price_versioned
```

Recommended grain:

```text
instrument_id, trade_date, asof_trade_date, price_version
```

This table must be append/versioned. It must not be a latest-only table if historical reproducibility is a key requirement. If stock `A` has a new adjustment-factor version tomorrow that changes the adjusted price for `2025-05-05`, the system should append a new adjusted-price version for `A, 2025-05-05`; it should not overwrite the previous adjusted-price version.

Recommended columns:

| Column | Purpose |
| --- | --- |
| `instrument_id` | Standard security identifier. |
| `instrument_type` | Should be `stock` initially. |
| `exchange` | Exchange code. |
| `source_code` | Tushare security code. |
| `event_date` | Business date, same as `trade_date`. |
| `trade_date` | Market trading date. |
| `asof_trade_date` | Trading date at which this adjusted-price version becomes visible. Internally this is aligned with `available_trade_date`. |
| `price_version` | Unique adjusted-price version or run identifier. |
| `price_version_from` | First trading date for which this version is visible. |
| `price_version_to` | Optional closing bound for convenience; may be derived by query if the table is append-only. |
| `is_current` | Optional serving flag, not the source of historical truth. |
| `price_asof_mode` | Adjustment policy, for example `pit_qfq_v1`. |
| `open`, `high`, `low`, `close`, `pre_close` | Raw prices preserved for same-day shape and execution logic. |
| `open_qfq`, `high_qfq`, `low_qfq`, `close_qfq`, `pre_close_qfq` | PIT-safe forward-adjusted prices. |
| `avg_price_qfq` | Optional adjusted VWAP/average price if source `avg_price` exists. |
| `adj_factor` | Visible adjustment factor for `trade_date`. |
| `anchor_trade_date` | Trade date used as forward-adjustment anchor. |
| `anchor_adj_factor` | Visible adjustment factor at `anchor_trade_date`. |
| `raw_price_sys_from` | Selected DWD price system version. |
| `adj_factor_sys_from` | Selected DWD adjustment-factor system version. |
| `anchor_adj_factor_sys_from` | Selected anchor adjustment-factor system version. |
| `source_batch_id` | Combined lineage batch ID. |
| `source_record_hash` | Combined lineage hash. |
| `build_time` | Materialization timestamp. |

The table should use `asof_trade_date` or `trade_date` partitioning depending on observed query patterns. For current-date production, expose a view that selects the latest visible version per `instrument_id, trade_date, price_asof_mode`. The view is a convenience layer; the versioned table is the system of record.

Example version behavior:

```text
2026-06-03:
  A, 2025-05-05, asof_trade_date=2026-06-03, price_version=P20260603, uses adj_factor v5

2026-06-04:
  A, 2025-05-05, asof_trade_date=2026-06-04, price_version=P20260604, uses adj_factor v6
```

Both rows must remain available. A query for the 2026-06-03 information set should select `P20260603`; a query for the 2026-06-04 information set should select `P20260604`.

### 5.4 Factor Wide Input

Modify `dws_stock_factor_wide` so that it joins from the versioned adjusted-price store or from a latest/as-of view over that store instead of directly using only raw `dwd_stock_eod_price` and `dwd_stock_adj_factor`.

Keep raw fields and add adjusted fields:

- Preserve `open`, `high`, `low`, `close`, `pre_close`, `vol`, `amount`, and existing business metrics.
- Add `open_qfq`, `high_qfq`, `low_qfq`, `close_qfq`, `pre_close_qfq`, `avg_price_qfq`.
- Add adjusted chip-cost fields only for cross-day chip-cost factors, for example `cost_5pct_qfq`, `cost_50pct_qfq`, `cost_95pct_qfq`, and `weight_avg_cost_qfq`.
- Do not adjust volume, amount, turnover, valuation, market capitalization, or financial statement fields.

This preserves raw semantics for execution and same-day candle factors while giving rolling and return-based factors a continuous price basis.

### 5.5 Versioned Factor Matrix

Keep a wide factor matrix for the default serving path, because the existing schema and tests already assume physical factor columns and wide storage is efficient for common training and backtest scans. However, the production-grade matrix must be versioned. A latest-only matrix would lose historical factor values when a later adjustment-factor version changes old adjusted prices.

Recommended versioned table:

```text
dws_stock_factor_wide_matrix_versioned
```

Recommended grain:

```text
instrument_id, trade_date, factor_run_id
```

If factors are recomputed in groups, add `factor_group` to the grain or maintain one run manifest row per factor group.

Add metadata columns:

| Column | Purpose |
| --- | --- |
| `factor_mapping_hash` | Hash of factor expressions and parameters used for this run. |
| `factor_library_version` | Semantic factor library version, if maintained. |
| `factor_run_id` | Unique calculation batch ID. |
| `asof_trade_date` | Information-set date used by the factor run. |
| `input_price_version` | Adjusted-price version used by the row. |
| `input_panel_hash` | Hash of selected input row hashes. |
| `price_adjustment_mode` | For example `pit_qfq_v1`. |
| `max_input_available_trade_date` | Defensive audit column. |

The long table proposed in the source document is useful for sparse or experimental factors, but it should be optional. For the current project, a versioned wide matrix plus explicit run metadata is the more practical default.

Example factor version behavior:

```text
2026-06-03:
  A, 2025-05-05, factor_run_id=F20260603, input_price_version=P20260603

2026-06-04:
  A, 2025-05-05, factor_run_id=F20260604, input_price_version=P20260604
```

Both factor rows must remain available. Current production consumers should read through a latest-view or snapshot manifest; replay consumers should select by `factor_run_id`, `asof_trade_date`, or snapshot identifier.

### 5.6 Factor Mapping Changes

Update factor expressions by semantic category:

- Use `_qfq` fields for cross-day price comparisons, returns, rolling highs/lows, moving averages, volatility, drawdown, and technical indicators.
- Use raw OHLC fields for same-day candle shape and same-day price ratios.
- Use raw `vol`, `amount`, turnover, valuation, market value, and financial statement fields for business metrics that are not price levels.
- Use adjusted chip-cost fields only when comparing chip-cost price levels across dates.

This matches the existing adjustment policy document in `docs/prd/factor/v1/dws_stock_factor_wide_matrix_adjustment_policy.md`.

## 6. Query Semantics

### 6.1 Latest Production Query

For routine daily production, users may read a latest published view for the target `trade_date`, but the underlying adjusted-price and factor tables must remain append/versioned.

The latest view should resolve the newest visible version, for example:

```sql
SELECT *
FROM (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY instrument_id, trade_date, price_asof_mode
            ORDER BY asof_trade_date DESC, price_version DESC
        ) AS version_rank
    FROM dws_stock_adjusted_price_versioned
    WHERE asof_trade_date <= :decision_trade_date
)
WHERE version_rank = 1;
```

The same pattern applies to the factor matrix with `factor_run_id` or a snapshot manifest. The view is allowed to look like a complete current table, but it must be derived from versioned rows.

### 6.2 Historical Replay Query

A strict replay query must filter both visibility and system version:

```sql
WHERE available_trade_date <= :decision_trade_date
  AND sys_from <= :replay_timestamp
  AND :replay_timestamp < sys_to
```

For DWS tables that do not carry `sys_from/sys_to`, the calculation run metadata must identify the exact DWD snapshot or replay timestamp used to build the table.

### 6.3 Recommended View Layer

Expose named views rather than requiring users to write PIT predicates manually:

- `v_dwd_stock_eod_price_asof`
- `v_dwd_stock_adj_factor_asof`
- `v_dws_stock_adjusted_price_latest`
- `v_dws_stock_adjusted_price_asof`
- `v_dws_stock_factor_matrix_latest`
- `v_dws_stock_factor_matrix_asof`

For parameterized use cases, provide query templates or manager methods instead of relying on ad hoc SQL.

### 6.4 Daily Incremental Publishing Semantics

The daily process should produce a new logical complete dataset by merging yesterday's published versions with today's deltas, without overwriting historical rows.

The intended semantics are:

```text
previous published versioned rows
+ new trade-date rows
+ new adjusted-price versions for stocks with new adjustment information
+ new factor versions for affected stock/date/window ranges
= current logical snapshot
```

Physically, the system should append only new and changed versions. A snapshot manifest or latest view then exposes the current whole dataset.

For example, if stock `A` receives new adjustment information on 2026-06-04, and that information changes the adjusted price for `2025-05-05`, the system should append:

```text
dws_stock_adjusted_price_versioned:
  A, 2025-05-05, asof_trade_date=2026-06-04, price_version=P20260604

dws_stock_factor_wide_matrix_versioned:
  A, 2025-05-05, factor_run_id=F20260604, input_price_version=P20260604
```

The previous rows from 2026-06-03 remain queryable. The current snapshot view selects the 2026-06-04 versions; a replay for 2026-06-03 selects the earlier versions.

## 7. Alternative Solutions

### 7.1 Use Latest Vendor Forward-Adjusted Fields

The project already has source schemas such as `stk_factor` and `stk_factor_pro` that include `*_qfq` fields. These are useful as validation references, but they are not an appropriate source of truth for strict PIT factor storage.

Reasons:

- Vendor-adjusted fields usually represent the vendor's current adjustment view.
- They do not expose the full adjustment-anchor and version lineage needed to replay a historical decision date.
- They couple the factor system to a vendor-specific adjustment implementation.

Recommendation: use these fields only for QA comparisons and fallback diagnostics.

### 7.2 Compute Adjusted Prices and Factors at Query Time

This minimizes storage but is not appropriate as the primary solution for high-dimensional production factors.

Reasons:

- Repeated backtests and training jobs would recompute the same rolling windows.
- Query latency would be unpredictable.
- Concurrent research workloads would duplicate compute.
- Reproducibility would depend on every query consistently applying the same as-of logic.

Recommendation: allow query-time computation for ad hoc research, but materialize daily adjusted prices and standard factor matrices.

### 7.3 Store Daily Full Snapshots

Daily full snapshots are the simplest strict PIT model, but they are not cost-effective for this project.

Reasons:

- Most adjustment-factor changes are sparse relative to the full stock-date-factor cube.
- Daily snapshots multiply storage by the number of snapshot dates.
- Repair and backfill become slow and operationally expensive.

Recommendation: do not snapshot the entire high-dimensional factor matrix daily.

### 7.4 Move to Iceberg, Delta Lake, or Hudi

Open table formats provide table snapshot and time-travel capabilities. Iceberg supports time-travel queries by timestamp or snapshot version and keeps snapshots for reproducible reads; Delta Lake and Hudi also support time-travel style reads through their transaction timelines. These systems are appropriate when the platform needs object-store-first storage, multi-engine access, large historical table snapshots, or stronger lakehouse governance.

They are not the best first step for this project.

Reasons:

- The current runtime, schema templates, DWD/DWS managers, and quality checks are ClickHouse-centered.
- Table-level time travel does not by itself solve business PIT semantics for adjustment anchors and factor expressions.
- A lakehouse migration would introduce Spark/Trino/Flink/catalog operations before the adjustment problem is solved.

Recommendation: keep ClickHouse for the first implementation. Reconsider Iceberg/Delta/Hudi only if multi-engine lakehouse access or object-storage snapshot governance becomes a platform requirement.

### 7.5 Export Parquet and Query with DuckDB

DuckDB can query Parquet files efficiently with projection and filter pushdown. This is attractive for offline research packages, reproducible experiment bundles, and local analysis.

It is not a replacement for the production factor store.

Reasons:

- It does not provide a shared, governed, multi-user publishing model by itself.
- PIT semantics would still need to be encoded in exported datasets and manifests.
- Repeated production queries over shared datasets are better served from ClickHouse in the current architecture.

Recommendation: use Parquet/DuckDB as an export and research-consumption format after ClickHouse materialization.

## 8. Implementation Plan

### Phase 1: PIT-Adjusted Price Foundation

1. Add `dws_stock_adjusted_price_versioned.yaml`.
2. Add a DWS builder for append-only PIT-safe daily adjusted-price versions.
3. Implement anchor selection using only rows visible by `available_trade_date`.
4. Preserve raw price fields and add `_qfq` fields.
5. Add latest/as-of views over the versioned adjusted-price table.
6. Add quality checks:
   - Adjustment factors must be positive.
   - Anchor adjustment factor must be non-null when adjusted fields are produced.
   - `asof_trade_date` / `available_trade_date` must not be earlier than `trade_date`.
   - A versioned row must not duplicate `instrument_id, trade_date, asof_trade_date, price_version`.
   - Adjusted same-day ratios should match raw same-day ratios within tolerance.
   - Non-event discontinuity checks should flag suspicious adjusted return jumps.

### Phase 2: Factor Input and Mapping

1. Modify `dws_stock_factor_wide` to read adjusted-price fields.
2. Extend `STOCK_FACTOR_WIDE_MATRIX_ALIASES` and source-field extraction to include `_qfq` fields.
3. Update factor mapping CSVs so cross-day price factors use `_qfq` fields.
4. Add regression tests for representative factors:
   - Rolling return.
   - Moving-average bias.
   - Same-day candle shape.
   - Volume-only factor.
   - Price-volume factor using adjusted price and raw volume.

### Phase 3: Versioned Factor Matrix and Run Metadata

1. Add `dws_stock_factor_wide_matrix_versioned.yaml`.
2. Add `factor_mapping_hash`, `factor_run_id`, `asof_trade_date`, `input_price_version`, `price_adjustment_mode`, and `input_panel_hash` to the versioned matrix.
3. Expose latest/as-of views over the versioned matrix.
4. Persist a small run manifest table:

```text
dws_factor_run_manifest
```

Recommended columns:

| Column | Purpose |
| --- | --- |
| `factor_run_id` | Unique run identifier. |
| `run_started_at` | Run start timestamp. |
| `run_finished_at` | Run finish timestamp. |
| `factor_mapping_hash` | Expression mapping hash. |
| `factor_count` | Number of factors. |
| `price_adjustment_mode` | Adjustment policy identifier. |
| `snapshot_id` | Logical snapshot identifier exposed to consumers. |
| `parent_snapshot_id` | Previous published snapshot used as the base. |
| `source_tables` | Source table list. |
| `source_max_available_trade_date` | Maximum visible source date used. |
| `changed_instrument_count` | Number of instruments with newly materialized versions. |
| `changed_row_count` | Number of adjusted-price or factor rows appended by the run. |
| `code_commit_id` | Code version, when available. |
| `status` | Staging, published, failed, or retired. |

### Phase 4: Incremental Recalculation

Start with full rebuilds through staging tables for correctness if needed, but the target state is daily append-only affected-window recomputation. The daily job should append new versions and publish a snapshot manifest; it should not overwrite previous adjusted-price or factor versions.

Affected windows should be derived from:

- changed `dwd_stock_adj_factor` records,
- changed `dwd_stock_eod_price` records,
- changed factor mapping hash,
- maximum rolling window used by affected factors,
- downstream factor dependencies.

For a changed price or adjustment factor at trade date `D`, recompute at least:

```text
[D, D + max_factor_window]
```

for affected instruments and price-dependent factors.

The daily delta should include:

- current trade-date raw price and adjusted-price rows,
- adjusted-price versions for prior dates impacted by newly visible adjustment information,
- factor versions for dates impacted by changed adjusted prices and rolling-window dependencies,
- a manifest row that marks the new logical snapshot as published.

## 9. ClickHouse-Specific Design Notes

The current table template uses `MergeTree` when no primary key is declared and `ReplacingMergeTree` when a primary key exists. For PIT tables, do not rely on background deduplication as the only correctness mechanism. ClickHouse replacement happens during merges and may leave multiple versions visible before merge completion unless queries use deterministic latest-row selection.

For versioned DWD/DWS queries:

- Use explicit `row_number()` or `argMax` selection when reading visible versions.
- Avoid `FINAL` as a default user-facing mechanism on large tables unless benchmarked.
- Keep ordering keys aligned with query filters: `instrument_id`, `trade_date`, `asof_trade_date` / `available_trade_date`, and version columns.
- Use staging tables and `EXCHANGE TABLES` or equivalent atomic publish flow for full rebuilds.

ASOF joins are useful for selecting the latest known financial or anchor row under a non-exact date condition, but the join condition must be constrained by instrument and visibility date.

## 10. Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Incorrect anchor date | Future information leakage | Add explicit anchor columns and PIT anchor tests. |
| Ambiguous `asof_date` versus `available_trade_date` | Query inconsistency | Use `available_trade_date` internally and expose `asof_trade_date` only as an alias. |
| Factor mapping partially migrated | Mixed raw/adjusted semantics | Classify factor expressions and add tests by category. |
| Full matrix rebuild cost | Slow daily publish | Start full rebuild for correctness, then implement affected-window recomputation. |
| Latest-only DWS table accidentally used as source of truth | Loss of historical adjusted-price or factor versions | Make versioned DWS tables the source of truth; expose latest data only through views or manifests. |
| Incremental merge omits an affected rolling window | Current snapshot inconsistent with factor dependencies | Derive affected windows from changed input dates and maximum factor lookback; test with simulated corporate actions. |
| Vendor adjustment mismatch | False QA failures | Treat vendor `*_qfq` as reference only, not authoritative truth. |
| ClickHouse replacement semantics misunderstood | Duplicate/latest ambiguity | Use explicit version filters and staging publication. |
| Wide matrix schema growth | Operational friction | Keep the wide matrix for stable production factors; use optional long table for experimental factors. |

## 11. Acceptance Criteria

The implementation should be considered correct only when all of the following are true:

1. A factor row for trade date `D` can be shown to use only source rows with `available_trade_date <= decision_trade_date`.
2. Forward-adjusted fields for `D` use an anchor adjustment factor visible at the decision date, not today's latest anchor.
3. Raw prices remain available in DWS for execution, same-day candle, and same-day ratio factors.
4. Cross-day price factors are migrated to `_qfq` fields.
5. Factor matrix rows persist `factor_mapping_hash` and `factor_run_id`.
6. A run manifest can identify the source tables, adjustment policy, factor expression version, and calculation timestamp.
7. Quality checks fail publication for non-positive adjustment factors, missing anchors, and visibility-date violations.
8. Regression tests demonstrate that a simulated future corporate action does not change previously published PIT factor rows unless a replay run explicitly chooses a later decision date.
9. When a new adjustment-factor version appears on a later day, the system appends new adjusted-price and factor versions for affected rows while preserving the previous versions.
10. The latest production dataset is exposed as a logical snapshot or latest view over versioned rows, not as the only physical copy of the data.

## 12. Final Recommendation

Integrate the proposal, but adapt it to the existing project rather than adding a parallel storage model.

The recommended solution is:

```text
Existing ODS raw version history
+ existing DWD sys_from/sys_to and available_trade_date
+ new append-only DWS PIT-adjusted price versions
+ adjusted/raw factor input fields
+ append-only versioned wide factor matrix with run manifest
+ daily incremental affected-window recomputation
+ latest/as-of views or snapshot manifests for complete-dataset reads
```

This provides the best balance of correctness, implementation effort, storage cost, and compatibility with the current ClickHouse-based codebase.

## 13. References

- ClickHouse ReplacingMergeTree documentation: https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree
- ClickHouse JOIN documentation, including ASOF JOIN: https://clickhouse.com/docs/sql-reference/statements/select/join
- Apache Iceberg Spark queries and time travel: https://iceberg.apache.org/docs/latest/spark-queries/
- Apache Iceberg maintenance and snapshot expiration: https://iceberg.apache.org/docs/latest/maintenance/
- Delta Lake time travel article: https://delta.io/blog/2023-02-01-delta-lake-time-travel/
- Apache Hudi SQL queries and time travel: https://hudi.apache.org/docs/sql_queries/
- DuckDB Parquet documentation: https://duckdb.org/docs/current/data/parquet/overview
- DuckDB Parquet query guide: https://duckdb.org/docs/current/guides/file_formats/query_parquet
