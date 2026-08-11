# DWD 设计:申万行业成分 PIT 表(`dwd_sw_industry_member`)

> 面向 `index_member_all_raw` 的 point-in-time 加工设计。目标:给出"在任意历史交易日 T,某股票属于哪个申万三级/二级/一级行业"的可回测视图,**杜绝未来函数**。

## 1. 源数据形态(基于 2026-08-10 实测全量)

| 事实 | 实测 | 对设计的含义 |
|---|---|---|
| 业务时间轴 | `in_date`(纳入日)/ `out_date`(剔除日),`is_new` Y/N | **业务时间就是 PIT 时间**,天然存在,无需 `_ingest_time` |
| `in_date` 缺失 | 0 | 可安全作为区间左端 |
| `is_new='N'` 的 `out_date` 缺失 | 0 | 历史段区间右端完整 |
| `is_new='Y'` 的 `out_date` | 全 = 默认 `1970-01-01` | 当前段右端 = 开区间(至今) |
| `out_date < in_date` | 0 | 无逆序 |
| 同一时点属于多个 l3 | 0(互斥) | 三级行业是**单一归属**,任意 T 每股最多一条有效行 |
| l3 → l2/l1 层级 | 自洽(一个 l3 唯一归属) | l1/l2 可由 l3 决定,无需额外去冲突 |
| 重复进出 | 存在(同 ts_code+l3 出现 2 段) | 主键必须含 `in_date` |
| `in_date` 是否交易日 | 6022 交易日 / 9 落在节假日 | **生效日不保证是交易日,须平移到下一交易日** |
| 快照批次 | 只有 1 个(2026-08-10) | 见 §2 的关键约束 |

## 2. 关键约束:为什么 PIT 只能用业务时间,不能用 `_ingest_time`

现有通用 DWD builder(`raw_versioned`,`dwd.py`)用 `_ingest_time` 做 SCD-2 版本轴 —— 那适用于"每天采一次、想还原每天看到的快照"的接口。

**申万成分接口不适用**,因为:

1. **我们只有今天(2026-08-10)一个快照**。历史上每次行业调整发生时,我们并没有当时的采集记录。用 `_ingest_time` 做版本轴,只会得到"2026-08-10 一次性看到全部历史"这一个版本 —— 毫无 PIT 意义。
2. Tushare 这个接口返回的 `in_date`/`out_date` **本身就是权威的业务生效时间**。申万的成分调整是公开、有确定生效日的事件,`in_date`/`out_date` 就是这条时间轴。
3. 因此 **PIT 时间轴 = 业务时间轴(`in_date`/`out_date`)**,这与用户要求的"PIT 尽量和业务相关,防止未来函数"完全一致。

> 代价与假设:因为只有单快照,我们**信任 Tushare 当前返回的历史区间是正确的**,无法反映"申万事后修订某段归属"这类罕见情况。若未来想防这种修订风险,需要**定期采集并保留每日快照**,再叠加一层 `_ingest_time` 版本轴(knowledge_date)。当前设计先不做,留作后续增强(见 §7)。

## 3. 未来函数的防线:`available_date` 怎么取

三条时间要素,必须区分清楚:

- **`event_date`(业务生效日)= `in_date`**:申万宣布/生效该股进入此行业的日期。
- **`available_date`(最早可用交易日)**:回测里**最早能据此建仓**的交易日。
- **`end_date`(区间右端)**:`is_new='Y'` → 开区间(用远期哨兵 `2299-12-31`);`is_new='N'` → `out_date`。

### available_date 的取法

```
available_date = 「>= in_date 的最早 SSE 交易日」
```

理由:
- `in_date` 是生效日,可能落在周末/节假日(实测有 9 条)。回测中你只能在**交易日**调仓,所以要把生效日**向后平移到最近的可交易日**。
- 用 `>=`(含当日)而非严格 `>`:申万成分生效日当天该分类即成立,盘中/收盘即可知,当日收盘选股使用不构成未来函数。若你的策略更保守(要求"生效日之后一天才敢用"),可切换到 `next_trade_date`,见下。

### 与现有 `calendar_map` 的差异(重要)

`dwd.py` 里的 `_calendar_map_sql()` 算的是 `next_trade_date`(**严格大于** `cal_date` 的下一个交易日)。这里我们需要的是 **`>=` 的当日或之后最近交易日**,语义不同。方案:

- 复用 `trade_cal`,但用一个 `on_or_after_trade_date` 映射:`min(cal_date) WHERE is_open=1 AND cal_date >= in_date`。
- 提供开关 `available_offset ∈ {on_or_after, next}`:
  - `on_or_after`(默认,推荐):生效日当天收盘可用。
  - `next`:平移到生效日**之后**的下一个交易日,最保守,彻底杜绝"生效日盘中信息"疑虑。

### 查询语义(下游怎么用,天然防未来函数)

给定回测交易日 `T`,取当日行业归属:

```sql
SELECT ts_code, l1_code, l2_code, l3_code
FROM dwd_sw_industry_member
WHERE available_date <= T
  AND (end_date > T OR end_date = toDate32('2299-12-31'))
```

- `available_date <= T`:只看 T 当天**已经可知**的成分,不会用到未来才生效的调整。
- `end_date > T`:该段在 T 仍然有效。
- 因 §1 证明区间互斥,每股在 T 最多命中一条 → 无需去重。

## 4. 表结构 `dwd_sw_industry_member`

因为 PIT 语义完全由业务时间驱动、与通用 `raw_versioned` 的 `_ingest_time` 轴不同,**建议新增一个 builder `business_interval`**(见 §5),而不是硬套 `raw_versioned`。

列设计(在 `COMMON_DWD_COLUMNS_NO_INSTRUMENT` 思路上裁剪,业务列直接来自源):

| 列 | 类型 | 来源 / 说明 |
|---|---|---|
| `ts_code` | str | 成分股票代码(业务键) |
| `name` | str | 成分股票名称(快照值) |
| `l1_code` `l1_name` | str | 申万一级 |
| `l2_code` `l2_name` | str | 申万二级 |
| `l3_code` `l3_name` | str | 申万三级(最细归属) |
| `in_date` | date | 纳入日(= `event_date`,业务键之一) |
| `event_date` | date | = `in_date`,语义列,便于跨表统一 |
| `available_date` | date | **最早可用交易日**(§3) |
| `end_date` | date | `is_new='N'` → `out_date`;`is_new='Y'` → `2299-12-31` |
| `is_current` | int | `is_new='Y'` → 1 else 0,便于快速取当前 |
| `source` `source_table` `source_batch_id` `source_record_hash` | str | 血缘,来自 raw |

**业务主键 / ClickHouse ORDER BY**:`(ts_code, l3_code, in_date)`。
**partition_key**:建议 `toYYYYMM(available_date)` 或不分区(数据量仅数千行,可不分区)。
**engine**:`ReplacingMergeTree`(与项目其它 DWD 一致;主键含 `in_date` 不会误折叠)。

## 5. 加工逻辑(builder: `business_interval`)

从 `index_member_all_raw` 出发。**注意用 raw 表而非 latest**,并对同一业务键去重(取最新采集哈希),避免多次运行 raw 追加造成重复。

```sql
INSERT INTO {db}.dwd_sw_industry_member
WITH
on_or_after AS (   -- >= 的当日或之后最近 SSE 交易日
    SELECT c.cal_date AS eff_date, min(o.cal_date) AS avail_date
    FROM {db}.trade_cal c
    LEFT JOIN {db}.trade_cal o
      ON o.exchange='SSE' AND o.is_open=1 AND o.cal_date >= c.cal_date
    WHERE c.exchange='SSE'
    GROUP BY c.cal_date
),
dedup AS (   -- 每个业务键取一条(raw 可能多批追加)
    SELECT *
    FROM (
        SELECT src.*,
               row_number() OVER (
                 PARTITION BY ts_code, l3_code, in_date
                 ORDER BY _ingest_time DESC, _batch_id DESC
               ) AS rn
        FROM {db}.index_member_all_raw src
        WHERE ts_code IS NOT NULL AND in_date IS NOT NULL
    ) WHERE rn = 1
)
SELECT
    d.ts_code, d.name,
    d.l1_code, d.l1_name, d.l2_code, d.l2_name, d.l3_code, d.l3_name,
    d.in_date,
    d.in_date AS event_date,
    coalesce(cal.avail_date, d.in_date) AS available_date,
    if(d.is_new='Y', toDate32('2299-12-31'), d.out_date) AS end_date,
    if(d.is_new='Y', 1, 0) AS is_current,
    d._source, 'index_member_all_raw', d._batch_id, d._record_hash
FROM dedup d
LEFT JOIN on_or_after cal ON cal.eff_date = d.in_date
```

- `dedup`:防 raw append-only 重复。
- `on_or_after` join:把生效日平移到可交易日。
- 全程只用业务时间 → 无未来函数。

沿用 `dwd.py` 现有的 `sync_table` 机制(tmp 表 + `EXCHANGE TABLES` 原子替换 + `QualityManager.validate_publish`),无需改动执行框架,只需让新 builder 走 `render_sync_sql` 分支。

## 6. 校验点(接入 QualityManager 的规则建议)

1. **区间不重叠**:同 `(ts_code, l3_code)` 的 `[in_date, end_date)` 不得重叠(实测当前成立)。
2. **每股每日单一 l3**:任取采样交易日 T,`available_date <= T < end_date` 的行按 `ts_code` 分组 count 应 = 1。
3. **available_date >= in_date** 且为交易日(或等于 in_date 的兜底)。
4. **层级自洽**:l3 → 唯一 l2/l1。
5. **计数一致**:`is_current=1` 行数应 ≈ latest 表 `is_new='Y'` 行数(当前 5889)。

## 7. 后续增强(本轮不做)

- **knowledge_date 双时间轴**:定期采集每日快照并保留 `_ingest_time`,叠加第二条版本轴,支持"截至某个认知日,当时看到的历史归属",防申万事后修订。需先积累多日快照。
- **接入 DWS**:把行业归属并入 `dws_stock_factor_wide`(行业中性化、行业哑变量),用 `available_date`/`end_date` 做 as-of join。
- **DWD 命令与编排**:新增 `schema/dwd/dwd_sw_industry_member.yaml` 后,`python main.py dwd sync dwd_sw_industry_member` 即可用;jobs 编排挂在 `index_member_all` 采集之后。

## 8. 落地清单(已实现)

- [x] 新增 `tushare_integration/schema/dwd/dwd_sw_industry_member.yaml`(spec + `builder: business_interval` + 显式 schema 块,主键 `(ts_code, l3_code, in_date)`)。
- [x] `dwd.py` 增加 `business_interval` builder 分支:`build_schema`(保留业务主键,不清空)、`_render_business_interval_sync_sql`、`_on_or_after_calendar_map_sql`、`render_sync_sql` / `get_required_source_tables` 分支。
- [x] `available_offset` 开关(默认 `on_or_after`,可切 `next`)。
- [x] QualityManager 规则:`_build_business_interval_dwd_rules`(PIT列非空、`available_date>=event_date`、区间有序、区间不重叠、血缘完整)。`strict` 模式通过。
- [x] 接入编排:`scripts/run_daily_market_jobs.sh` 在 `dwd_index_classify` 之后增加 `dwd_sw_industry_member` sync(挂在 `index/sw` 采集之后)。
- [x] 验证:strict sync 通过;7893 行(5889 current);`avail_before_in=0`;as-of 查询 2020-01-02 每股唯一无重复;2026-06-30 集中剔除批次对齐。

### 实现备注

- `Date32` 上限约 `2299-12-31`,`9999-12-31` 会被静默截断,故区间右端哨兵统一用 `toDate32('2299-12-31')`(`dwd.py` 的 `FAR_FUTURE_DATE_SQL` / `quality.py` 的 `FAR_FUTURE_DATE`)。
- `on_or_after` 平移用 **ASOF LEFT JOIN**(带常量 equi-key)实现"`>=` 生效日的最早 SSE 交易日":早于日历起始日(1990-12-19)的 12 条 `in_date` 会平移到 `1990-12-19`,不会出现 `available_date < in_date`。
- 命令:`python main.py dwd sync dwd_sw_industry_member`;渲染 `python main.py dwd sql dwd_sw_industry_member`。
