# 沪深 A 股与中证 2000 实时 1 分钟行情

`scripts/subscribe_ricequant_minute.py` 是常驻订阅程序，默认写入
`ricequant_stock_minute_realtime`。直接订阅 rqdatac 3.8.1 的 `bar_<order_book_id>`
频道：1 分钟线由米筐服务端聚合后推送，不在客户端下载 tick 再合成。

增加 `--scope csi2000` 时只订阅中证 2000 的 `bar_932000.INDX`，写入独立的
`ricequant_index_minute_realtime` 表及 `ricequant_index_minute_realtime_latest` 视图。
此模式固定为一个分钟频道，不订阅 tick、成份股或其它指数，也不读取 YAML 的 `indexes`。
实时订阅会消耗米筐授权的流量；仅建表不会连接米筐，常驻采集需要明确运行启动命令。

## 启动

依赖使用项目 `requirements.txt`，新增的 `websockets==15.0.1` 与 SDK 的同步订阅接口兼容。
在已有的 `quant` 环境中，可以只补齐 SDK 和订阅依赖，避免重装整个项目的依赖：

```bash
python -m pip install 'rqdatac[subscribe]==3.8.1'
```

SDK 的同步订阅需要支持 `proxy` 参数的 websockets 版本（15 或更新版本）；
若环境里已经有兼容版本，上述命令会保留它。
数据库配置复用 `ricequant.yaml`；米筐只需要 `ricequant.env` 内的 `RQDATA_TOKEN`，
程序复用项目的 license 认证，不需要单独填写用户名和密码。

```bash
python scripts/subscribe_ricequant_minute.py --config ricequant.yaml --env-file ricequant.env
```

env 文件使用 Docker 的 `KEY=value` 格式，token 原样填写，不加 shell 引号。
程序不会执行文件里的 shell 代码；已设置的环境变量优先。
token 不写入日志、YAML 或命令行。仅建表/验证结构无需米筐 token：

```bash
python scripts/subscribe_ricequant_minute.py --config ricequant.yaml --create-table
```

仅准备中证 2000 的表（不连接米筐、不产生订阅流量）：

```bash
python scripts/subscribe_ricequant_minute.py --config ricequant.yaml --scope csi2000 --create-table
```

启动中证 2000 分钟订阅（会产生订阅流量）：

```bash
python scripts/subscribe_ricequant_minute.py --config ricequant.yaml --env-file ricequant.env --scope csi2000
```

中证 2000 的队列默认在 `data/ricequant-realtime-csi2000/`，日志为
`logs/ricequant-realtime-csi2000.log`。股票和指数可以独立启停，目标表、队列和写入锁必须分开。
表注释与队列元数据记录订阅范围，启动和写入时校验，拒绝把股票与指数行情混入同一目标。

启动时自动建表和 `<表名>_latest` 视图。已有同名表必须与预期结构一致，程序不会改造或覆盖其他表。
若希望物理表就叫 `realtime`，增加 `--table realtime`；队列目录需要与其他写入目标分开。

Docker 常驻部署，宿主机或进程重启后自动恢复，并把本地队列和日志保存在宿主机：

```bash
docker build -t tushare-integration:ricequant-v1 .
bash scripts/run_ricequant_realtime.sh start
bash scripts/run_ricequant_realtime.sh status
bash scripts/run_ricequant_realtime.sh logs
bash scripts/run_ricequant_realtime.sh stop
```

Docker 中单独管理中证 2000，用同一个 scope 执行各项命令：

```bash
RICEQUANT_REALTIME_SCOPE=csi2000 bash scripts/run_ricequant_realtime.sh start
RICEQUANT_REALTIME_SCOPE=csi2000 bash scripts/run_ricequant_realtime.sh status
RICEQUANT_REALTIME_SCOPE=csi2000 bash scripts/run_ricequant_realtime.sh logs
RICEQUANT_REALTIME_SCOPE=csi2000 bash scripts/run_ricequant_realtime.sh stop
```

默认容器名为 `ricequant-realtime-csi2000`，与股票容器和队列独立。

首次启动使用 `start`；停止后恢复已有容器使用 `docker start ricequant-realtime`。
更新镜像/配置后需要在停止状态下移除旧容器并重新 `start`，保持挂载的队列目录不变。
`start` 不会自动强制删除已有容器。此常驻进程使用独立锁，不占用历史回填 runner 的锁；
米筐 license 的同时登录机器/进程数与实时订阅权限仍需满足两类程序并行使用的要求。

## 表与数据口径

物理表是普通 `MergeTree`，`PARTITION BY trade_date`。
`trade_date` 从源消息的 `trading_date` 解析；`datetime` 原样表示源分钟时间，
明确使用 `Asia/Shanghai`，不自行移动分钟起止标签。
`received_at` 是本系统观察时间，和源分钟时间分开保存。

OHLC、`volume`、`total_turnover`、`num_trades` 直接使用 bar 消息对应字段，
保留来源数值、不复权、不换算单位，不用 tick 或其他数据源字段补值。
数值列使用 `Nullable(Float64)`，与现有米筐分钟表一致；缺失/NaN 保存为 NULL，0 保持为 0。
`source_datetime`、`source_trading_date`、`payload_json`、`record_hash` 保存源表示及完整消息，
`source` 和 `api_name` 明确血缘。非法时间、交易日不一致、负数和非有限数会拒收并记录错误计数。

物理表保留收到的分钟观察版本，每个 `event_id` 唯一；同一标的同一分钟重新推送时，
可能增加一个版本。常规查询使用 `_latest` 视图，它按
`trade_date, order_book_id, datetime` 返回接收时间最新的一整条观察，
包括最新版本中的 NULL，既不依赖后台去重，也不拼接不同版本的字段。

```sql
SELECT trade_date, order_book_id, datetime, open, high, low, close,
       volume, total_turnover, received_at
FROM default.ricequant_stock_minute_realtime_latest
WHERE trade_date = today('Asia/Shanghai')
ORDER BY order_book_id, datetime;
```

查询中证 2000：

```sql
SELECT trade_date, order_book_id, datetime, open, high, low, close,
       volume, total_turnover, received_at
FROM default.ricequant_index_minute_realtime_latest
WHERE order_book_id = '932000.INDX' AND trade_date = today('Asia/Shanghai')
ORDER BY datetime;
```

指数的 OHLC 是指数点位。成交量、成交额及成交笔数保留米筐指数 bar 的源值，
缺失时保存 NULL，不用股票成份行情计算或补值，也不假定与股票字段具有相同单位或统计口径。
指数实时表与现有 `ricequant_index_daily` 分开保存，不生成指数日线或历史覆盖记录。

实时分钟线可能遗漏晚到 tick，与盘后重新清洗聚合的
`ricequant_stock_minute` 存在差异。此程序不会用历史分钟线自动覆盖或补齐实时表。
PIT 查询应在物理表上先用 `received_at <= 计算时点` 过滤，再按业务键取整条最新观察；
`_latest` 视图只代表当前已观察到的最新结果。

## 保留最近 7 个分区

ClickHouse 时间 TTL 表示自然时间过期，不能精确实现保留最新 N 个现存分区。
程序启动后及每 60 秒查询目标表的 `system.parts`，仅统计 active 分区，
保留最新 **7 个实际存在的交易日分区**，对其余执行 `DROP PARTITION ID`。
因此长假期间仍保留 7 个有数据的交易日，不会按 7 个自然日删除。
清理只作用于配置的实时表；历史表不受影响。

队列中早于最旧保留分区的消息也会清理；过期迟到消息不会重新创建已淘汰分区。
清理可能短暂滞后一个检查周期，程序停止期间不会自动删除分区，重新启动后继续。
可使用 `--keep-partitions N` 和 `--cleanup-seconds S` 调整。

## 长期运行、恢复与容量

- 每天上海时间 07:00 后重新请求 `all_instruments(type='CS', date=当天, cached=False)`，
  只选择沪深 A 股代码段，排除 B 股、北交所、ETF 等；新增上市股票增订阅，退市股票退订阅。
  请求失败每 300 秒重试，刷新过程不需要每天重启。
  中证 2000 模式固定订阅一个标的，不请求或刷新全市场股票池。
- SDK 自动断线重连和重订阅；SDK 线程退出的异常由主循环接收，指数退避重试，最长 300 秒。
  `QuotaExceeded` 退出时等待上海时间次日 00:01，避免持续重试耗尽的日配额。
  实时推送与普通 RQData 拉取是否共用字节配额，以授权方案为准。
- 心跳每分钟记录请求/服务端确认的频道数、队列积压及非法消息计数。确认数不足会明确报错，
  不把 SDK 的“请求订阅列表”当作全部股票已订阅成功的证明。
  服务端确认计数读取固定 SDK 3.8.1 的 `_subscribed`；本地子类在每次建立连接前清空旧确认，
  避免 SDK 重连时累计旧连接的确认。升级 SDK 时需重新核对连接和 ACK 接口。
  股票池刷新先扩展读线程的接收集合，再发送订阅变更；部分批次失败时仍接收已经订阅的新股票，
  后续刷新会重试全部变更。
- SQLite WAL 队列默认放在 `data/ricequant-realtime/outbox.sqlite3`，批量同步落盘；
  ClickHouse 写成功后才删除队列事件。响应丢失或重启时，先查已写入的 `event_id`，
  再重放未写入部分。当前批次在 SQLite 中冻结并跨重启保留，配合 ClickHouse 的
  `insert_deduplication_token` 和非复制表同步插入去重窗口（10000 个块），
  防止超时后原写入仍在提交时发生重复。这不依赖后台合并去重。每个目标表只允许一个写入进程，
  同一队列目录由文件锁保护；不要用不同目录/不同宿主机同时写同一表。
- 每批最多 1000 行、空队列时每 2 秒尝试写入；写入失败每 10 秒重试。
  内存队列上限 5 万条，持久队列上限 200 万条（约全市场 1.7 个交易日的单版本分钟消息）；
  满后产生背压并报错，不无限占用内存或磁盘。SQLite 已分配空间会复用，文件大小不会随删除立即缩小。
- SIGINT/SIGTERM 会关闭订阅，把已接收的内存消息尽量落入队列后退出。
  硬崩溃前未落盘的消息、断网期间的行情，以及队列满导致的长时间背压，均可能留下缺口。
  WebSocket 没有提供本脚本可依赖的历史重放保证，程序不会宣称这些时段完整。
  本功能不生成历史 runner 的 complete 覆盖记录。
- 文件日志按日轮转，保留 7 个日志备份；Docker 日志也限制大小。

官方参考：[实时订阅与 LiveMarketDataClient](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-LiveMarketDataClient)。
