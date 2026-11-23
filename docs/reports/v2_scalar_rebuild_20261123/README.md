# 可用日 2026-11-23 v2 重建

已按用户确认的**可用日**完成全市场单日重建：`available_trade_date=2026-11-23`，对应 `trade_date=2026-11-20`。使用已采集的 Tushare 真实数据，没有使用米筐或跨源填充。

候选实体表：

```text
v2_scalar_rebuild_20261123.dws_stock_factor_wide_v2_available_20261123
```

结果为 **5,572 行、5,572 只股票、1,968 列**，含 356 只北交所股票。全部行的交易日和可用日正确，键无重复，与当日源行情、正式 v2 的键集合完全一致，缺行和多行均为 0。所有写入均在隔离库；正式表未交换或替换，验收后正式 v2 仍为 1,741 列、目标日 5,572 行。

**验收通过。**与正式 v2 对比 1,736 个原有非审计列，共 9,672,992 个单元格，精确空值安全比较零差异。排除的五列为 `source`、`source_table`、`source_batch_id`、`source_record_hash`、`build_time`；每批比较 128 列。新增字段无 NaN/Inf，股本代理、标志取值及 forward PE 正盈利约束检查通过。

新增 227 列中，214 列有实现，13 列为明确占位且全部 NULL。210 个已实现列在目标日有真实非空值；另外四列 `fa_avail_for_sale_mrq_0`、`fa_avail_for_sale_mrq_4`、`htm_invest_mrq_0`、`htm_invest_mrq_4` 当日全空，它们在此前历史样本中已有非空验证。没有把当日空值补为零或用其他字段替代。逐列统计见 [available_new_coverage.json](available_new_coverage.json)。

财务 PIT 规则保持不变：按可用日选取可见版本，使用既有固定自然季度 MRQ/年度 LYR；TTM 要求四个季度报告存在，求和型字段仍按非空单季均值乘四；递延所得税先合并两项可空累计源值，再作单季差分。季度历史未按目标日截断。

独立 Python 从 DWD 重新选报告并重算 12 项字段，覆盖 122 只股票、1,464 次比较，全部通过。样本包含沪深、科创板、创业板、北交所以及目标日全部 4 个非空递延所得税 TTM 样本（`001232.SZ`、`001248.SZ`、`002360.SZ`、`301707.SZ`）。递延税值精确相同；研发费用 TTM 最大绝对浮点差为 5.96e-8 元，在 `rel_tol=1e-12, abs_tol=1e-8` 内，其余非空比较精确一致。脚本与结果见 [independent_pit_check.py](independent_pit_check.py)、[available_independent_pit.json](available_independent_pit.json)。原有列比较不使用该浮点容差。

当日补充源覆盖如下。相比 11 月 20 日试建，基准指数、涨跌停和龙虎榜源已更新到目标交易日，相关字段因此新增非空值。

| 字段 | 目标日非空行数 | 说明 |
|---|---:|---|
| `bench_ret` | 5,572 | `000985.CSI` 当日收益率，比例值 -0.027074 |
| `up_limit` / `down_limit` | 各 5,572 | 与目标股票日匹配 |
| `top_list_flag` | 61 | 命中为 1，其余保留 NULL |
| `sw_l1_code` | 5,560 | 其余 12 行保留 NULL |
| `csi800_member` | 800 | 正权重成员为 1，其余保留 NULL |
| `list_date` | 5,572 | 全部有值 |

龙虎榜可见源共 73 行、62 个代码，其中 `111024.SH` 不在当天股票行情面板，因此面板实际命中 61 只；未新增无行情行或自动改码。全市场龙虎榜标志与可见源核对零差异，见 [available_toplist_check.json](available_toplist_check.json)。

**源数据限制：**构建期间融资融券 DWD 最新交易日为 2026-11-19，目标日没有可见记录，相关字段按现有规则保留 NULL，未沿用前一天数值。复权因子虽已有 11 月 23 日记录，本次仅关联交易日 11 月 20 日。源覆盖快照见 [available_source_snapshot.json](available_source_snapshot.json)。

上游候选实体已在本次重建前刷新并验收：

| 表 | 行数 | 验收 |
|---|---:|---|
| `dwd_stock_holder_number_rebuilt` | 434,890 | 精确下一 SSE 开市日，异常 0 |
| `dwd_stock_top_list_rebuilt` | 241,293 | 精确下一 SSE 开市日，异常 0 |
| `dws_stock_income_quarter_rebuilt` | 728,895 | 旧业务字段零差异、键集合相同、无重复 |
| `dws_stock_cashflow_quarter_rebuilt` | 601,018 | 旧业务字段零差异、键集合相同、无重复 |

股东户数原始数据 479,254 行，其中 3,894 行公告日早于报告期，沿用既有规则排除。其余数量差异还涉及起始日期边界和去重，不能全部归因于公告日异常。

构建于 2026-11-23 11:54:59（Asia/Shanghai）完成。ClickHouse 25.8.22.28 查询日志记载耗时 **699.45 秒**、峰值内存 **34.93 GiB**，写入 5,572 行，异常码 0。成功查询 ID：`d7fd92a8-14e9-412a-898e-528c6c9fca23`。客户端记录耗时 697.68 秒，与服务端日志分别保存在 `runs.jsonl` 和 [build_query_log.json](build_query_log.json)。

使用 4 线程、64 GiB 查询内存上限、2 GiB 外部排序与聚合阈值、20 分钟执行上限，并沿用单插入线程和 64 KiB 压缩块设置。仅裁剪等值关联的日频源至交易日 11 月 20 日，价格同时限制可用日 11 月 23 日；保留完整财报、研报、北向和指数成分快照历史。源视图读取运行时数据，未冻结为跨查询事务快照；后续源更新后重跑需重新审阅差异。

构建脚本：`/tmp/v2_nov23_available.py`（复用 `/tmp/v2_nov23_rebuild.py`）；生成 SQL：`/tmp/v2_nov23_available.sql`，SHA256 和完整参数见 [available_build.json](available_build.json)。这些构建脚本拒绝向已非空的候选表重复插入。

可从仓库根目录重跑只读验收（更新本地结果 JSON）：

```bash
PYTHONPATH=. python docs/reports/v2_scalar_rebuild_20261123/validate_available.py
PYTHONPATH=. python docs/reports/v2_scalar_rebuild_20261123/independent_pit_check.py
```

本次是数据重建，没有新增生产代码修改；未重复运行已通过的实现回归测试。汇总见 [available_validation_summary.json](available_validation_summary.json)，字段定义与占位限制见 [扩展说明](../../v2_scalar_extensions_rebuild.md)，之前的历史试建证据见 [11 月 20 日报告](../v2_scalar_rebuild_20261120.md)。
