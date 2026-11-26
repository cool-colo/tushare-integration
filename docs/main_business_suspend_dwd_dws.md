# 停复牌标准层与主营业务日期代理

`dwd_stock_suspend` 来自 `suspend_d_raw`，业务键为
`ts_code, trade_date, suspend_type`。同日停牌 S 和复牌 R 分别保留，
`suspend_timing` 原文及 NULL 不变。与现有 DWD 一致，只保留 2010 年起事件。
事件日期不是已证实的披露时间，因此 `available_trade_date` 始终为 NULL。
观察版本按 RAW 哈希和采集时间构建；同观察时刻的版本冲突进入隔离表。

`dwd_stock_main_business` 同样保留原始未知披露日期语义。
跨表日期推导位于 `dws_stock_main_business`，来源只包括主营业务 DWD、
`dwd_stock_income` 的普通合并利润表（`report_type='1'`）和 SSE 交易日历。
不使用利润表 ODS、RAW、单季 DWS，也不向其他财务来源兜底。

## 金额依据与选择

按 `ts_code, end_date` 查找所有保留的利润表观察版本。公告日必须有效且不早于
报告期，可用日必须等于 `greatest(ann_date, f_ann_date)` 之后的首个 SSE 交易日。
不沿用利润表中日期缺失时的推导值，也不将来源占位日期作为实际公告日。

人民币主营业务分类汇总行 P/产品、D/地区、I/行业只有在与明细的观察时刻、
批次、分类、币种、`update_flag` 一致且汇总金额唯一时才作为金额依据。
明细中同时存在总额、子项、层级合计、旧新名称，直接求和会重复计算。
因此不自动汇总分类明细，不使用单个产品收入代替整张利润表收入。
缺少这一汇总依据的行仍参与报告期关联。

比较 `bz_sales` 与 `revenue`、`bz_cost` 与 `oper_cost`，单位均为元。
至少一项主营汇总金额非 NULL；每个非 NULL 字段都要求候选对应金额非 NULL、
有限，且绝对误差不超过 0.01 元。NULL 不转换为零。
主营业务利润不等于营业利润，不参与匹配；`update_flag` 不是两表共同版本号。

1. 金额匹配：仅在金额吻合的候选中取最晚组合。
2. 金额无匹配或无可靠汇总：在同股票、报告期有效候选中取最晚组合。
3. 无有效报告期候选：三项日期均为 NULL。

组合排序为可用交易日、两个公告日较晚者、实际公告日、公告日依次降序。
同日期不同金额观察版本以稳定排序后的血缘 JSON 为最后排序项。
`ann_date, f_ann_date, available_trade_date` 整组取自被选候选，不分别拼接。
同金额日期组合的重复观察合并成一个候选，全部观察血缘仍保留。
候选计数统计金额及完整日期组合，不是不同日期数。

## 血缘与消费限制

每个主营业务 DWD 版本对应一行 DWS，原始金额、分类、币种、观察窗口保持不变。
`sys_from/sys_to` 表示主营业务的观察窗口，不表示两表联合版本窗口。
`date_match_method` 区分 `amount_match`、`report_period_latest`、`no_valid_report`；
`date_match_fields`、误差、候选数、匹配用金额与所选利润表金额可用于复核。

`income_source_records` 为所选金额日期组合的全部观察血缘，JSON 元组依次为
`[记录哈希, 批次, sys_from, sys_to, update_flag, source, source_table]`。
`main_business_summary_records` 元组依次为
`[记录哈希, 批次, sys_from, sys_to, bz_item]`。
`main_business_*` 备份原始 DWD 血缘和可用日字段，DWS 记录哈希覆盖原始哈希、
汇总依据、所选利润表依据和选择方式。

关联代理不能证明主营业务明细或修订值当时已经公开。
因此 `is_public_date_pit_eligible` 固定为 0；不自动接入公开日期 PIT 因子宽表。
质量校验检查逐行数据保留、真实来源组合、汇总依据、金额证明、候选优先级与最晚选择。
当前两表使用 `warn_only`：校验结果和问题继续记录，BLOCKER 失败也不阻止发布。
可在 `config.yaml` 的 `quality.table_modes` 中分别设置两表；命令行模式显式覆盖配置。

## 构建

```bash
python main.py dwd sync dwd_stock_suspend --validation-mode warn_only
python main.py dws sync dws_stock_main_business --validation-mode warn_only
```

主营业务 DWS 依赖 `dwd_stock_main_business`、`dwd_stock_income`、`trade_cal` 已构建。
本次发布统计及验证结果见 `docs/reports/main_business_suspend_20261126/`。
