# RiceQuant（米筐）数据接入设计与开发指南

## 1. 范围与不变量

本实现是独立的 `ricequant_integration` 包、CLI、配置、状态表和 CronJob。它与现有 Tushare
任务可以并行运行，但同一时刻只允许一个 RiceQuant 历史下载 runner。
[实时分钟订阅程序](ricequant_realtime.md) 使用独立锁，可以与下载任务并行运行。现有 Tushare Spider、Pipeline、表模板和
Job 均未改变。

已接入数据包括核心指数行情/成份/权重、全 A 股 Tick、从 2015 年开始的未复权日线、从 2020 年开始的
未复权 1 分钟线、独立复权/拆分因子，以及最近一周的概念和行业快照；交易日历和按交易日的证券快照
作为依赖一并采集。财务数据通过 `get_pit_financials_ex` 按官方字段组拆成利润表、资产负债表、现金流量表
和独立财务指标四张表。期权从 2019 年开始采集全部境内合约快照和日线行情，ETF 期权另存每日动态
合约属性。所有物理表以 `ricequant_` 开头。不同来源之间不做字段回退、
`coalesce` 或自动优先级选择。尤其深证成指、创业板指、中小板指的成交量/成交额口径可能与其他来源
不同，使用时必须保留来源并单独核对。

## 2. 时间模型与覆盖清单

每个数据集声明一种主时间语义：

| 语义 | 切片与覆盖依据 | 示例 |
| --- | --- | --- |
| `trading_date` | 米筐交易日历 | 指数日行情、成份、Tick |
| `calendar_date` | 自然日 | 交易日历 |
| `report_period` | 报告期 | 四类 PIT 财务数据 |
| `source_update_time` | 源更新时间 | 公告修订流 |
| `snapshot` | 快照时点 | 权重、证券列表 |

`ricequant_coverage_event` 是追加式事件清单。每条事件有唯一 `event_id`，保存 dataset、slice、起止范围、
状态、游标、分区、行数和内容哈希。当前状态通过 `(event_time, event_id)` 的 `argMax` 得出；增量边界来自
该清单，而不是目标表的 `max(date)`。因此空结果、配额暂停和部分完成也可表达，任意时间段都可以后补。

财务报表不伪造交易日：源 `quarter` 显式转换为季度末 `report_period`，`info_date` 是源公告发布日期，
`rice_create_tm` 是米筐记录创建时间；二者均原样保存，缺失保持 NULL。每次请求还保存调用的
`query_date` 与本地完成观察时间 `observed_at`。`available_trade_date` 只能在后续 DWD 中用米筐自己的
交易日历派生，而且应至少晚于公告日，避免公告当日盘前/盘后不明确造成前视。仅选择财务数据集运行时
不会请求或依赖交易日历；季度边界完全由自然季度计算。

财务接口固定使用 `statements='all'`，保留截止 `query_date` 可见的全部披露版本。非空
`source_version_id` 由 `order_book_id + quarter + info_date + if_adjusted + rice_create_tm` 稳定生成；它允许
源时间字段保持 NULL，同时防止重拉产生重复。增量任务重扫最近 `financial_rescan_days`（默认 1100 天）
覆盖比较期披露和源修订；更老报告期通过显式 backfill 复查。历史查询只能表达米筐当前返回的历史披露
版本，若源事后补录且没有新的源版本时间，不能声称该记录此前已被本系统观察到，此限制必须传递给
DWD/DWS 血缘。

### 双时间与 PIT 规则

所有新数据集都必须区分“源数据表示的生效/快照时间”和“本系统实际观察到该值的时间”：

- 源接口提供日期参数时，保存请求的 `snapshot_date`，并同时保存 `observation_date`、`observed_at`；
- 源接口不提供日期参数时，只保存 `observation_date`、`observed_at`，禁止把下载日命名为源生效日；
- 每个观察日是独立版本，同一观察日重跑原子替换，跨观察日不得覆盖旧版本；
- 同一逻辑快照只使用一个 `observed_at`，取整张快照组装完成、准备原子发布的时间；禁止按 API
  分页或成员逐行赋不同观察时间，避免 PIT 查询得到半张快照；
- DWD/DWS 的 PIT 连接只能使用 `observed_at <= 计算时点` 的最新版本；
- 历史日期查询若没有源公告时间或版本时间，只能证明“下载时看到的历史归属”，不能证明该结果在历史
  当时已知。该限制必须随字段血缘传递到宽表；
- 源提供的 `announcement_date`、`rice_create_tm` 等时间原样保留，NULL 不推断、不用其他来源补齐。

上述规则适用于以后接入的财务、分类、成份、标签等所有可能修订的数据，不仅限于概念和板块。

## 3. 表、键和原子发布

最终表全部使用普通 `MergeTree`，不使用 `ReplacingMergeTree`，也没有 raw 表：

| 表 | 业务键 | 分区 |
| --- | --- | --- |
| `ricequant_trading_calendar` | `calendar_date` | 年 |
| `ricequant_instrument` | `snapshot_date, order_book_id` | 快照日 |
| `ricequant_option_instrument` | `observation_date, snapshot_date, order_book_id` | 观察日、源快照日 |
| `ricequant_option_contract_property` | `trading_date, order_book_id` | 交易日 |
| `ricequant_option_daily` | `trading_date, order_book_id` | 交易日 |
| `ricequant_index_daily` | `order_book_id, trading_date` | 指数、月 |
| `ricequant_index_component` | `index_id, trading_date, component_id` | 指数、月 |
| `ricequant_index_weight` | `index_id, snapshot_date, component_id` | 指数、月 |
| `ricequant_index_weight_ex` | `index_id, trading_date, component_id` | 指数、月 |
| `ricequant_stock_daily` | `trading_date, order_book_id` | 交易日 |
| `ricequant_stock_minute` | `trading_date, order_book_id, datetime` | 交易日 |
| `ricequant_stock_ex_factor` | `order_book_id, ex_date` | 股票 |
| `ricequant_stock_split` | `order_book_id, ex_dividend_date, book_closure_date` | 股票 |
| `ricequant_income_statement` | `order_book_id, report_period, source_version_id` | 股票 |
| `ricequant_balance_sheet` | `order_book_id, report_period, source_version_id` | 股票 |
| `ricequant_cashflow_statement` | `order_book_id, report_period, source_version_id` | 股票 |
| `ricequant_financial_metric` | `order_book_id, report_period, source_version_id` | 股票 |
| `ricequant_concept_snapshot` | `observation_date, snapshot_date, concept_name, order_book_id` | 观察日、源快照日 |
| `ricequant_industry_snapshot` | `observation_date, snapshot_date, source_name, industry_level, order_book_id` | 观察日、源快照日 |
| `ricequant_sector_snapshot` | `observation_date, sector_code, order_book_id` | 观察日 |
| `ricequant_stock_tick` | `trading_date, order_book_id, datetime, tick_sequence` | 交易日 |

普通数据先写同结构临时表，验证主键非空和无重复后，通过 `REPLACE PARTITION` 原子替换。更新月分区中的
一天时，先在服务端复制该分区的其他日期，再加入新数据，避免覆盖历史。指定半个月做 backfill 也使用
相同的范围排除逻辑。

`ricequant_index_weight` 保存 `index_weights` 的月末源权重快照；`ricequant_index_weight_ex` 保存
`index_weights_ex` 从 2015 年开始的日度动态权重。后者是米筐基于上月末成份和 ETF 申赎清单计算的
动态结果，并非前者的简单日频版本。两者独立保留 API lineage，不做 `coalesce`、回填或自动优先级选择。
`index_weights_ex` 不使用 YAML 的 `indexes` 配置，而是逐一调用 rqdatac 官方固定支持的9个指数。

Tick 是特殊的两级提交：一个交易日只有一张持久 staging 表；每只股票写入前先同步删除该股票旧数据，
所以“写成功、游标未提交”的崩溃也能安全重放。每 25 只股票记录一次游标。全市场股票都处理完、日期和
主键检查通过后，才替换最终日分区；查询最终表永远看不到半天数据。阶段数据最多保留一个尚未完成的
交易日。

同一时间戳的合法多笔 Tick 用源返回顺序的 `cumcount` 形成稳定 `tick_sequence`，重拉时键保持一致。

日线和分钟线固定请求 `adjust_type='none'`、`skip_suspended=True`。复权因子与拆分因子独立落表；当前
源层不生成前/后复权副本。后续 DWD/DWS 按明确的基准日和 PIT 截止时间合成：价格使用综合累计复权因子，
若需完全复刻米筐默认 `pre/post` 的成交量语义则使用拆分累计因子。复权算法上线前必须在分红、送转和
停牌样本上与米筐四种复权模式逐字段核对。

分钟线与 Tick 一样按日 staging、按股票批次记录游标，整日完成后发布。概念和中信/申万行业仅下载最近
一周的日期快照；`sector()` 无日期参数，只能从接入日起保留每日观察版本，不能回补或伪造历史快照。

四组财务业务字段来自 rqdatac 3.8.1 官方常量，分别为 94、194、74、32 个且互不重叠。独立指标表的
32 列由 `MAINDATA_FIELDS`（2）、`TTM_FIELDS`（23）和研发支出字段（7）组成。每组独立调用接口、独立
记录 coverage 和额度、独立断点；不会与 Tushare 的 income/balancesheet/cashflow/fina_indicator 合并，
也不会跨来源补值。表按股票分区，一批 API 返回按股票拆分后，用报告期范围原子替换；已完成股票在相同
bootstrap 范围内直接跳过。四类财务数据的统一历史起点为 `2015-01-01`；显式请求更早日期也会被该边界
限制。进程若在请求后、发布前崩溃，最多重拉当前小批次，不会重复最终表记录。

期权使用三条独立链路，不扩展股票 `ricequant_instrument`。`option_instruments` 调用
`all_instruments(type='Option', date=...)`，保留源快照日期和本系统观察时间；米筐说明该接口的合约详情
可能是最新状态，因此历史 ETF 行权价和乘数必须以 `options.get_contract_property` 为准。动态属性表只
包含该接口支持的交易所 ETF 期权；期权日线通过 `get_price(frequency='1d', adjust_type='none')` 覆盖
ETF、股指和商品期权。行情和属性按月规划、按合约游标续传、按交易日原子发布，统一历史下限为
`2019-01-01`。已完成月份在重复 backfill 时跳过，未完成月份从持久 staging 和最后合约代码恢复。

## 4. 配额、断点与每日增量

每次 API 调用前读取 `rqdatac.user.get_quota()` 的 `bytes_limit` 与 `bytes_used`。剩余额度不大于
`max(256 MiB, 最近同类切片 P80 估算 × 1.5)` 时停止。配额暂停是预期状态，CLI 返回 0，调度器不会立即
失败重试；第二个配额日从 coverage 游标继续。消耗量按调用记录到 `ricequant_quota_observation`，估算随
实际数据自动校正。`time_slice` 不用于省配额，因为该参数仍会下载完整数据。

每日 T+1 运行顺序如下：

1. 每日数据就绪时间（默认上海时间 18:00）后，从米筐交易日历与 coverage 清单确定所有已结束但未完成的交易日；
2. 更新指数行情、成份；普通权重按每月最后交易日快照更新，`index_weights_ex` 更新日度动态权重；
3. 取得当日证券快照，按股票恢复 Tick；
4. 完成全市场后发布 Tick 日分区并把 slice 标为 complete。

历史首拉用月切片；`backfill --start/--end` 可补任意旧区间。每日增量会重扫指数最近 7 天以接住源修订，
但原子重建键范围，不会重复。若单日全市场 Tick 长期超过每日 5GB，系统会持续呈现 backlog/lag 并跨日
续传，不跳过数据，也不虚报完成。

## 5. 使用方式

复制 `ricequant.example.yaml` 为 `ricequant.yaml`，数据库配置写入该文件。米筐只提供一段不透明的
RQSDK License/token，不需要用户名和密码。实现会在进程内将它包装为官方要求的 `RQDATAC_CONF`，再调用
`rqdatac.init()`；用户不需要自行拼接连接 URI。token 只通过环境变量或 Kubernetes Secret 提供：

```bash
export RQDATA_TOKEN='米筐提供的完整许可证字符串'
python -m ricequant_integration --config ricequant.yaml init-db
python -m ricequant_integration --config ricequant.yaml bootstrap
python -m ricequant_integration --config ricequant.yaml incremental
python -m ricequant_integration --config ricequant.yaml backfill --dataset index_daily --start 2010-01-01 --end 2019-12-31
python -m ricequant_integration --config ricequant.yaml status
python -m ricequant_integration --config ricequant.yaml quota
```

`quota` 只调用米筐的额度查询接口，不访问 ClickHouse，也不触发下载。输出保留服务端返回的精确字节数，
并附带 GiB、使用百分比、框架最小预留额度以及扣除最小预留后的可用字节数。通过 Docker 脚本执行时，
额度查询不会占用下载任务锁，因此可以在 bootstrap 或 incremental 运行期间查看：

```bash
scripts/run_ricequant_jobs.sh quota
```

Kubernetes 中可创建只包含该 token 的 Secret（请勿把真实值写进 values 或提交到仓库）：

```bash
kubectl create secret generic ricequant-credentials \
  --from-literal=RQDATA_TOKEN='米筐提供的完整许可证字符串'
```

`bootstrap` 可重复执行，已完成月切片从清单跳过；`incremental` 适合每天调度；`backfill` 是按需补历史的
统一入口。对快照数据显式执行 `backfill --start/--end` 会重新采集并原子替换同观察日、同源快照日的
版本，可用于验证源修订或修复采集逻辑；普通 `bootstrap/incremental` 仍跳过当天已经完成的版本，避免
无意重复消耗额度。独立 Helm Chart 位于 `deploy/ricequant-integration`，使用 `concurrencyPolicy: Forbid`，不会与
Tushare Job 混在一个 CronJob 中。

### Docker + crontab 部署

非 Kubernetes 环境使用 `scripts/run_ricequant_jobs.sh`。脚本与现有 Tushare 宿主机调度方式一致：每次
启动一个 `--net=host` 的短生命周期容器，同时使用米筐独立的容器名、锁文件和日志。配置挂载自
`ricequant.yaml`，token 由权限为 `600` 的 `ricequant.env` 通过 Docker `--env-file` 注入：

```bash
cp ricequant.example.yaml ricequant.yaml
cp ricequant.env.example ricequant.env
chmod 600 ricequant.env
docker build -t tushare-integration:ricequant-v1 .

scripts/run_ricequant_jobs.sh init-db
scripts/run_ricequant_jobs.sh bootstrap --dataset index_daily --dataset index_components --dataset index_weights
scripts/run_ricequant_jobs.sh bootstrap --dataset tick
scripts/run_ricequant_jobs.sh backfill --dataset option_instruments --dataset option_contract_property --dataset option_daily --start 2019-01-01 --end "$(date +%F)"
scripts/run_ricequant_jobs.sh bootstrap --dataset financial_income --dataset financial_balance --dataset financial_cashflow --dataset financial_metric
scripts/run_ricequant_jobs.sh backfill --dataset financial_income --instrument 000001.XSHE --start 2024-01-01 --end 2024-12-31
scripts/run_ricequant_incremental.sh
```

额度暂停时，第二天重复相同的 `bootstrap` 命令即可恢复。历史首拉完成后，在宿主机 crontab 中配置：

```cron
30 18 * * 1-5 /data/flc/code/quant/tushare-integration/scripts/run_ricequant_incremental.sh
```

`run_ricequant_incremental.sh` 显式调度当前已经实现的全部增量数据集，包括股票日线、分钟线、复权/拆股、
指数、期权合约/动态属性/日线、概念、行业、板块、四类财务数据和 Tick；交易日历及证券列表由依赖解析自动加入。Tick 默认开启且可能消耗较多
额度；若不需要每日 Tick，可在 crontab 命令前设置 `RICEQUANT_INCLUDE_TICK=0`，其余数据集不受影响。
wrapper 的标准输出、错误堆栈和最终退出码写入
`logs/ricequant-incremental-cron-YYYYMMDD.log`；底层任务仍保留自己的
`logs/ricequant-incremental-YYYYMMDD.log`。

默认日志写入 `logs/ricequant-<mode>-YYYYMMDD.log`。可使用 `RICEQUANT_IMAGE`、
`RICEQUANT_CONFIG_FILE`、`RICEQUANT_ENV_FILE` 和 `RICEQUANT_LOG_DIR` 覆盖默认路径。

## 6. 新增数据集流程

1. 先确认官方 API 的返回形态、配额量级、修订行为、字段单位和 PIT 含义；不得假定同名字段与 Tushare
   可互换。
2. 在 `specs.py` 声明时间语义、业务键、分区、频率、可变窗口和依赖。
3. 在 `schema.py` 增加带 `ricequant_` 前缀的普通 MergeTree 表；选择能完整原子重建的分区。
4. 在 `client.py` 增加一个薄 API 调用，在 `transform.py` 显式映射字段、类型、单位和稳定键。
5. 在 runner 中用 coverage 规划切片。所有源 API 请求必须经过统一 `_fetch`，不得绕过配额保护、用量
   观测和 `ProgressReporter`；这样新增数据集自动获得开始、周期性心跳、失败位置和结束汇总日志。
6. 所有最终写入经过 staging 发布。适配器只补充百分比、证券数等领域特有进度，不另造日志协议。
7. 添加以下测试：响应形态、空响应、同键重复、重拉、部分区间回填、配额边界、崩溃续传、可变窗口
   修订、PIT/NULL 时间，以及同一逻辑快照的 `observed_at` 唯一性。
8. 先在隔离数据库执行小区间 bootstrap/backfill，对源记录数和哈希；再执行两次相同命令确认键重复为
   0；最后运行完整 Tushare 回归测试后才启用独立 CronJob。

## 7. 运维检查

关注 coverage 中长期 `partial/quota_paused` 的 Tick 日、最新 complete 日期与交易日历的差距、单切片配额
P80、最终表主键重复数，以及 staging 表的日期。禁止人工把 partial 改成 complete。源侧口径或历史值变化
应作为差异报告，不得用另一数据源自动填补。

