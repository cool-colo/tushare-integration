# Public-fund stock holdings

The source is Tushare [`fund_portfolio`, doc_id=121](https://tushare.pro/document/2?doc_id=121), updated quarterly. The spider is `fund/portfolio/fund_portfolio`. It creates the ODS latest table `fund_portfolio` and append-only history `fund_portfolio_raw`; DWD sync publishes `dwd_fund_portfolio` from that raw history.

Run from the repository root with your normal `config.yaml`:

```shell
python main.py run job fund/portfolio --update-type full
python main.py run spider stock/basic/trade_cal
python main.py dwd sync dwd_fund_portfolio --validation-mode strict
```

`jobs.yaml` registers the job. `scripts/run_daily_market_jobs.sh` schedules the full holdings refresh and subsequent DWD sync only when `UPDATE_TYPE=full`; weekday incremental batches skip both because per-fund ingestion is a long-running task. Tushare began enforcing `ts_code` on `fund_portfolio` requests on 2026-11-05 even though its parameter description still said that `period` alone was accepted. The spider therefore obtains the fund universe from Tushare `fund_basic` and requests each source fund's holdings history. It does not substitute ETF tables or codes inferred from existing holdings, either of which can omit funds.

Fund discovery explicitly requests both `E` (exchange-traded) and `O` (off-exchange) markets. `fund_basic` documents a 15,000-row single-request maximum, so each market is paginated with `limit=15000` and increasing offsets until an explicit empty page. A short page is not treated as completion because the server can impose a lower effective cap. A repeated discovery page, blank code, empty market, or page safety limit fails the run instead of silently accepting a truncated universe. Codes repeated by the source are logged and scheduled only once. Holdings requests begin only after both markets complete, so a discovery failure cannot start a partial-universe ingestion.

Each `fund_portfolio` request includes one `ts_code`, `offset`, and `limit=8000`; subsequent offsets advance by the number of source rows until an empty response. Short pages do not prove completion. A row for another fund, an invalid report date, or a future report date fails the run. The API call returns the fund's history, so the spider locally retains only rows whose `end_date` is on or after `default_min_cal_date` (default `2010-01-01`). This preserves the configured history boundary without treating another data source as a fallback. Tushare documents 200 requests/minute at 5000 points and 500 at 8000; the spider applies that endpoint allowance with the configured safety ratio and respects any slower user limit.

Although Tushare describes the endpoint as quarterly updated, the source also returns legitimate first-period snapshots whose `end_date` is not a calendar quarter end. Observed examples include `159146.SZ` (`end_date=20260113`, `ann_date=20260115`) and `159849.SZ` (`end_date=20210223`, `ann_date=20210225`), both near fund inception. These rows are retained as distinct source observations. Date validation requires a real report date no later than its announcement; it does not rewrite or discard the source date.

Identical holdings pages at different offsets produce warnings and continue because equality alone does not prove that later offsets contain no new rows. The spider fails after 10,000 nonempty pages for one fund if no terminal empty page arrives. All eligible received rows, including source duplicates, remain in raw history. Page warnings expose duplicate business keys with different payloads. ODS latest uses the existing pipeline's last returned row per key; this is response order, not evidence of source revision order. Raw/DWD observations cannot resolve which source payload is authoritative without additional source information.

Each eligible page is immediately yielded to the normal storage pipeline. Follow-up pages use Scrapy requests, so download timeouts, retries, and interruption remain responsive. Memory holds active pages, discovered codes, and small page hashes rather than all holdings. Progress logs separately show source and stored row counts per fund; `Completed fund_portfolio ts_code=...` appears after its terminal empty page. Existing rows are not a completeness marker: if a run fails, earlier pages remain stored and the job reports failure. Finish fund discovery and holdings ingestion successfully before syncing DWD; the daily runner already skips DWD after an ingestion failure.

At startup the spider logs `per-fund streaming pagination`, page limits, and the loaded code path. Requests without `ts_code` identify an old image. Code changes take effect only after restarting that process, or rebuilding and restarting its image when using Docker.

`DEFAULT_MIN_CAL_DATE` can narrow which returned rows are stored for a one-off backfill. It no longer avoids requesting older source history because Tushare requires the per-fund query shape. For example, to store only reports after `20230630`:

```shell
DEFAULT_MIN_CAL_DATE=2023-07-01 python main.py run job fund/portfolio --update-type full
```

Stop the previous process first; running processes do not load code edits. This override narrows stored rows for that invocation only. Later regular full refreshes should retain the normal configured start date so old source corrections can still be observed.

The business key is `(ts_code, ann_date, end_date, symbol)`. `ts_code` identifies the fund and `symbol` the held stock. Different funds and announcements are preserved separately. DWD uses `stock:<symbol>` for `instrument_id`, retains the fund code, and adds `fund:<ts_code>` as `fund_id`; the fund is not treated as a stock. `fund_basic` is used only as the Tushare code-universe request and is not substituted for holdings data.

| Source field | Stored meaning |
| --- | --- |
| `end_date` | Holdings report period; DWD `event_date` |
| `ann_date` | Disclosure date; determines business availability |
| `mkv` | Stock holding market value in yuan |
| `amount` | Stock holding quantity in shares; Float64 preserves the source float type |
| `stk_mkv_ratio` | Ratio to stock market value, kept in source scale |
| `stk_float_ratio` | Ratio to floating stock capital, kept in source scale |

All four measures use the source float type (Float64 in ClickHouse), with no rounding, integer conversion, unit conversion, or ratio rescaling. DWD SQL uses the repository's ClickHouse conventions. The official sample uses percentage-like values such as `4.37`, but the page does not explicitly label the ratio unit; no fraction conversion or 100-based validation is imposed. Missing measures remain NULL in latest ODS, raw ODS, and DWD. Schema-declared nullable columns now retain NULL through the shared ingestion pipelines; nonnullable columns retain existing default handling.

DWD `available_trade_date` is the first SSE trading day **strictly after** `ann_date`, following the repository's conservative daily visibility convention. An explicit SQL guard fails sync if that calendar date is missing, so the incomplete temporary table is not published. This guard is necessary because ClickHouse can otherwise substitute a default when inserting NULL into a required date. There is no substitution with the report date or ingestion date. Complete the SSE calendar through at least the next open day after the newest announcement before syncing.

DWD retains system version windows and source table, batch, and record hash. Backfilled rows do not reconstruct versions that were never observed: for a system-time replay, apply `sys_from <= as_of_timestamp AND as_of_timestamp < sys_to` as well as `available_trade_date <= as_of_trade_date`. An `end_date` filter alone exposes information before disclosure. Tushare may disclose partial quarter portfolios and fuller semiannual/annual portfolios on different announcement dates; this table does not claim each disclosure is a complete portfolio or automatically combine them.

Quality checks cover both identities, valid report dates no later than announcements, strict next-day visibility, nonnegative finite known measures, lineage, and nonoverlapping version windows per complete business key. Use strict validation to block publication on findings; the project's configured default remains `warn_only`.

For a stock-centric analysis, group by `symbol` while retaining fund and disclosure identity. Fund holdings, shareholder tables, and northbound holdings describe different populations and dates; their similarly named quantities and ratios are not interchangeable and are not merged by this change.
