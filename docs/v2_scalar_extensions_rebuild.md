# V2 标量扩展：口径、重建及验收

初始在现有工作区补齐 227 个 Tushare 标量列；2026-11-25 又增加四个只建列的高频占位和两个利息费用 MRQ，当前扩展 233 列，其中 216 列具备计算路径、17 列明确为 NULL 占位。不读取米筐，不提供 5 个明细数组。初始隔离库真实数据试建见 [试建报告](reports/v2_scalar_rebuild_20261120.md)。

后续新增需求已单独落实 5 组数组的 DWD 明细、PIT 约束与任务，见 [数组 DWD 说明](v2_array_dwd_pit.md)；v2 标量列数与本文原范围保持不变。

完整逐项映射见 [字段血缘](v2_scalar_extensions_lineage.md)。机器可读目录为 `tushare_integration/schema/dws/v2_scalar_extensions.json`，包括原文、最终字段名、期间、状态、单位和限制。V2 1741 列现增加至 1974 列；财务期间列从 1595 增加至 1784。

## 口径

- 财务可用时点、报告版本选择、累计转单季和旧累计报告修订向下一季传播均复用当前实现。MRQ/LYR 固定到计算时点的自然季度/年度，不以最新已披露记录重新编号。TTM 要求四份自然季度报告存在；金额字段为非空季度均值乘四。这两项优先于候选文档的不同描述。
- 单季写入明确指定目标列名，防止扩列时 schema 顺序与计算字段顺序不同造成错位。递延所得税先把两项可空累计值相加，再差分和聚合，不能分别估算两个 TTM 后相加。
- 时间 `t` 取日行情的 `available_trade_date`，与现有 T+1 面板一致。龙虎榜属于 `trade_date` 当天的盘后事件，只在下一交易日可用。交易日滚动窗口使用日历天 `(t-N日,t]`，十二个月窗口使用 `(t-12个月,t]`。
- 研报年度预测只用 12 月 31 日预测期。先按时点选择每篇可见版本，再按机构与绝对年度取最新记录；最新版本字段为空时不退回旧值。最新排序为报告日期、可用日、源更新时间、稳定哈希。目标价按文档单独选各机构最新有效区间中点。
- FY0 来自最新可见定期财报年度，年报已披露时使用同期实际净利润。active 年度为上一自然年（其年报尚未披露）或当年（其年报已披露）；分歧度固定取当年。预测净利润按万元转元，但源 `np` 并未独立证明归母含义。
- 近似净资产使用最新可见归母净资产、逐绝对年度机构均值及逐日权重，留存率采用最新可见年报及其前两年。三份年报必须齐全；利润分母仅累计正净利润。缺预测、分红输入或非正分母时留空。
- 利润表 `rd_exp` 和财务指标 `rd_exp` 保持独立，后者不宣称等于 2018 年前附注研发投入。`fix_assets_total` 只解释为固定资产合计。期末总股本代理稀释加权股本，不能据此认定真实稀释股份已披露。
- 北向持股按最新可见业务日期及版本取值，旧日期修订不覆盖更新日期；其停更后持有最后披露值，不表示当前实际持仓。申万行业按现有业务有效区间取值，有冲突则 NULL。上市日期仅在源版本无冲突、日期有效且已上市时提供。
- 中证 800 取全指数最新可见快照，避免个股落选后继续保留旧入选状态。最新快照中明确正权重为 1；没有覆盖完整性证据时不输出 0。龙虎榜、研报覆盖计数和分红也不把无输入当作零；正样本计算只代表已采集可见记录，不保证上游采集完整。
- 分红仅接收具有有效实施公告日的实施记录，按股票、分送年度、除息日选可见最新版本，现金分红使用税前每股金额乘实施基准股本（万股）乘 10000。缺实施公告日的记录不能用于重建历史可用性。
- `share_action_factor`、两项基金汇总、八项国家队指标、公司省市为 13 个 NULL 占位列，不依赖米筐、基金或前十股东表。后续补齐依赖需要单独变更，不能自动激活或从其他来源填充。
- 保留现有历史边界：交易面板和单季 DWS 从 2010 年开始；直接读取的资产负债表和年报仍可使用源中已有的更早报告，不额外采集回补。财务 PIT 仍具有现有源版本观察范围的限制，不声明重建从未采集过的历史修订版本。

## 利息费用 TTM 补充核验（2026-11-23）

`fin_exp_int_exp_ttm_0`、`fin_exp_int_exp_ttm_4` 已存在于代码目录和正式
`default.dws_stock_factor_wide_v2`，本次不重复扩列，补充字段注释和专项数值回归。
血缘为 `default.dwd_stock_income.fin_exp_int_exp` → `dws_stock_income_quarter` → v2，单位为元。

- 利润表按自己的公告/修订可用日选择 PIT 可见的累计合并版本（`report_type` 为 1/4）。
  Q1 直接使用累计值，Q2–Q4 减同年紧邻上一季的可见累计值；缺前季或缺字段值时单季为空，不能跨季度相减。
- `_ttm_0` 使用固定季度槽 0–3，`_ttm_4` 使用槽 4–7，即上年同季截止的滚动四季值。
  `_4` 不代表第四条已披露记录，也不是仅一个上年单季值。报告期缺失时 TTM 为空；
  四份报告存在而部分字段为空时，保留 v2 既有的非空季度均值乘四规则。
- 利息费用和现金流表的折旧各自使用本表的可用日，不要求公告日期相等，也不等待另一张表披露。
  旧累计值修订从自身修订可用日起影响本季及下一季差分，不能改写更早时点；
  不用 `int_exp` 等其他字段补齐 `fin_exp_int_exp`。

只读核验：正式表可用日 `2026-11-23` 共 5,572 行，两列非空数分别为 5,071 和 5,234；
此前同日候选表覆盖数相同。独立 Python 从真实 DWD 重算 55 只股票的 110 个利息 TTM 值，
与正式 v2 的数值及 NULL 状态全部一致，见 [核验记录](reports/v2_interest_ttm_20261123.json)。
同样本的 110 个折旧 TTM 均为空，与独立计算一致；真实抽样不构成折旧非空值的验证，
独立公告日、非空折旧、未来修订和缺期边界由专项 ClickHouse SQL 数值测试覆盖。
新增两项数值测试和九项 v2 回归全部通过；Ruff 与 `git diff --check` 通过。本次未写入数据库。

## 高频占位与利息 MRQ 补充（2026-11-25）

2026-11-25 六列补充：`hf_std_5m`、`hf_5m_return_count`、`hf_5m_return_sum`、`hf_5m_return_sum_sq` 仅建可空列，V2 同步输出 NULL，未实现分钟收益计算，也不增加米筐依赖。计数列为 Nullable(Int64)，其余三列为 Nullable(Float64)；对数收益及其标准差／平方和为无量纲。

`fin_exp_int_exp_mrq_0`、`fin_exp_int_exp_mrq_4` 复用现有 `dwd_stock_income.fin_exp_int_exp` → `dws_stock_income_quarter` 单季链路，单位为元。Q1 直接使用累计值，Q2–Q4 减同年紧邻上一季可见累计值；按 income 自身披露时点选版本。`_0` 是固定自然季度槽0，`_4` 是其前四个季度（上年同季），未披露／缺期／缺值不跳期、不补旧值，不用另一字段 `int_exp` 替代。无需扩建 quarter 表，该表已含源字段。数据库加列是元数据变更，已有历史行不回算；两个 MRQ 字段在后续 V2 重建时计算。

已对 `default.dws_stock_factor_wide_v2` 执行六列 `ADD COLUMN`，字段顺序与代码 schema 一致；原表 UUID 和 14,628,482 行均保持，六列当前均为 NULL。见 [DDL](../scripts/sql/add_v2_hf_interest_mrq_20261125.sql) 和 [数据库验收记录](../logs/v2-six-column-alter-20261125.json)。没有回算历史、交换表或删除表。

本次 24 项结构／同步测试和 2 项数值测试通过，包括完整 1974 列写入、Q1／Q2 单季值、上年同季槽、缺前季／缺当前季、晚到修订传播、最新 NULL、未来版本隔离和四个高频列保持 NULL。Ruff、diff 检查通过，见 [测试记录](../logs/v2-six-fields-tests-20261125.txt)。

## 重建顺序

以下步骤是发布时的操作说明；真实数据试建在隔离库执行，尚未交换正式表。先验证源表和 SSE 交易日历（包含最新公告后的下一开市日）。新增 DWD 缺少日历映射时直接失败，不退回公告当日。

1. 同步 `dwd_stock_holder_number`、`dwd_stock_top_list`。现有日常任务已将这两项加入 DWD 阶段。
2. 确认 v2 所需的指数日线、涨跌停、主数据、行业、指数权重、财报、研报、分红和北向持股 DWD 均存在并完成更新。只占位的来源不列为必需依赖。
3. 先在候选表构建 `dws_stock_income_quarter`、`dws_stock_cashflow_quarter` 并验收，再构建 v2 候选表。扩展季度字段前不能直接运行新 v2 查询。
4. 保留旧表用于比较；检查候选表唯一性、字段、类型、单位、空值分布、财报时点边界和旧列一致性，再执行原子 `EXCHANGE TABLES`。交换不受支持时停止发布，不删除旧表来模拟交换。

可用 `python main.py dwd sql <表名>`、`python main.py dws sql <表名>` 查看生成 SQL。候选表应通过 `render_sync_sql(table_name, target_table_name=候选表名)` 生成写入语句，schema 通过相应 manager 构建；避免手工只加列却不重算历史。

验收使用 `tushare_integration/sql/validate_v2_scalar_extensions.sql`（候选表默认命名为 `dws_stock_factor_wide_v2_candidate`）。动态的旧列逐列对比由 `scripts/validate_v2_scalar_extensions.py` 生成只读 SQL：

```bash
python scripts/validate_v2_scalar_extensions.py --old-table dws_stock_factor_wide_v2 --new-table dws_stock_factor_wide_v2_candidate > /tmp/v2_scalar_acceptance.sql
```

旧值验收按每批 128 列生成查询，避免同时读取 1,736 列的缓冲叠加。ClickHouse 25.8 的验收表达式使用空值状态比较和非空值比较，不在 JOIN ON 之外调用 `isNotDistinctFrom`。1968 列宽表的历史写入使用 `max_insert_threads=1, max_compress_block_size=65536`，降低多分区并发写入时的列压缩缓冲开销。

v2 构建查询不额外设置 `max_threads`，计算线程数沿用 ClickHouse 服务端配置；本地读取、写入分别使用
`max_local_read_bandwidth=104857600`、`max_local_write_bandwidth=104857600`（各 100 MiB/s）。
这两项写在单条全市场 `INSERT SELECT ... SETTINGS` 中；候选试建与正常同步使用同一 SQL。
不额外设置线程数或内存上限。带宽限制覆盖查询本地读写，不限制后台合并、校验或实例总 IOPS。

ClickHouse 的 V2 同步恢复为全市场、全历史单条 SQL，使用唯一候选表名。
默认 `warn_only` 校验后原子发布，显式 `strict` 会阻断失败校验，拒绝跳过校验。
`EXCHANGE TABLES` 后旧正式数据保留在该次候选表名下；无正式表时使用 `RENAME TABLE`。
构建、校验或交换失败均保留表，交换失败不使用删表降级。源清单变化时保留候选并停止发布；
物理清单包含后台合并造成的变化，因此该判定保守，需核对变更再发布。

血缘哈希、来源列表、批次与构建时间会随新增输入变化，不作旧列数值一致性比较。旧列有任何差异都须定位，不允许用跨源填充掩盖。全历史构建应另外记录耗时、峰值内存及各来源覆盖情况；本地样例不代表生产规模性能验收。

## V2 单条 SQL 与提前过滤（2026-11-25）

正常同步：`python main.py dws sync dws_stock_factor_wide_v2`。
隔离试建不发布、不运行发布后 DQC 或通知：

```bash
python scripts/build_v2_single.py --report-path logs/v2-single-full.json
python scripts/build_v2_single.py --instrument stock:000001.SZ --validation-mode strict
python scripts/build_v2_single.py --refresh-report logs/v2-single-full.json
```

未指定候选名时自动生成唯一名称；已有名称、正式表、固定 `_tmp` 和旧阶段表名一律拒绝写入。
阶段构建、资格报告及重启阶段任务接口已移除，旧阶段表和历史报告仍保留。
SQL、源清单、校验、行数、磁盘和查询日志指标写入报告；查询日志异步落盘后可刷新。
候选表实际执行一条完整 `INSERT SELECT`，没有中间物理阶段表。
完整 V2 HTTP 请求单独使用 12 小时接收超时，其它查询仍使用现有客户端设置。
每日调度需重建实际使用的 Docker 镜像，容器 logs 挂载保留运行报告。

新增字段的过滤边界：

- 研报覆盖和目标价：交易日生成最多 4 个月份键，股票＋报告月份等值 JOIN 后使用精确 `(t-90日,t]`。
- 年度预测：先形成股票／机构／预测年度的可见状态，再按必要年度 ASOF 匹配。
  年份取 FY0–FY3、CY/CY+1、正权重净资产投影年度及 active 年度；长期预测无统一年龄过期条件。
  active 利润、EPS 和分歧度继续使用各自 180、90、91 日窗口与机构门槛。
- 分红：股票＋除息年度等值 JOIN 限制到近 12 月涉及的年度及留存率所需的 3 个年度。
  再检查精确日期和时点，选择版本后才过滤实施状态／金额，保留 NULL 与无效输入的业务含义。
- 财报新增分支：源侧选择同可用日版本，运行最大报告期确定最新业务期，再按报告期 ASOF。
  利润表保留最新期、必要的 3 个年报和上自然年年报存在性；净资产只用最新期。
  半年折旧只读取 6/12 月及当年 6 月基数；原 MRQ／TTM／LYR 字段仍读取完整季度链路。
- 中证 800：全指数最新快照状态 ASOF，个股试建也不缩小指数来源。

提前过滤只改变计算规模及实际依赖血缘，不改变字段来源、单位、财报窗口和空值语义。
目标价选中记录纳入血缘，零权重净资产预测不纳入血缘。保留的最新 NULL 不回填旧值。
预计中间行缩减见 [过滤测算](reports/v2_early_filter_estimates_20261125.md)，
实际性能、资源约束与本次验收证据见 [单条 SQL 验收报告](reports/v2_single_early_filter_20261125.md)，
不能以测算比例替代全市场执行结果。

## 测试

`python -m unittest tests.test_stock_factor_wide_v2 tests.test_v2_sync tests.test_v2_single_build tests.test_v2_scalar_extensions tests.test_tushare_response tests.test_daily_market_jobs_script tests.test_quality_validation`

数值测试在独立 `clickhouse-local` 进程内使用 Memory 表，不读取配置数据库。覆盖未知全空、固定取期、TTM 部分字段缺失、LYR10、累计修订传播、递延税缺项、年度预测与实际值切换、未来修订隔离、机构门槛、估值近似、半年度折旧、分红单位、股东户数、行业换期、指数换样和北向旧期修订。

2026-11-20 的验证结果：126 项相关回归测试与 7 项新增测试全部通过。ClickHouse Local 26.3.9.8 在与项目一致的 `max_query_size=2097152`、`max_ast_elements=500000` 及默认 `max_expanded_ast_elements=500000` 下完成了完整宽表写入，并核对非空财务值与股本代理的目标列。新增测试整组耗时约 139 秒；当时的真实数据试建和资源测量见 [试建报告](reports/v2_scalar_rebuild_20261120.md)。2026-11-25 的提前过滤、全市场构建及最终回归记录见上面的单条 SQL 验收报告。
