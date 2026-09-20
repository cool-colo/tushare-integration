# 三大财务报表 PIT、确定性 JOIN 与单季重算改造计划

状态：核心改造已实现（原生单季对账与生产重建待执行）  
日期：2026-09-20

## 1. 目标

本计划修复利润表、资产负债表、现金流量表进入 `dws_stock_factor_wide` 时的三类问题：

1. 财报修订版本当前按 `ann_date` 而不是 `f_ann_date` 生效，可能把未来修订回填到历史。
2. 直接财报 JOIN 没有限制 `report_type`，并用 `sys_from`、哈希兜底选行，可能随机选中单季表、母公司表或调整前表。
3. 旧报告期修订后，单季值和 TTM 必须从修订可用日开始重算，但不得改写修订可用日前的历史值，也不得覆盖更新的报告期。

本次明确采用以下业务决策：

- `income`、`balance_sheet`、`cashflow` 的普通直接 JOIN 仅允许 `report_type = '1'`。
- 报告期 `event_date` 决定“哪一期更新、哪一期最新”；披露时间决定“该版本什么时候可见”。
- 同一报告期内部选择截至交易日已可见的最新修订；不同报告期之间始终优先最近报告期。
- `update_flag` 不作为版本生效时间，只在业务日期完全相同时作为确定性兜底排序字段。
- 修订只从基于 `f_ann_date` 得出的 `available_trade_date` 开始影响因子。

## 2. 当前实现审计结论

### 2.1 DWD 可用日错误

三大报表当前都使用：

```sql
calendar_date_expr: src.ann_date
available_trade_date_expr: coalesce(calendar_map.next_trade_date, src.ann_date, src.end_date)
```

`f_ann_date` 没有参与计算。相同 `ann_date`、不同 `f_ann_date` 的原始版和修订版因此得到同一个 `available_trade_date`。

实际样例 `000928.SZ / 2026-03-31`：

| 版本 | ann_date | f_ann_date | 当前 available_trade_date |
|---|---|---|---|
| 原始版 | 2026-04-28 | 2026-04-28 | 2026-04-29 |
| 修订版 | 2026-04-28 | 2026-05-09 | 2026-04-29（错误） |

修订版正确的最早可用交易日应为 2026-05-11。

### 2.2 普通直接 JOIN 会选中错误报表类型

`dws_stock_factor_wide` 的 `income`、`balance_sheet`、`cashflow` CTE 当前没有 `report_type` 过滤，排序为：

```sql
PARTITION BY instrument_id, available_trade_date
ORDER BY event_date DESC, sys_from DESC, source_record_hash DESC
```

这不是业务优先级。`sys_from` 容易受接口抓取顺序影响，哈希倒序更没有业务语义。

当前库中，按现有 `income` 规则产生的 304,146 个候选节点里，有 240,730 个节点最终选中 `report_type IN ('6', ..., '12')`，占 79.15%。这些是母公司或其他非普通合并口径。

实际样例：`000004.SZ / 2024-12-31 / available_trade_date=2026-04-29` 当前直接收入候选第一名为 `report_type=9`（母公司调整表）。

受影响的直接字段包括 `revenue`、`total_revenue`、`n_income`、`n_income_attr_p`、`total_profit`、`oper_cost`、`admin_exp`、`sell_exp` 等。

### 2.3 只按最近 available_trade_date 做 ASOF 会发生报告期倒退

如果旧报告期在新报告期披露后才修订：

```text
2025Q3 已披露
2025Q2 随后发布修订
```

当前直接 ASOF JOIN 会把 Q2 修订当成最新财报，因为它的可用日期更晚，造成宽表从 Q3 倒退到 Q2。

正确顺序必须是：

1. 对每个报告期选择交易日当时已可见的最新版本。
2. 普通直接字段再从这些报告期中选择最大的 `event_date`。

### 2.4 单季链路的 report_type 审计

各链路当前和目标口径如下：

| 链路 | 当前 report_type | 说明 | 本计划处理 |
|---|---|---|---|
| 三大报表普通直接 JOIN | 未过滤 | 会混入 2–12 | 改为仅 `1` |
| income/cashflow 累计差分单季表 | `1,4` | 用累计合并表及调整累计表做相邻季度差分 | 暂时保留，修复时间轴和重算 |
| Tushare 原生单季对照 | `2,3` | 单季合并、调整单季合并 | 作为对账基准和后续切源候选 |
| balance sheet 季度/MRQ | `1,4` | 资产负债表是时点值，不做单季差分 | 保留，但版本选择按 PIT 修复 |
| fina_indicator quarter | 无 report_type | 源表没有该字段 | 单独处理 `update_flag` 确定性排序 |

`(1,3)` 不是有效组合：`1` 是累计合并口径，`3` 是调整单季口径。可比较的组合是累计 `(1,4)` 或原生单季 `(2,3)`。

#### 普通 JOIN 为什么只用 type=1，而不是 `(1,4)`

type=4 是公司在本期报表中重新列示的上年同期调整合并数据，通常属于更早的 `end_date`，不是本期最新合并报表。实测 234,453 组 type=4 披露中：

- 228,331 组在同一 `f_ann_date` 存在报告期更新的 type=1；
- 315 组与 type=1 报告期相同；
- 没有一组在同一 `f_ann_date` 完全缺少 type=1。

若普通 JOIN 同时允许 `(1,4)` 并按当前方式竞争，已有 8,072 个可用日节点会由 type=4 胜出。因此：

- 普通 LF/直接字段只允许 type=1；
- type=4 不丢弃，只在按报告期组织的 LYR、TTM、历史比较值和累计差分修订层中使用；
- type=4 的较晚披露日期不能让旧报告期抢占最新报告期。

当前 `income/cashflow quarter` 使用 `(1,4)` 是因为实现采用累计差分：

```text
Q1 = Q1 累计值
Q2..Q4 = 当期累计值 - 上季度累计值
```

代码中的 `quarter_report_types=(2,3)` 在 income/cashflow 配置里不会实际参与这条路径，因为 quarter 特征已切到 `dws_stock_income_quarter` 和 `dws_stock_cashflow_quarter`；该配置容易误导，应删除或明确标成仅供原生单季对账。

### 2.5 当前累计差分与原生单季并非完全一致

以相同证券、报告期、可用日对账，当前累计差分结果与原生 `(2,3)` 的匹配情况为：

| 表/字段 | 配对行数 | 匹配率 |
|---|---:|---:|
| income.revenue | 444,648 | 97.10% |
| income.n_income_attr_p | 444,648 | 96.65% |
| income.total_profit | 444,648 | 96.91% |
| cashflow.n_cashflow_act | 433,415 | 97.02% |
| cashflow.n_cashflow_inv_act | 433,415 | 96.87% |
| cashflow.n_cash_flows_fnc_act | 433,415 | 95.25% |

因此当前实现不能直接宣称完全正确，也不能未经分类就切换到 `(2,3)`。差异需要区分：修订口径、缺失上一季度、精度/舍入、字段非可加、Tushare 原生单季本身缺失等原因。

## 3. 目标 PIT 语义

### 3.1 公告业务日期和可用交易日

三大报表定义：

```sql
publication_date = greatest(
    coalesce(nullIf(ann_date, toDate32('1970-01-01')), end_date),
    coalesce(
        nullIf(f_ann_date, toDate32('1970-01-01')),
        nullIf(ann_date, toDate32('1970-01-01')),
        end_date
    )
)

available_trade_date = publication_date 之后的第一个 SSE 交易日
```

继续沿用当前“严格下一交易日”约定。`sys_from` 只表达系统第一次采集到版本的时间，不替代市场披露时间。

### 3.2 两级选行规则

给定交易日 `T`：

```text
第一层：每个 (instrument_id, event_date) 内，
        选择 available_trade_date <= T 的最新可见版本。

第二层：普通直接字段从第一层结果中，
        选择 event_date 最大的报告期。
```

同一报告期内部的确定性排序：

```sql
ORDER BY
    available_trade_date DESC,
    f_ann_date DESC,
    update_flag DESC,
    sys_from DESC,
    source_record_hash DESC
```

普通直接 JOIN 在进入上述排序前必须过滤：

```sql
report_type = '1'
```

旧报告期即使后来修订，也只能更新自己的历史槽位，不能取代已经披露的更新报告期。

### 3.3 LYR、MRQ、TTM 的优先级

- `MRQ/LF`：从交易日当时可见的所有报告期中取最大 `event_date`。
- `LYR_0`：取最大年度报告期的最新可见版本；旧年度修订只能更新 `LYR_1` 等对应偏移。
- `TTM`：先对最近四个报告期分别选交易日当时的最新版本，再聚合。
- 修订报告期已退出最近四期窗口时，不影响当前 TTM。
- 修订生效日前的 TTM 必须保持原值。

## 4. 实施步骤

### 阶段 A：修复三大报表 DWD 可用日

修改：

- `tushare_integration/schema/dwd/dwd_stock_income.yaml`
- `tushare_integration/schema/dwd/dwd_stock_cashflow.yaml`
- `tushare_integration/schema/dwd/dwd_stock_balance_sheet.yaml`

工作项：

1. 将日历映射输入由 `ann_date` 改为 §3.1 的 `publication_date`。
2. `available_trade_date_expr` 使用同一个表达式作为日历缺失时的回退，避免计算口径分裂。
3. 保留源字段 `ann_date`、`f_ann_date`，便于审计。
4. 对 `1970-01-01` 和 NULL 增加质量规则。
5. 增加单元测试，覆盖工作日、周末、节假日、修订晚于原公告、缺失 `f_ann_date`。

### 阶段 B：把普通直接 JOIN 改成 type=1 的财报状态流

修改 `tushare_integration/dws.py` 中：

- `income` CTE
- `balance_sheet` CTE
- `cashflow` CTE

工作项：

1. 三个 CTE 统一增加 `src.report_type = '1'`。
2. 不再只按 `(instrument_id, available_trade_date)` 对当天到达的记录选一条。
3. 生成财报状态变更日期集合；在每个状态日期上，查看所有 `available_trade_date <= 状态日期` 的 type=1 记录。
4. 按 §3.2 先选最新报告期，再选该报告期最新修订。
5. 状态流与日行情继续使用 ASOF JOIN，但右表每个证券、状态日期必须唯一。
6. 明确使用 `f_ann_date`、`update_flag` 作为确定性排序，不允许仅靠抓取顺序或哈希决定业务赢家。
7. 为三个直接 CTE 抽取共用 SQL renderer，防止规则再次漂移。

### 阶段 C：修复 income/cashflow 单季时间轴和修订传播

当前 `dws_stock_income_quarter`、`dws_stock_cashflow_quarter` 只在某个累计报告自身出现时计算该季度。旧累计报告随后修订时，依赖它的下一季度不会自动重算。

目标构建方式：

1. 生成所有财务版本的 `available_trade_date` 状态轴。
2. 在每个状态日期，对每个累计报告期选择当时可见的最新 `(1,4)` 版本。
3. 对每个报告期重新计算：

   ```text
   Q1 = Cumulative(Q1)
   Qn = Cumulative(Qn) - Cumulative(Qn-1), n=2..4
   ```

4. 当累计 `Qk` 被修订时，从修订可用日开始至少重算 `Qk` 和 `Q(k+1)`；不得修改修订日前的季度版本。
5. 为季度表保留或新增清晰血缘：当前累计记录哈希、上一季度累计记录哈希、两者各自的实际公告日和 report_type。
6. `dws_stock_factor_wide` 的季度/TTM 特征在每个状态日按报告期选择最新季度版本，再按报告期倒序取最近四期。

阶段 C 暂时保留累计 `(1,4)` 路径，不改成 `(1,3)`。同时建立原生 `(2,3)` 对账视图或诊断 SQL，完成阶段 D 的决策门禁。

### 阶段 D：决定是否切换为原生单季 `(2,3)`

对 §2.5 的不一致样本按季度、report_type、字段和缺失模式分类：

1. 检查原生 type=2/3 覆盖率和字段完整率。
2. 检查累计差分是否因缺少上一季度而为空。
3. 检查调整单季 type=3 是否与调整累计 type=4 的差分一致。
4. 检查 EPS、比率和其他非严格可加字段是否应禁止差分。
5. 对金额字段采用绝对误差和相对误差双阈值，区分舍入与实质差异。

决策条件：

- 若原生 `(2,3)` 覆盖和一致性更好，则以 `3 > 2` 为优先级建立 canonical quarter，累计 `(1,4)` 仅作缺失回退。
- 若累计差分更稳定，则继续以 `(1,4)` 为生产口径，原生 `(2,3)` 作为 DQC 对账来源。
- 无论选择哪条路径，都必须遵循 `f_ann_date` 生效时间和按报告期选版本的规则。

### 阶段 E：核查 balance sheet 与 fina_indicator quarter

1. Balance sheet 是时点值，不做累计差分；季度/MRQ 只需按报告期和版本做 PIT 选择。
2. Balance sheet 普通直接 JOIN 按用户要求仅使用 type=1；历史调整 type=4 只允许更新其对应历史报告期的派生槽位。
3. `fina_indicator` 没有 `report_type`、`f_ann_date`，不能套用三大报表规则。
4. `dws_stock_financial_indicator_quarter` 在同报告期、同公告日存在 `update_flag=0/1` 时，显式按 `update_flag DESC, sys_from DESC, source_record_hash DESC` 选择，避免哈希随机决定。
5. 对 `fina_indicator` 的修订只能声明 `ann_date` 业务可见性和 `sys_from` 系统可见性，不能伪造精确官方修订日期。

### 阶段 F：重建和发布顺序

按临时表构建、校验、交换的方式依次重建：

1. `dwd_stock_income`
2. `dwd_stock_cashflow`
3. `dwd_stock_balance_sheet`
4. `dws_stock_income_quarter`
5. `dws_stock_cashflow_quarter`
6. `dws_stock_financial_indicator_quarter`（若阶段 E 有修改）
7. `dws_stock_factor_wide`
8. `dws_stock_factor_wide_matrix`

禁止直接覆盖生产表后再验证。

## 5. 测试与质量门禁

### 5.1 SQL 生成单元测试

更新 `tests/test_tushare_response.py`，至少断言：

- 三大报表 DWD 使用 `f_ann_date` 推导公告业务日期。
- 三个普通直接 CTE 都包含 `report_type = '1'`。
- 普通直接 CTE 排序以 `event_date` 优先于修订可用日期。
- income/cashflow 累计差分仍只使用 `(1,4)`，没有混入母公司类型。
- 原生单季诊断明确使用 `(2,3)` 且 `3 > 2`。
- `fina_indicator quarter` 在同业务键下显式优先 `update_flag=1`。

### 5.2 必须覆盖的 PIT 场景

1. 同一 `ann_date`、两个 `f_ann_date`：修订日前取旧版，修订日起取新版。
2. 旧报告期在新报告期之后修订：普通直接字段仍保持新报告期。
3. 同报告期 type=1 与母公司 type=6/7/9 同时存在：直接 JOIN 只能命中 type=1。
4. 同报告期 type=1、update_flag=0/1 同时存在：选行确定且可重复。
5. Q1 修订发生在 Q2 发布后：修订日前 Q1/Q2/TTM 不变，修订日起重算受影响季度。
6. 修订期已退出最近四期：当前 TTM 不变。
7. LYR_1 修订：不得抢占 LYR_0。
8. 周末 `f_ann_date`：从严格下一 SSE 交易日生效。

### 5.3 数据门禁

- 普通直接 income/balance_sheet/cashflow 的源 `report_type` 必须 100% 为 1。
- `(instrument_id, state_available_trade_date)` 在每个直接状态 CTE 中最多一行。
- 修订日前的宽表 TTM 校验和不得因未来修订变化。
- 修订日起的变化必须能追溯到 source record hash。
- 不允许 `available_trade_date` 早于有效 `f_ann_date` 的下一交易日。
- 发布前输出累计差分与原生单季 `(2,3)` 的覆盖率、匹配率和差异样本。

## 6. 验收标准

完成后应满足：

1. `000928.SZ / 2026-03-31` 修订版不早于 2026-05-11 进入宽表。
2. `000004.SZ` 的普通直接收入字段不再命中 type=9。
3. 所有普通直接财报字段只能追溯到 type=1。
4. 任何旧报告期修订都不会使 LF/MRQ 从较新报告期倒退。
5. TTM 在修订可用日前保持旧值，从修订可用日起按当时可见版本重算。
6. 单季链路不存在 `(1,3)` 混合口径。
7. 重复运行构建得到相同赢家，不再由接口抓取顺序或哈希偶然决定。

## 7. 主要风险

- 改用 `f_ann_date` 会显著改变历史宽表，需要完整重建，不能增量补一小段。
- 直接字段限制 type=1 后，少数没有 type=1 的证券/日期会变为 NULL；必须量化覆盖下降，不能回退到母公司类型填充。
- 原生单季与累计差分存在 3%–5% 差异，切换生产口径会改变大量 TTM 因子，必须经过阶段 D。
- `fina_indicator` 缺少精确修订日期，不能与三大报表达到完全相同的市场时间 PIT 精度。
- 当前 DWD 业务键包含 `report_type`、`update_flag` 等字段，各版本会并行保持打开状态；下游必须显式完成业务版本归并，不能依赖 `sys_to` 自动解决。
