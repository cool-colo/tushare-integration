# Project Memory

## ClickHouse connectivity

- ClickHouse is accessible outside the Codex sandbox on port `8123`.
- A failed request to `127.0.0.1:8123` from inside the sandbox does not establish that ClickHouse is stopped.
- Project default connection: `clickhouse://127.0.0.1:8123/default`, user `default`, empty password.
- Run ClickHouse queries in an environment with host-network access when validating data.

## RiceQuant / RQData interface

### Authoritative references and SDK

- Official Python API documentation: <https://www.ricequant.com/doc/rqdata/python/index-rqdatac>.
- Upstream skill repository: <https://github.com/ricequant/ricequant-skills>; only the
  `basic` material is relevant to this ingestion project unless research work is
  explicitly requested.
- The project pins `rqdatac==3.8.1`. Interface fields and behavior must be checked
  against that installed version instead of inferred from similarly named Tushare
  fields.
- The detailed local design and extension rules are in
  `docs/ricequant_integration_design.md`.

### Authentication and transport

- RiceQuant supplies one opaque RQSDK license/token, not a username and password.
- Store it only as `RQDATA_TOKEN` in `ricequant.env` (normally mode `600`). Never
  commit or copy the real token into documentation, YAML, logs, commands, or memory.
- `RqDataClient.initialize()` wraps a bare token in memory as
  `rqdata://license:<token>@rqdatad-pro.ricequant.com:16011`, assigns it to
  `RQDATAC_CONF`, and calls `rqdatac.init(use_zstd=True)`. Operators should not
  construct this URI themselves.
- `QuotaExceeded: login machine num exceeds` is a license login/machine concurrency
  limit, not the daily byte quota. Check for another active or stale RQData process or
  container before retrying; repeated retries do not solve that condition.

### Quota and resumability

- The account is constrained by a daily byte allowance (approximately 5 GiB in the
  current plan), not a Tushare-style request-frequency limit. Always trust the exact
  `bytes_limit` and `bytes_used` returned by `rqdatac.user.get_quota()` rather than
  the approximate plan description.
- Run `scripts/run_ricequant_jobs.sh quota` to inspect quota. It does not query
  ClickHouse or acquire the ingestion lock, so it can run while an ingestion job is
  active.
- Every source request in a dataset runner must go through the common `_fetch` path so
  quota checks, byte observations, progress logs, and failure context are retained.
- A quota pause is an expected resumable result and exits successfully. Re-run the
  same command on the next quota day; `ricequant_coverage_event` and per-day/per-stock
  cursors determine what remains. Do not infer progress from `max(date)` in a final
  table and do not manually mark partial work complete.

### Deployment and operator commands

- The normal deployment on this host is Docker plus crontab; Kubernetes is optional
  and is not required.
- The wrapper is `scripts/run_ricequant_jobs.sh`; it mounts `ricequant.yaml` read-only,
  injects `ricequant.env`, uses host networking, and writes
  `logs/ricequant-<mode>-YYYYMMDD.log`.
- Supported modes are `init-db`, `bootstrap`, `incremental`, `backfill`, `status`, and
  `quota`. A bounded historical request uses, for example,
  `backfill --dataset <name> --start YYYY-MM-DD --end YYYY-MM-DD`.
- Editing `ricequant.yaml` or `ricequant.env` does not require rebuilding the image,
  because both are supplied at container startup. Python code, dependencies, or files
  baked into the image do require a rebuild.
- RiceQuant uses its own package, container names, locks, state tables, and cron path;
  it may run in parallel with Tushare, while two RiceQuant ingestion runners are
  deliberately prevented from running concurrently.

### Stable ingestion decisions

- Source tables use the `ricequant_` prefix, ordinary ClickHouse `MergeTree`, validated
  staging data, and atomic partition replacement. There is no raw layer and correctness
  must not depend on background deduplication.
- Data from RiceQuant and Tushare must remain source-distinct. Do not add fallback,
  `coalesce`, field substitution, or automatic source precedence without an explicit
  request and a documented discrepancy analysis.
- Final-table writes use explicit business keys. Re-fetching the same authoritative
  range must replace that range without producing duplicate keys.
- `history_start_date` controls the index history that uses the common history setting;
  dataset-specific boundaries override it. Current important boundaries are:
  `index_weights_ex=2015-01-01`, stock daily bars `2015-01-01`, stock minute bars
  `2020-01-01`, and all four PIT financial groups `2015-01-01`.
- Stock daily and minute bars are requested with `adjust_type='none'`. Corporate-action
  and split factors are stored independently; adjustment belongs in later DWD/DWS work
  with an explicit baseline and PIT cutoff.
- Snapshot APIs without a source date must preserve `observation_date`/`observed_at` as
  the system observation time. Never present the download date as a source effective
  date or manufacture historical PIT knowledge.
- PIT financial data uses `get_pit_financials_ex(..., statements='all')` and four
  independent field groups/tables: income (94 fields), balance sheet (194), cash flow
  (74), and financial metrics (32 = main data 2 + TTM 23 + R&D 7). Preserve source
  `quarter`, `info_date`, `if_adjusted`, and version information; do not mix these rows
  with existing Tushare financial tables.

### Confirmed volatility-related APIs in rqdatac 3.8.1

- `get_specific_risk(order_book_ids, start_date, end_date, horizon, model,
  industry_mapping)` returns model-based stock-specific volatility for daily, monthly,
  or quarterly forecast horizons. The SDK documentation does not state the unit or
  annualization convention, so these must be empirically verified before ingestion.
- `get_style_factor_exposure(..., factors=['residual_volatility'])` returns a style
  factor exposure, not an ordinary realized-volatility series.
- `options.get_greeks(..., fields=['iv'])` returns BS-model option implied volatility;
  it is option-contract data and must not be labelled as the underlying stock's
  historical volatility.
- Historical/realized stock volatility should be explicitly calculated from a chosen
  daily or minute return series, with the return definition, adjustment choice, window,
  missing-value policy, and annualization factor recorded. Do not substitute any of the
  three interfaces above automatically.

### Option ingestion

- Options are isolated from `ricequant_instrument` in three tables:
  `ricequant_option_instrument`, `ricequant_option_contract_property`, and
  `ricequant_option_daily`. Their common history boundary is `2019-01-01`.
- Contract snapshots and daily bars cover all domestic ETF, index, and commodity
  options. `options.get_contract_property()` only supports exchange ETF options and is
  the authoritative historical source for adjusted strike prices and multipliers.
- Completed option backfill months are skipped on a repeated command; an unfinished
  month resumes from persistent daily stages and its last completed contract batch.
- Incremental option runs finish the saved interval before extending to newly
  available trading dates. A growing month must not reset quota-paused stages or
  introduce new-date contracts into the unfinished interval's cursor.
