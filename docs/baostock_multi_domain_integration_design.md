# Baostock Multi-Domain Integration Design

## Summary

Baostock is integrated as the first non-Tushare source for the core daily market, security master, industry, index, quarterly financial, financial indicator, and express-report domains. The integration keeps source data isolated in Baostock ODS tables, then publishes comparable standardized data into parallel Baostock DWD tables.

Baostock rows are intentionally not merged into existing Tushare physical DWD tables in v1. Existing production DWS factor tables remain Tushare-primary. Baostock is used first for validation, source coverage monitoring, and future failover planning.

Baostock ingestion and DWD sync intentionally exclude source business dates/report periods before `2015-01-01`.

## Source Isolation Requirement

Each data-source pipeline must be self-contained while scraping ODS data and while calculating its own DWD layer. A Baostock spider or Baostock DWD sync must not read Tushare ODS, DWD, calendar, security-master, or helper tables; likewise, a Tushare spider or Tushare DWD sync must not read Baostock tables. Shared framework code is allowed only when it is source-neutral and does not introduce data dependencies across providers.

This rule is required for cross-source validation to be meaningful. If one source uses another source's data during scraping or DWD calculation, later validation would compare a dependent dataset against the dataset it already consumed, hiding real provider differences and producing false confidence.

Calendar handling follows the same rule. Baostock daily spiders and Baostock DWD PIT/availability calculations use `baostock_trade_dates`, populated from Baostock `query_trade_dates`; they must not use Tushare `trade_cal`. Tushare pipelines continue to use Tushare `trade_cal`.

## Source Layout

Baostock code is isolated under source-specific paths:

- Spiders: `tushare_integration/spiders/baostock/`
- ODS schemas: `tushare_integration/schema/baostock/`
- DWD schemas: `tushare_integration/schema/dwd/baostock/`
- Tests: `tests/test_baostock_integration.py`

Shared changes are limited to neutral framework support:

- Recursive DWD schema discovery under `schema/dwd/**`.
- A `mapped_versioned` DWD builder for mapping source-specific fields into Tushare-compatible domain shapes.
- Cross-source validation manager and CLI.
- Baostock settings for lower bounds and incremental backfill.

## ODS Tables

Baostock ODS tables preserve Baostock field names and use existing latest/raw metadata behavior. The pipeline sets `_source = baostock`.

Primary ODS tables:

- `baostock_trade_dates`
- `baostock_stock_basic`
- `baostock_stock_industry`
- `baostock_stock_daily`
- `baostock_index_daily`
- `baostock_stock_balance`
- `baostock_stock_profit`
- `baostock_stock_cash_flow`
- `baostock_stock_operation`
- `baostock_stock_growth`
- `baostock_stock_debt`
- `baostock_stock_dupont`
- `baostock_stock_financial_indicator`
- `baostock_stock_express`

Each ODS table also has a raw table with the existing `_raw` suffix, for example `baostock_stock_daily_raw`.

Baostock API request reservations are recorded in `baostock_api_request_log`. This table is source-specific and is used only to enforce Baostock request limits.

`baostock_trade_dates` is the Baostock calendar counterpart used by Baostock incremental scraping and DWD calendar mapping. It is sourced from Baostock `query_trade_dates` and is intentionally separate from Tushare `trade_cal`.

## DWD Tables

Baostock DWD tables are parallel physical tables:

- `dwd_baostock_stock_eod_price`
- `dwd_baostock_stock_daily_basic`
- `dwd_baostock_security_master`
- `dwd_baostock_stock_industry`
- `dwd_baostock_stock_income`
- `dwd_baostock_stock_balance_sheet`
- `dwd_baostock_stock_cashflow`
- `dwd_baostock_stock_financial_indicator`
- `dwd_baostock_index_eod_price`
- `dwd_baostock_stock_express`

Tushare also now has `dwd_stock_express`, so Baostock express reports can be compared to the corresponding Tushare express domain.

## Field Mapping

Baostock codes are normalized into Tushare-style codes:

- `sh.600000` -> `600000.SH`
- `sz.000001` -> `000001.SZ`
- `bj.430047` -> `430047.BJ`

Instrument IDs use the normalized code:

- Stock: `stock:<ts_code>`
- Index: `index:<ts_code>`

Daily stock price mapping:

- `date` -> `trade_date` / `event_date`
- `code` -> normalized `ts_code`
- `preclose` -> `pre_close`
- `volume` -> `vol`
- `pctChg` -> `pct_chg`
- `adjustflag` is retained for audit and validation.

Daily stock basic mapping:

- `turn` -> `turnover_rate`
- `peTTM` -> `pe_ttm`
- `pbMRQ` -> `pb`
- `psTTM` -> `ps_ttm`
- `pcfNcfTTM` -> `pcf_ncf_ttm`
- `tradestatus` -> `trade_status`
- `isST` -> `is_st`
- Unsupported Tushare fields, such as free-float share, remain nullable.

Financial statement mapping:

- `pubDate` -> `ann_date`
- `statDate` -> `end_date` / `event_date`
- `available_trade_date` uses the next open Baostock trade date after `ann_date`; if publication date is missing, it falls back to the report period date.
- Baostock financial schemas are narrower than Tushare, so unsupported comparable fields remain nullable.

Financial indicator mapping:

- Multiple Baostock quarterly factor endpoints are combined into `baostock_stock_financial_indicator`.
- The combined DWD target is `dwd_baostock_stock_financial_indicator`.

Security master enrichment:

- `dwd_baostock_security_master` uses `baostock_stock_basic_raw`.
- It enriches `industry` from `baostock_stock_industry_raw`.
- A separate `dwd_baostock_stock_industry` table is retained for source-specific industry audit.

## Jobs

Configured jobs:

```bash
python main.py run job baostock/stock/basic
python main.py run job baostock/stock/quotes
python main.py run job baostock/stock/financial
python main.py run job baostock/index/quotes
```

Job contents:

- `baostock/stock/basic`: stock basic, industry, and Baostock trade calendar.
- `baostock/stock/quotes`: stock daily OHLCV and daily indicators.
- `baostock/stock/financial`: quarterly financial statements, factor endpoints, merged financial indicator, and express reports.
- `baostock/index/quotes`: index daily OHLCV.

Financial backfill iterates years `2015..current_year` and quarters `1..4`.

Daily and index jobs start from `2015-01-01` on first ingestion. Incremental runs use `baostock_incremental_backfill_days` to choose a recent lookback window, then use `baostock_trade_dates` to request only Baostock trading dates missing from the target Baostock ODS table.

## DWD Usage

Examples:

```bash
python main.py dwd list
python main.py dwd sql dwd_baostock_stock_income
python main.py dwd sync dwd_baostock_stock_income
```

The `mapped_versioned` DWD builder:

- Builds DWD output from explicit target-column expressions.
- Preserves source lineage fields.
- Supports PIT/version windows with source business keys.
- Supports source filters such as `src.statDate >= toDate32('2015-01-01')`.
- Supports source-side joins, currently used for Baostock security-master industry enrichment.
- Uses source-specific calendar maps. Baostock DWD tables use `baostock_trade_dates`; Tushare DWD tables use `trade_cal`.

## Cross-Source Validation

Cross-source validation is available through:

```bash
python main.py quality cross-source stock_eod_price --as-of-date YYYY-MM-DD
```

Supported domains:

- `stock_eod_price`
- `stock_daily_basic`
- `security_master`
- `stock_financial_statement`
- `stock_financial_indicator`
- `index_eod_price`

Validation result tables:

- `dq_cross_source_run`
- `dq_cross_source_result`
- `dq_cross_source_diff`
- `dq_source_quality_metric`

Validation starts as `warn_only` unless overridden. `BLOCKER` severity is reserved for invalid internal data, severe key coverage loss, adjusted stock-price rows, impossible OHLC, and major price mismatches.

Only comparable fields are compared. Source-unavailable or definition-mismatched fields are left nullable or monitored rather than forced into false diffs.

## Baostock Runtime Dependency

The Baostock spiders require:

```bash
python -m pip install baostock==0.9.2
```

This dependency is listed in both `requirements.txt` and `pyproject.toml`.

## Settings

Baostock-specific settings:

```yaml
baostock_start_date: "2015-01-01"
baostock_incremental_backfill_days: 7
baostock_daily_request_limit: 50000
```

Environment overrides:

```bash
BAOSTOCK_START_DATE=2015-01-01
BAOSTOCK_INCREMENTAL_BACKFILL_DAYS=7
BAOSTOCK_DAILY_REQUEST_LIMIT=50000
```

`baostock_daily_request_limit` applies only to Baostock API calls. A value of `0` disables this source-specific cap. Each Baostock data API call reserves one request before calling the provider, so failed provider calls still count toward the safety limit.

## Verification

Current regression coverage:

- Code normalization for SH/SZ/BJ.
- Baostock spider item schema padding.
- Recursive DWD discovery.
- `mapped_versioned` SQL rendering.
- Financial PIT publication-date fallback.
- Cross-source metadata and comparison SQL.
- Existing project regression suite.

Verification commands:

```bash
python -m unittest tests.test_baostock_integration
python -m unittest discover
```
