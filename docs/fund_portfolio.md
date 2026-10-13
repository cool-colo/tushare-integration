# Public-fund stock holdings

The source is Tushare [`fund_portfolio`, doc_id=121](https://tushare.pro/document/2?doc_id=121), updated quarterly. The spider is `fund/portfolio/fund_portfolio`. It creates the ODS latest table `fund_portfolio` and append-only history `fund_portfolio_raw`; DWD sync publishes `dwd_fund_portfolio` from that raw history.

Run from the repository root with your normal `config.yaml`:

```shell
python main.py run job fund/portfolio --update-type full
python main.py run spider stock/basic/trade_cal
python main.py dwd sync dwd_fund_portfolio --validation-mode strict
```

`jobs.yaml` and `scripts/run_daily_market_jobs.sh` include the full holdings refresh and subsequent DWD sync. The job generator also registers this job. The spider requests each completed quarter from `default_min_cal_date` (default `2010-01-01`) through today, including quarter ends on weekends. It deliberately revisits old periods: one existing holding does not establish disclosure completeness, and later announcements or corrections can change historical reports. This is a full refresh of returned rows, not a deletion or replacement of raw history.

Requests use `period`, `offset`, and `limit=8000`; subsequent offsets advance by the number of returned rows until an empty response. Live checks for `20231231` returned 5,000 rows with `limit=5000` and 8,000 with `limit=10000`; offset 1,071,000 still returned 1,000 rows and offset 5,000,000 returned no rows. Annual portfolios can therefore require many pages. The public documentation does not state the row cap or describe pagination parameters. Short pages do not prove completion. Rows from another report period fail the run. Tushare documents 200 requests/minute at 5000 points and 500 at 8000; this spider caps Scrapy requests at that endpoint allowance with the configured safety ratio and respects any slower user limit.

Live checks of `20260630` with `limit=1000` found identical pages at offsets 17,000 and 19,000 (only eight distinct rows among 1,000 returned rows), followed by additional rows at offset 20,000. An identical page does **not** prove that the endpoint ignored offset. Repeated pages therefore produce warnings and continue; the spider fails after 10,000 nonempty pages for one period if no terminal empty page arrives, and leaves that period incomplete. All received rows, including source duplicates, remain in raw history, and offsets always advance by received row count. Page warnings also expose duplicate business keys with different payloads: for `20260630`, the first 8,000-row page contained ten distinct payloads for eight keys. ODS latest uses the existing pipeline's last returned row per key; this is response order, not evidence of source revision order. Raw/DWD observations cannot resolve which source payload is authoritative without additional source information.

Each page is immediately yielded to the normal storage pipeline. Follow-up pages use Scrapy requests, so download timeouts, retries, and interruption remain responsive. Memory holds the active pages and small page hashes rather than all rows for a quarter. Progress logs show period, offset, page row count, and total received rows; `Completed fund_portfolio period=...` appears after the terminal empty page. An ODS row or an existing quarter is not a completeness marker: if a run fails, earlier pages remain stored and the job reports failure. Finish ingestion successfully before manually syncing DWD; the daily runner already skips DWD after an ingestion failure. Restarting refreshes the configured quarters and upserts their source business keys while appending raw observations.

At startup the spider logs `streaming pagination: page_limit=8000` and the loaded code path. Requests still showing `limit=1000`, combined with a traceback whose response has `offset=0` but whose exception reports a much larger offset, identify the earlier synchronous quarter-buffering code. Code changes take effect only after restarting that process (or rebuilding and restarting its image when using Docker).

To retry the initial backfill without re-fetching earlier completed quarters, set the existing `DEFAULT_MIN_CAL_DATE` environment override for that invocation. For example, if all periods through `20230630` completed and later periods did not:

```shell
DEFAULT_MIN_CAL_DATE=2023-07-01 python main.py run job fund/portfolio --update-type full
```

Stop the previous process first; running processes do not load code edits. This override narrows that invocation only. Later regular full refreshes should retain the normal configured start date so old source corrections can still be observed.

The business key is `(ts_code, ann_date, end_date, symbol)`. `ts_code` identifies the fund and `symbol` the held stock. Different funds and announcements are preserved separately. DWD uses `stock:<symbol>` for `instrument_id`, retains the fund code, and adds `fund:<ts_code>` as `fund_id`; the fund is not treated as a stock. No fund-list dependency is required for period queries.

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

Quality checks cover both identities, valid quarter ends, report dates no later than announcements, strict next-day visibility, nonnegative finite known measures, lineage, and nonoverlapping version windows per complete business key. Use strict validation to block publication on findings; the project's configured default remains `warn_only`.

For a stock-centric analysis, group by `symbol` while retaining fund and disclosure identity. Fund holdings, shareholder tables, and northbound holdings describe different populations and dates; their similarly named quantities and ratios are not interchangeable and are not merged by this change.
