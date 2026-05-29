# QDC 工作报告

报告日期：2026-05-28  
报告范围：Tushare Integration 项目的数据质量控制工作。当前代码中使用 `DQC` 命名，本报告沿用用户侧 `QDC` 表述，二者均指数据质量控制/校验体系。  
数据口径：代码与 schema 静态统计基于当前仓库；运行效果统计来自本地 ClickHouse 质量结果表，截止最新 DQC 运行完成时间 `2026-05-28 00:03:27`。

## 1. 工作概述

本阶段完成了从“发布前轻量校验”到“系统性 DQC 监控”的数据质量体系建设，覆盖 DWD 发布、DWS 发布和 DWS 因子面板的日常质量观测。核心目标是把数据质量问题前置到发布链路和日终批次中，减少空表发布、PIT 失效、版本重叠、行情/财务字段异常、因子矩阵计算异常等问题进入下游研究、回测和生产策略。

## 2. 已完成工作

### 2.1 建立通用 DQC 框架

- 实现 `DqcManager`，统一负责 DQC suite 解析、表范围解析、运行模式解析、规则执行、指标生成、结果入库和严格模式阻断。
- 设计并落地 5 张通用 DQC 结果表：
  - `dq_dqc_run`
  - `dq_dqc_result`
  - `dq_dqc_metric`
  - `dq_dqc_consistency`
  - `dq_dqc_sample`
- 结果表维度包含 `layer`、`domain`、`suite_name`、`table_name`，可复用于后续 ADS、组合、风险、信号、回测等 DQC suite。
- 支持 `strict`、`warn_only`、`skip` 三种运行模式；当前默认使用 `warn_only` 建立基线和稳定规则。

### 2.2 落地 DWS 因子面板 DQC suite

已上线 `dws.stock_factor_panel` suite，覆盖 2 张核心 DWS 表：

| 表名 | 定位 |
| --- | --- |
| `dws_stock_factor_wide` | 因子宽表，承载基础行情、财务、筹码、融资融券等字段 |
| `dws_stock_factor_wide_matrix` | 因子矩阵表，承载面向模型/研究使用的因子列 |

该 suite 覆盖以下质量维度：

| 维度 | 已完成能力 |
| --- | --- |
| 完整性 | 目标交易日非空、关键字段和血缘字段非空、矩阵 `factor_count` 与配置一致 |
| 新鲜度 | DWS 最新交易日必须追平交易日历中最近开市日 |
| PIT 安全 | `available_trade_date >= trade_date`，避免未来数据提前可见 |
| 语义规则 | OHLC 一致性、非负数值、比例边界、NaN/Inf 检查、因子错误 JSON 检查 |
| 统计画像 | 按表和数值列输出 row count、非空率、空值率、零值率、均值、标准差、分位数等指标 |
| 漂移监控 | 基于历史 `dq_dqc_metric` 做滚动基线对比，基线不足时以 `MONITOR` 形式记录 |
| 跨表一致性 | 宽表与矩阵表的主键集合、行数比例、证券数量比例一致性检查 |
| 审计样本 | 固定 hash 抽样，记录缺失 key、spot check 和因子交叉验证样本 |
| 因子业务交叉验证 | 用独立 Python reference evaluator 重新计算抽样因子，与矩阵表实际值比较 |

### 2.3 建立发布前质量闸口

除系统性 DQC 外，已实现 DWD/DWS 发布前质量校验，用于在临时表替换生产表前发现阻断级风险。

| 层级 | 覆盖范围 | 规则能力 |
| --- | ---: | --- |
| ODS | 138 个 schema 文件 | 每表 3 条通用规则，覆盖非空、必需元数据列、采集元数据非空 |
| DWD | 22 张 DWD 表 | 每表基础 PIT/血缘/版本规则，并按业务域扩展行情、财务、融资融券、北向、筹码、指数权重、证券主数据规则 |
| DWS | 2 张 DWS 表 | 因子宽表和矩阵表发布规则，覆盖唯一键、必需字段、OHLC、PIT 可见性、factor_count |

当前 DWD/DWS 发布校验静态规则实例为 219 条；若计入 ODS 通用规则实例，总静态规则实例为 633 条。这里的“规则实例”指“某张表上应用一条规则”的计数，同一规则 ID 在多张表上应用会分别计数。

### 2.4 提供 CLI 和日常运行入口

- 增加 `python main.py quality dqc` 命令，用于执行系统性 DQC。
- 增加 `python main.py quality run/list/report` 命令，用于发布校验规则查询、执行和结果查看。
- 日常脚本已接入 DQC 执行入口，可通过 `scripts/run_daily_market_jobs.sh` 在日终任务中触发 DWS 全量 DQC。
- CLI 支持单表、全 suite、全层运行，并输出 JSON 汇总，便于接入调度日志和后续告警。

### 2.5 建立测试和文档

- 已形成 `docs/dqc_design.md` 和 `docs/quality_rules_report_zh.md`，说明 DQC 架构、结果表、规则范围和执行方式。
- 质量相关测试覆盖 CLI 参数解析、suite 解析、结果入库、issue rate 计算、DWD/DWS 规则 SQL、DQC 语义 SQL、因子业务交叉验证等关键路径。
- 本次核验运行 `python -m unittest tests.test_quality_validation tests.test_quality_cli`，共执行 43 个测试用例，结果通过。

## 3. 关键量化指标

### 3.1 静态覆盖指标

| 指标 | 数值 | 说明 |
| --- | ---: | --- |
| DQC suite 数 | 1 | `dws.stock_factor_panel` |
| DQC 覆盖 DWS 表 | 2 | 宽表和矩阵表 |
| 最新完整 DQC 运行规则数 | 24 | `dq_dqc_result` 中最新全量运行产生的规则结果数 |
| 因子映射数 | 448 | 来自 `docs/prd/factor_mapping_readable.csv` |
| 已支持独立交叉验证的因子数 | 446 | 可由 reference evaluator 解析和重算 |
| 暂未支持独立交叉验证的因子数 | 2 | 以 `MONITOR` 覆盖率结果记录 |
| DWS 宽表数值列 | 63 | 用于统计画像和 NaN/Inf 检查 |
| DWS 矩阵表数值列 | 448 | 与因子映射数量一致 |
| DWD/DWS 发布校验规则实例 | 219 | 22 张 DWD 表 + 2 张 DWS 表 |
| ODS 通用校验规则实例 | 414 | 138 个 schema * 3 条规则 |
| ODS+DWD+DWS 总规则实例 | 633 | 静态可应用规则实例总数 |

### 3.2 最新 DQC 运行效果

最新 DQC 运行信息：

| 字段 | 值 |
| --- | --- |
| run_id | `a33e8e8d43004dadb6290f52733fde13` |
| suite | `stock_factor_panel` |
| table scope | `all` |
| as_of_date | `2026-05-27` |
| mode | `warn_only` |
| status | `FAIL` |
| finished_at | `2026-05-28 00:03:27` |

最新运行的结果汇总：

| 指标 | 数值 | 说明 |
| --- | ---: | --- |
| 应用规则数 | 24 | 本次生成 24 条 DQC 规则结果 |
| 聚合检查量 | 28,001,552 | 各规则 `checked_count` 求和，不代表去重物理行数 |
| 发现问题数 | 5 | 各规则 `issue_count` 求和 |
| 失败规则数 | 1 | `status = FAIL` |
| 通过规则数 | 21 | `status = PASS` |
| 监控规则数 | 2 | `status = MONITOR` |
| 生成监控指标 | 6,579 | 写入 `dq_dqc_metric` |
| 生成审计样本 | 100 | 写入 `dq_dqc_sample` |
| 生成一致性记录 | 2 | 写入 `dq_dqc_consistency` |

最新运行发现的问题：

| 表 | 规则 | 严重级别 | 检查量 | 问题数 | 问题率 |
| --- | --- | --- | ---: | ---: | ---: |
| `dws_stock_factor_wide` | `dqc_wide_winner_rate_bounds` | `WARN` | 5,506 | 5 | 0.0908% |

结论：最新一次 DQC 没有发现 `BLOCKER` 级别问题；发现 1 条 `WARN` 级规则失败，问题集中在 `winner_rate` 超出 `[0, 100]` 边界。

### 3.3 DQC 累计运行效果

截至最新运行完成时间，DQC 结果表累计记录：

| 指标 | 数值 |
| --- | ---: |
| DQC 运行次数 | 18 |
| DQC 规则结果数 | 344 |
| DQC 累计问题数 | 34,428 |
| DQC 失败规则结果数 | 46 |
| DQC 监控指标数 | 80,882 |
| DQC 审计样本数 | 1,320 |
| DQC 一致性记录数 | 28 |

累计失败按严重级别拆分：

| 严重级别 | 状态 | 规则结果数 | 问题数 |
| --- | --- | ---: | ---: |
| `BLOCKER` | `FAIL` | 22 | 1,158 |
| `WARN` | `FAIL` | 24 | 33,270 |
| `MONITOR` | `MONITOR` | 29 | 0 |

累计问题排名靠前的 DQC 规则：

| 规则 | 严重级别 | 失败次数 | 累计问题数 | 说明 |
| --- | --- | ---: | ---: | --- |
| `dqc_matrix_factor_errors_empty` | `WARN` | 6 | 33,024 | 矩阵表因子计算错误 JSON 非空 |
| `dqc_wide_nonnegative_quant_fields` | `BLOCKER` | 8 | 1,144 | 宽表非负数值字段出现负值 |
| `dqc_wide_winner_rate_bounds` | `WARN` | 14 | 242 | `winner_rate` 超出 `[0, 100]` |
| `dqc_row_count_nonzero` | `BLOCKER` | 4 | 4 | 目标交易日无数据 |
| `dqc_latest_trade_date_fresh` | `BLOCKER` | 4 | 4 | DWS 最新交易日未追平交易日历 |
| `dqc_dws_factor_row_ratio` | `BLOCKER` | 2 | 2 | 宽表与矩阵表行数比例不一致 |
| `dqc_dws_factor_instrument_ratio` | `BLOCKER` | 2 | 2 | 宽表与矩阵表证券数量比例不一致 |

### 3.4 发布校验累计效果

发布校验结果表累计记录：

| 指标 | 数值 |
| --- | ---: |
| 发布校验运行次数 | 280 |
| 发布校验规则结果数 | 2,650 |
| 发布校验累计问题数 | 4,517,411 |
| 发布校验失败规则结果数 | 301 |

按层级拆分：

| 层级 | 运行次数 | 规则结果数 | 问题数 | 失败规则结果数 |
| --- | ---: | ---: | ---: | ---: |
| DWD | 251 | 2,505 | 4,517,333 | 281 |
| DWS | 29 | 145 | 78 | 20 |

累计问题排名靠前的发布校验规则：

| 规则 | 严重级别 | 失败次数 | 累计问题数 | 主要风险 |
| --- | --- | ---: | ---: | --- |
| `margin_nonnegative_fields` | `BLOCKER` | 24 | 1,929,855 | 融资融券余额/流量字段为负 |
| `dwd_single_open_version` | `BLOCKER` | 10 | 1,526,523 | 同一业务键存在多个开放 PIT 版本 |
| `quote_metrics_ohlc_consistency` | `BLOCKER` | 7 | 812,266 | 行情衍生 OHLC 字段不一致 |
| `chip_winner_rate_bounds` | `BLOCKER` | 24 | 182,104 | 筹码胜率超出有效区间 |
| `daily_basic_share_hierarchy` | `BLOCKER` | 24 | 17,797 | 股本层级关系异常 |
| `market_ohlc_consistency` | `BLOCKER` | 50 | 16,291 | 行情 OHLC 字段不一致 |
| `quote_metrics_average_price_range` | `WARN` | 24 | 12,536 | 均价超出日内 low-high 区间 |
| `dwd_sys_window_order` | `BLOCKER` | 35 | 10,433 | PIT 版本窗口 `sys_from >= sys_to` |

## 4. 实际效果评估

### 4.1 从事后发现转为批次内发现

质量规则已经嵌入发布和日终 DQC 流程，问题会在批次执行时记录到结果表，而不是等下游研究或策略使用时才暴露。最新 DQC 运行在 `warn_only` 模式下发现 5 条 `winner_rate` 边界问题，说明规则已能对具体字段、具体交易日形成可量化反馈。

### 4.2 增强 PIT 与回测可信度

DWD 发布校验覆盖 PIT 日期、版本窗口、开放版本唯一性、血缘字段完整性；DWS DQC 继续检查 `available_trade_date` 与 `trade_date` 的关系。这减少了未来函数、版本穿越和源数据不可追溯对回测结果的影响。

### 4.3 提高因子矩阵可审计性

DQC 不仅检查矩阵是否有数据，还会检查 factor_count、矩阵血缘、错误 JSON、宽表与矩阵主键一致性，并用独立 reference evaluator 对抽样因子做业务公式重算。最新完整运行生成 100 条审计样本和 6,579 条监控指标，为定位单只证券、单个交易日、单个因子的异常提供了入口。

### 4.4 建立了可持续监控基线

DQC 已累计沉淀 80,882 条监控指标，可用于后续漂移检测、阈值调优和质量趋势看板。当前漂移规则在基线不足时记录 `MONITOR`，可以避免规则刚上线时误阻断生产批次。

### 4.5 具备生产阻断能力，但当前仍处于观测模式

框架支持 `strict` 模式下对 `BLOCKER` 失败进行阻断；当前 DQC 和发布校验运行以 `warn_only` 为主，因此问题会被记录但不会自动阻断发布。该策略适合规则上线初期建立基线，但对于已稳定的核心表，建议逐步切换到 `strict`。

## 5. 后续建议

1. 优先治理累计问题量最大的规则：
   - `dqc_matrix_factor_errors_empty`
   - `dqc_wide_nonnegative_quant_fields`
   - `margin_nonnegative_fields`
   - `dwd_single_open_version`
   - `quote_metrics_ohlc_consistency`
2. 对最新 DQC 发现的 5 条 `winner_rate` 边界问题做样本追踪，判断是源字段异常、DWD 转换异常还是 DWS 聚合/映射异常。
3. 在连续多日无 `BLOCKER` 失败后，将核心表逐步从 `warn_only` 切换到 `strict`：
   - 第一批：`dws_stock_factor_wide`、`dws_stock_factor_wide_matrix`
   - 第二批：行情、交易日历、证券主数据、DWD PIT 关键表
4. 将 DQC 结果表接入调度告警和质量看板，建议至少展示运行状态、失败规则、问题数、问题率、最新交易日、漂移指标和样本链接。
5. 扩展 ADS 层 suite，复用现有通用结果表，覆盖组合、风险、信号和回测输出。

## 6. 结论

本阶段 QDC/DQC 工作已经形成可运行、可记录、可审计、可扩展的数据质量体系。静态能力上，系统已覆盖 633 个表级规则实例，其中 DWD/DWS 发布链路 219 个规则实例；系统性 DQC 已覆盖 DWS 因子面板 2 张核心表、448 个因子和 511 个数值列。运行效果上，DQC 已累计执行 18 次、生成 344 条规则结果、发现 34,428 个规则问题并沉淀 80,882 条监控指标；最新完整运行应用 24 条规则，检查量聚合值为 28,001,552，发现 5 个 WARN 级问题且无 BLOCKER 级失败。

整体看，QDC 已经从规则实现进入可运营阶段。下一阶段重点应从“覆盖能力建设”转向“高频问题治理、严格模式分批启用、质量看板和告警闭环”。
