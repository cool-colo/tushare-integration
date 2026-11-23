# V2 数组相关明细：DWD 字段、PIT 与任务

本轮按原需求中的 5 组数组、6 张 Tushare 明细表落实 DWD 加工。数组不加入 v2 宽表；本轮不使用米筐，不激活此前占位的基金汇总或国家队指标。真实数据结果见 [加工报告](reports/v2_array_dwd_20261123/README.md)。

| 数组字段 | 原始输入 | DWD 表 | 日期与限制 |
|---|---|---|---|
| `research_records` | `report_rc_raw` | `dwd_stock_research_report` | 研报日期与源更新时间中较晚日期的下一 SSE 交易日 |
| `fund_holding_records` | `fund_portfolio_raw` | `dwd_fund_portfolio` | 公告日的下一 SSE 交易日；完整持仓标记未知 |
| `ccass_holding_records` | `ccass_hold_detail_raw` | `dwd_stock_ccass_holding_detail` | 缺历史披露日：保留明细，历史可用日 NULL，不可进入公开日期 PIT |
| `main_business_records` | `fina_mainbz_raw` | `dwd_stock_main_business` | 缺公告日：保留明细，历史可用日 NULL，不按报告期末回填 |
| `top_holder_records` | `top10_holders_raw` | `dwd_stock_top10_holders` | 公告日的下一 SSE 交易日；总股东口径 |
| `top_holder_records` | `top10_floatholders_raw` | `dwd_stock_top10_floatholders` | 公告日的下一 SSE 交易日；流通股东口径 |

所有表都保留源业务列及公共字段：`instrument_id`、`instrument_type`、`exchange`、`source_code`、`event_date`、`available_trade_date`、`sys_from`、`sys_to`、`source`、`source_table`、`source_batch_id`、`source_record_hash`。下游记录 ID 使用 `source_record_hash`，不另造跨源统一 ID。

两类十大股东即使出现相同哈希，也不代表口径相同。合并展示时应保留 `source_kind`，不能跨来源仅按哈希丢弃一方。

| 数组内字段 | DWD 字段与单位 |
|---|---|
| 研报日期、预测报告期、机构、作者、目标价、EPS、预测利润、PE、ROE | `report_date`、`forecast_period_end`、`org_name`、`author_name`、`min_price`、`max_price`、`eps`、`np`、`pe`、`roe`；全部保留源尺度，特别是 `np` 为万元，不在 DWD 改为元 |
| 基金 ID、基金代码、报告期、完整性、数量、市值、比例 | `fund_id`、`ts_code`、`end_date`、`is_complete_holdings`、`amount`、`mkv`、`stk_mkv_ratio`；股票键为 `symbol`，数量保持股、市值保持元，比例保持源尺度；完整性一律 NULL，不能用季末/半年末推断为 1 |
| CCASS 持仓日、参与者 ID/名称、数量、比例 | `trade_date`、`col_participant_id`、`col_participant_name`、`shareholding`、`shareholding_percent`；数量去除规范千分位后转 Float64，单位为股；百分数除以 100 成为 0～1；原字符串 `col_shareholding`、`col_shareholding_percent` 同时保留 |
| 主营业务报告期、分类、项目、收入、币种 | `end_date`、`bz_code`、`bz_item`、`bz_sales`、`curr_type`；同时保留 `bz_profit`、`bz_cost`、`update_flag`，不跨币种求和或换算；分类原码保留，不将清单外类型自动改成 P/D/I |
| 股东报告期、来源口径、名称、性质、数量及比例 | `end_date`、`source_kind`、`holder_name`、`holder_type`、`hold_amount`、`hold_ratio`、`hold_float_ratio`；同时保留 `hold_change`，比例保持源百分数尺度；两张表的 `source_kind` 分别为 `top10_holders` 与 `top10_floatholders`，同主体跨表不自动合并或优先取值 |

业务键决定一条记录的版本链，不能使用过粗的 ODS latest 表键覆盖同一公告内的多个主体：

| DWD 表 | 版本业务键 |
|---|---|
| 研报 | `ts_code, report_date, org_name, report_title, author_name, quarter, report_type, classify, create_time`；延续现有研报身份，允许既有可空身份项 |
| 基金持仓 | `ts_code, ann_date, end_date, symbol` |
| CCASS 持仓 | `ts_code, trade_date, col_participant_id` |
| 主营业务 | `ts_code, end_date, bz_code, bz_item, curr_type`；币种允许 NULL，`update_flag` 为版本内容，不是新主体 |
| 两类十大股东 | 各自使用 `ts_code, end_date, ann_date, holder_name` |

相同业务键连续重复采集的相同哈希只保留首次观察；数值发生变化或 A→B→A 时保留变化链，不按哈希全局去重。`sys_from` 来自该版本首次保留的 `_ingest_time`，`sys_to` 为下一观察版本的开始，形成左闭右开的系统观察窗口。公开日期可用性与系统观察时间分别保留，不能用持仓日/报告期替代公告日，也不能将“当前最新版本”称作历史系统 PIT。

有明确披露日期的记录严格使用下一 SSE 开市日；重复日历行先按日期折叠，缺失下一交易日则失败，不退回公告当日。十大股东排除公告日早于报告期、无效日期或主体身份缺失的输入。基金和研报延续既有日期与空值口径。未采集过的历史修订无法通过重建补造。

CCASS 和主营业务的 `availability_mode=unknown_disclosure`：`available_trade_date` 为 `Nullable(Date32)`，且必须为 NULL，`availability_basis='unknown_disclosure_date'`。质量检查会拒绝给它们猜测一个日期；其它 DWD 表的日期要求保持不变。源中只有首次采集时间，这能证明系统观察时间，不能证明早年的公开披露时间。本轮按保守口径加工，尚未提供这两类历史公开日期 PIT 的可用数据。

六张表启用同一时刻版本冲突隔离。若同一业务键、同一 `_ingest_time` 有不同哈希，源无法提供先后依据；整个业务键的已观察历史从正常候选移入对应的 `<DWD表名>_quarantine`，不按哈希、数值大小或采集批次选胜者。隔离明细保留源业务值、哈希、批次和 `sys_from`，`available_trade_date`、`sys_to` 均为 NULL，并标记 `quarantine_reason='ambiguous_same_time_versions'`。这是当前重建的保守质量隔离范围，不能据此推断冲突之前的原始披露也不存在。正常结果与隔离明细必须一并审阅覆盖率。

有日期依据的正常表在系统观察截点 `known_at` 下查询时，要同时限定：

```sql
WHERE available_trade_date <= as_of_trade_date
  AND sys_from <= known_at
  AND known_at < sys_to
```

业务日、公开可用日、系统观察截点应由下游明确提供。首次历史回填之前没有系统观察证据；不能声称恢复了那时从未保存过的修订版本。缺公开可用日的表和所有 quarantine 表不进入上述 PIT 结果。

六项均接入 `scripts/run_daily_market_jobs.sh` 的 DWD 阶段；基金持仓沿用现有 full-only 调度。`python main.py dwd sync all` 通过 schema 自动发现全部 DWD 主任务，六张配套隔离表随各自主任务生成，不作为独立数据源任务再采集。其它已有 DWD 任务不因本轮被重新定义，v2/DWS 本轮不重建。

单表正式同步入口如下。该入口会先构建临时表、执行质量检查，然后发布正常表和配套隔离表；本次真实数据工作仅在隔离候选库执行，未调用这些命令替换正式表：

```bash
python main.py dwd sync dwd_stock_research_report
python main.py dwd sync dwd_fund_portfolio
python main.py dwd sync dwd_stock_ccass_holding_detail
python main.py dwd sync dwd_stock_main_business
python main.py dwd sync dwd_stock_top10_holders
python main.py dwd sync dwd_stock_top10_floatholders
```

基金 RAW 数据量较大。正式同步先材料化一次所需源列，按 `cityHash64(ts_code) % 16` 分片；每个基金及其股票持仓的完整版本历史均在同片，不能按时间切片后独立去重。正常和隔离输出读取同一份材料化输入，血缘 `source_table` 仍为 `fund_portfolio_raw`。成功发布后清理该临时源；失败时保留用于诊断。其它表按现有原始版本全量加工。ClickHouse 同步设置 4 线程、64 GiB 上限、2 GiB 外部排序/聚合阈值和较小读写块。

回归覆盖周末公告、重复日历、缺日历失败、重复采集、修订链、同刻冲突、主体及来源分离、基金分片、空值、单位转换和禁止伪造公开可用日。报告会分别列出正常记录、隔离记录和仍缺源证据的字段，不把 SQL 执行成功等同于所有数据都有历史 PIT 依据。
