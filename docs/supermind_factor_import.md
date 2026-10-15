# 同花顺(THS)因子历史入库 ClickHouse

把 `/nfs_data/quant_data/super_mind/history` 下的同花顺 `ths_factor` SDK 因子历史导入 ClickHouse,
并为后续 SDK 增量更新预留一致的落库结构。

## 数据来源与形态

- 磁盘布局:`TopCategory/SubCategory/FACTOR_CODE/YYYY/FACTOR_CODE-YYYY-MM-DD.csv`
- 每个 CSV 均为统一**长表**:表头 `time,code,<FACTOR_CODE>`,一行一只股票一天。
- universe:A 股(`.SH/.SZ/.BJ`,约 5000 只/天),全部**日频**。
- 规模:571 个因子、约 148 万个 CSV、224GB、约 2015–2026、约 77 亿个因子值。

SDK 模型(见 `docs/other/SDK接口函数说明20251210.docx` 与 `docs/other/【字典】因子对外字典20260908.xlsx`):
SDK 并非一因子一表,而是把因子分组为若干张表,产品名形如 `db__table`(双下划线 = `数据库__表名`)。
`read_data(sql_str, db)` 按 `__` 拆分,前半作数据库名。磁盘 13 个顶层目录与这些 SDK 表一一对应。

## 落库设计

ClickHouse 数据库 **`ths_ashare_daily`**(库名加 `ths` 前缀以标识来源),每个顶层目录一张**长表**,
表名 = SDK 的 `__` 后缀(表名**不加**前缀):

| 磁盘目录 | ClickHouse 表 | SDK 产品名 |
|---|---|---|
| DailyFreq | `ths_ashare_daily.daily_freq` | `ashare_daily__daily_freq` |
| MinFreq | `ths_ashare_daily.min_freq` | `ashare_daily__min_freq` |
| CallAuction | `ths_ashare_daily.call_auction` | `ashare_daily__call_auction` |
| TBTTran | `ths_ashare_daily.tbt_tran` | `ashare_daily__tbt_tran` |
| TBTOrder | `ths_ashare_daily.tbt_order` | `ashare_daily__tbt_order` |
| TickSnapshot | `ths_ashare_daily.tick_snapshot` | `ashare_daily__tick_snapshot` |
| DLTick | `ths_ashare_daily.dl_tick_snapshot` | `ashare_daily__dl_tick_snapshot` |
| TRFM | `ths_ashare_daily.trfm_model` | `ashare_daily__trfm_model` |
| RLPV | `ths_ashare_daily.rl_pv` | `ashare_daily__rl_pv` |
| RLFundamental | `ths_ashare_daily.rl_funda` | `ashare_daily__rl_funda` |
| MLNews | `ths_ashare_daily.ml_news` | `ashare_daily__ml_news` |
| LLMNews | `ths_ashare_daily.llm_news` | `ashare_daily__llm_news` |
| RLSentiment | `ths_ashare_daily.rl_senti` | `ashare_daily__rl_senti1..5` |

**表结构(所有表一致):**

```sql
CREATE TABLE ths_ashare_daily.<name>
(
    trade_date   Date32,
    ts_code      LowCardinality(String),
    factor_code  LowCardinality(String),
    sub_category LowCardinality(String),      -- 来自 SubCategory 目录,便于筛选/编目
    value        Nullable(Float64),           -- 部分因子天然为空(如 LLM_NEWS,约 60% 空)
    _ingest_time DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(_ingest_time)
PARTITION BY toYYYYMM(trade_date)
ORDER BY (factor_code, ts_code, trade_date);
```

### 为什么是"每组一张长表"

- **一表 vs 多表**:13 张表(每个 SDK 组一张),而非 571 张(part 过多)或宽表(稀疏列 + 每加一个因子就要 ALTER)。
- **SDK 一致性 / 增量**:表身份与 `db__table` 寻址与 SDK 完全一致;新交付的一天、甚至全新因子都只是多几行,无需 DDL。
  `ReplacingMergeTree(_ingest_time)` 保证按 `(factor_code, ts_code, trade_date)` 键重复导入幂等(最新 `_ingest_time` 胜出)。
- **硬件**:单个稠密 `Float64` 列 + `ts_code`/`factor_code` 的 `LowCardinality` 字典编码 + 月分区,
  压缩远优于宽表/稀疏;`ORDER BY factor_code` 在前,按因子扫描局部性好(实测 LLMNews 压缩比约 3.6x)。
- **使用便利**:按因子 = `WHERE factor_code='X'`;跨因子 = 条件聚合 pivot(见下)。

### 跨因子"宽表"访问(无需宽表存储)

```sql
SELECT trade_date, ts_code,
       anyIf(value, factor_code = 'DAY_PVC_AMPV') AS DAY_PVC_AMPV,
       anyIf(value, factor_code = 'DAY_PP_JDR')   AS DAY_PP_JDR
FROM ths_ashare_daily.daily_freq
WHERE trade_date BETWEEN '2024-01-01' AND '2024-12-31'
GROUP BY trade_date, ts_code;
```

### 元数据与编目表

- `ths_ashare_daily.factor_catalog(ch_table, sdk_product, sub_category, factor_code, name_en, name_cn, intro, since)`
  —— 由 `scripts/supermind_factor_catalog.py` 从因子字典构建,含中/英文名与介绍,并记录 SDK 的 `db__table` 产品名,
  供 SDK 增量路径做 product → 表映射。
- `ths_ashare_daily.load_manifest(group, table, factor_code, year, files, rows, done_at)`
  —— 导入进度,断点续跑按 `(group, factor, year)` 跳过已完成单元。

## 使用方式

从仓库根目录、`quant` 环境运行,务必带 `-I`(隔离脚本目录,避免 NFS 上同名模块被 import):

```bash
# 历史全量导入(可续跑;ReplacingMergeTree 保证重复导入幂等)
python -I scripts/import_supermind_history.py --group all

# 单组 / 只看计划 / 按日期过滤
python -I scripts/import_supermind_history.py --group DailyFreq
python -I scripts/import_supermind_history.py --group LLMNews --dry-run
python -I scripts/import_supermind_history.py --group DailyFreq --since 2024-01-01 --workers 8

# 构建/刷新因子元数据表(同时打印磁盘⇄字典交叉核对)
python -I scripts/supermind_factor_catalog.py --xlsx "docs/other/【字典】因子对外字典20260908.xlsx"
```

ClickHouse 连接从仓库根 `config.yaml` 的 `database:` 块读取(当前 `127.0.0.1:8123`,user `default`)。
脚本内所有 SQL/insert 均用全限定名 `ths_ashare_daily.<table>`,不依赖 client 默认库。

## 全量导入建议

- 先用最小组 `LLMNews`(2 个因子)跑通,核对 schema、编码、空值与吞吐,再跑其余组。
- 以 `(factor, year)` 分批,既控内存又给出干净的续跑单元;`--workers` 控制并行读/写线程。
- 预计压缩后体积远小于 224GB 原始 CSV。

## 验证清单

```bash
ch() { curl -s "http://127.0.0.1:8123/" --data-binary "$1"; }

# 1. 每因子行数/日期范围/空值率
ch "SELECT factor_code, count(), min(trade_date), max(trade_date), countIf(value IS NULL)
    FROM ths_ashare_daily.llm_news GROUP BY factor_code"

# 2. 对账:某因子某日 CH 行数 == 源 CSV 行数(减表头)
ch "SELECT count() FROM ths_ashare_daily.llm_news WHERE factor_code='LLM_NEWS_OD' AND trade_date='2025-01-02'"

# 3. 幂等:重跑应全部跳过,FINAL 行数不变
python -I scripts/import_supermind_history.py --group LLMNews
ch "SELECT count() FROM ths_ashare_daily.llm_news FINAL"

# 4. 存储/压缩
ch "SELECT formatReadableSize(sum(data_compressed_bytes)) FROM system.parts
    WHERE database='ths_ashare_daily' AND active"
```

## 后续:SDK 增量更新(已对齐,待实现)

落库结构已与 SDK 对齐,增量路径只需:

1. `FactorAPI.login(...)`,`get_product_list()` 确认有权限的产品。
2. 每日 `sync_data(start_date, end_date, product_list)`(或 `query`)取增量,
   把返回的 `(time, code, <factor>)` 规整成 `(trade_date, ts_code, factor_code, sub_category, value)`,
   `insert_df` 进对应 `ths_ashare_daily.<table>`(复用 `import_supermind_history.py` 的插入逻辑)。
3. product → 表映射查 `ths_ashare_daily.factor_catalog.sdk_product`;`ReplacingMergeTree` 保证当日重复拉取幂等。

> 本次仅做 A 股历史导入。港股/美股/ETF/期货(字典其他 sheet)暂不在范围内。
