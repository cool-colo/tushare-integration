# Tushare Schema Audit Report

Audit date: 2026-04-28

Scope: `stock`, `index`, `future`

Source of truth: official Tushare documentation at `https://tushare.pro/document/2`

## Summary

- Reviewed the live Tushare catalog under stock, index, and futures.
- Parsed 150 documentation pages under those sections.
- Found 139 API pages with explicit output-field definitions.
- Updated all existing repo schemas that were out of sync with the current docs.
- Re-ran the live audit after patching: existing covered APIs are now `OUTDATED = 0`.
- Found 38 official APIs that are still missing from this repo. They are listed below and were not implemented per request.

## Code Changes

- `tushare_integration/spiders/stock/basic.py`
- `stock_basic` spider now requests `SSE`, `SZSE`, `BSE`.
- `stock_basic` spider now requests list statuses `L`, `D`, `P`, `G`.
- `stock_company` spider now requests `SSE`, `SZSE`, `BSE`.

## Schema Changes

- `tushare_integration/schema/stock/basic/stock_basic.yaml`
- Updated `list_status` comment to include `G` (`过会未交易`).

- `tushare_integration/schema/stock/basic/stock_company.yaml`
- Removed obsolete field `ann_date`.
- Updated `exchange` comment from the old HKEX wording to `SSE/SZSE/BSE`.

- `tushare_integration/schema/stock/quotes/stk_weekly_monthly.yaml`
- Added missing field `end_date`.

- `tushare_integration/schema/stock/quotes/daily_basic.yaml`
- Removed obsolete field `limit_status`.

- `tushare_integration/schema/stock/financial/forecast.yaml`
- Removed obsolete fields `notice_times`, `update_flag`.

- `tushare_integration/schema/stock/financial/express.yaml`
- Removed obsolete field `update_flag`.

- `tushare_integration/schema/stock/financial/dividend.yaml`
- Removed obsolete field `update_flag`.
- Removed `update_flag` from the primary key.

- `tushare_integration/schema/stock/financial/fina_mainbz.yaml`
- Removed obsolete field `bz_code`.

- `tushare_integration/schema/stock/market/pledge_stat.yaml`
- Removed obsolete field `update_flag`.
- Removed `update_flag` from the primary key.

- `tushare_integration/schema/stock/market/pledge_detail.yaml`
- Removed obsolete fields `holder_type`, `desc`.

- `tushare_integration/schema/stock/market/repurchase.yaml`
- Removed obsolete fields `repo_goal`, `update_flag`.
- Removed `update_flag` from the primary key.

- `tushare_integration/schema/stock/market/stk_holdernumber.yaml`
- Removed obsolete duplicate field `holder_nums`.

- `tushare_integration/schema/stock/moneyflow/moneyflow.yaml`
- Removed obsolete field `trade_count`.

- `tushare_integration/schema/stock/moneyflow/moneyflow_ind_dc.yaml`
- Added missing field `content_type`.
- Added `content_type` to the primary key.

- `tushare_integration/schema/stock/moneyflow/moneyflow_mkt_dc.yaml`
- Fixed field name typo `ptc_change_sh` -> `pct_change_sh`.

- `tushare_integration/schema/stock/limit/limit_list_d.yaml`
- Removed obsolete field `swing`.

- `tushare_integration/schema/stock/special/limit_list_d.yaml`
- Removed obsolete field `swing`.

- `tushare_integration/schema/index/ths/ths_daily.yaml`
- Removed obsolete fields `pe_ttm`, `pb_mrq`.

- `tushare_integration/schema/index/ths/ths_member.yaml`
- Renamed `code` -> `con_code`.
- Renamed `name` -> `con_name`.
- Updated the primary key to use `con_code`.

- `tushare_integration/schema/stock/limit/dc_hot.yaml`
- Removed obsolete fields `hot`, `concept`.

- `tushare_integration/schema/stock/special/dc_hot.yaml`
- Removed obsolete fields `hot`, `concept`.

- `tushare_integration/schema/stock/limit/kpl_concept_cons.yaml`
- Renamed `cons_name` -> `con_name`.
- Renamed `cons_code` -> `con_code`.
- Updated the primary key to use `con_code`.

- `tushare_integration/schema/index/sw/sw_daily.yaml`
- Removed obsolete field `weight`.

## Missing APIs

### Stock

- `stock_st` (`ST股票列表`, doc_id=397)
- `st` (`ST风险警示板股票`, doc_id=423)
- `stock_hsgt` (`沪深港通股票列表`, doc_id=398)
- `bse_mapping` (`北交所新旧代码对照`, doc_id=375)
- `rt_k` (`实时日线`, doc_id=372)
- `rt_min` (`实时分钟`, doc_id=374)
- `rt_min_daily` (`A股实时分钟-日累计`, doc_id=457)
- `stk_week_month_adj` (`周/月线复权行情(每日更新)`, doc_id=365)
- `ggt_monthly` (`港股通每月成交统计`, doc_id=197)
- `stk_shock` (`个股异常波动`, doc_id=451)
- `stk_high_shock` (`个股严重异常波动`, doc_id=452)
- `stk_alert` (`交易所重点提示证券`, doc_id=453)
- `stk_account` (`股票开户数据（停）`, doc_id=164)
- `stk_account_old` (`股票开户数据（旧）`, doc_id=165)
- `stk_auction_o` (`股票开盘集合竞价数据`, doc_id=353)
- `stk_auction_c` (`股票收盘集合竞价数据`, doc_id=354)
- `stk_nineturn` (`神奇九转指标`, doc_id=364)
- `stk_ah_comparison` (`AH股比价`, doc_id=399)
- `moneyflow_cnt_ths` (`板块资金流向（THS)`, doc_id=371)
- `dc_index` (`东方财富概念板块`, doc_id=362)
- `dc_member` (`东方财富概念成分`, doc_id=363)
- `dc_daily` (`东财概念和行业指数行情`, doc_id=382)
- `stk_auction` (`开盘竞价成交（当日）`, doc_id=369)
- `tdx_index` (`通达信板块信息`, doc_id=376)
- `tdx_member` (`通达信板块成分`, doc_id=377)
- `tdx_daily` (`通达信板块行情`, doc_id=378)
- `dc_concept` (`题材数据（东方财富）`, doc_id=421)
- `dc_concept_cons` (`题材成分（东方财富）`, doc_id=422)

### Index

- `rt_idx_k` (`指数实时日线`, doc_id=403)
- `rt_idx_min` (`指数实时分钟`, doc_id=420)
- `idx_mins` (`指数历史分钟`, doc_id=419)
- `rt_sw_k` (`申万实时行情`, doc_id=417)
- `ci_index_member` (`中信行业成分`, doc_id=373)
- `idx_factor_pro` (`指数技术面因子(专业版)`, doc_id=358)

### Future

- `fut_weekly_monthly` (`期货周/月线行情(每日更新)`, doc_id=337)
- `ft_mins` (`历史分钟行情`, doc_id=313)
- `rt_fut_min` (`实时分钟行情`, doc_id=340)
- `ft_limit` (`期货合约涨跌停价格`, doc_id=368)

## Validation

- Re-ran the live doc comparison after patching: `OUTDATED = 0`.
- Parsed all schema YAML files successfully.
- Compiled the modified Python spider module successfully.

## Operational Note

- This repo now has the updated schema definitions, but the runtime table creation logic only does `CREATE TABLE IF NOT EXISTS`.
- If you already have old tables in MySQL, Doris, or ClickHouse, you still need a separate table migration or table rebuild for dropped/added/renamed columns to take effect in the database.
