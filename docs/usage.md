# 使用方式

- 参考[配置文件](settings.md)编写好配置文件
- 使用python main.py启动主程序

## 命令

### query

#### list 列举spider清单

`python main.py query list [OPTIONS]`

### run

#### spider 运行爬虫

`python main.py run spider [OPTIONS] SPIDER_NAME`

该命令将运行对应的spider  
spider_name基于正则全文匹配，例如stock/basic/*将运行所有stock/basic下的spider

#### job 运行任务

`python main.py run job [OPTIONS] JOB_NAME`

该命令将从jobs.yaml文件中找到对应的job，然后运行该job下的所有spider

## 公募基金持仓

`fund/portfolio/fund_portfolio` 采集公募基金季度股票持仓，并保留ODS最新数据和原始版本。
使用 `python main.py run job fund/portfolio --update-type full` 采集后，运行
`python main.py dwd sync dwd_fund_portfolio --validation-mode strict` 发布DWD。
公告可用日依赖已采集的SSE交易日历，完整口径和运行说明见[基金持仓](fund_portfolio.md)。

## 使用K8S

项目提供了基于Helm的部署模板，编写好values.yaml后直接部署到集群即可，会自动创建CronJob用于定时更新

## 使用Docker

### 安装Docker

```shell
yum install -y yum-utils
yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
yum install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl start docker
```

### 部署Clickhouse

#### 拉取镜像

```shell
docker pull clickhouse/clickhouse-server:23.6.2.18-alpine
```

#### 创建数据目录

```shell
mkdir -p /data0/clickhouse/data
```

#### 创建配置文件目录（可选）

```shell
mkdir -p /data0/clickhouse/config
```

#### 启动数据库

如果不需要挂载配置文件删除下列命令中的`-v /data0/clickhouse/config:/etc/clickhouse-server/config.d`

```shell
docker run -d --net=host -v /data0/clickhouse/data:/var/lib/clickhouse -v /data0/clickhouse/config:/etc/clickhouse-server/config.d --name clickhouse-server --ulimit nofile=262144:262144 clickhouse/clickhouse-server:23.6.2.18-alpine
```

### tushare-integration

#### 创建配置文件目录

```shell
mkdir -p /data0/tushare-integration/config
```

#### 编写jobs.yaml和config.yaml

```yaml
# jobs.yaml
cronjob:
  - cron_expr: Unsupported
    name: stock/basic
    spiders:
      - name: stock/basic/stock_basic
      - name: stock/basic/namechange
      - name: stock/basic/hs_const
      - name: stock/basic/trade_cal
      - name: stock/basic/stock_company
      - name: stock/basic/stk_managers
      - name: stock/basic/stk_rewards
      - name: stock/basic/new_share
      - name: stock/basic/bak_basic
  - cron_expr: Unsupported
    name: stock/financial
    spiders:
      - name: stock/financial/balancesheet
      - name: stock/financial/cashflow
      - name: stock/financial/income
      - name: stock/financial/express
      - name: stock/financial/forecast
      - name: stock/financial/dividend
      - name: stock/financial/fina_indicator
      - name: stock/financial/fina_audit
      - name: stock/financial/fina_mainbz
      - name: stock/financial/disclosure_date
  - cron_expr: Unsupported
    name: stock/market
    spiders:
      - name: stock/market/margin
      - name: stock/market/margin_detail
      - name: stock/market/margin_target
      - name: stock/market/top10_holders
      - name: stock/market/top10_floatholders
      - name: stock/market/top_list
      - name: stock/market/top_inst
      - name: stock/market/pledge_stat
      - name: stock/market/pledge_detail
      - name: stock/market/repurchase
      - name: stock/market/concept
      - name: stock/market/concept_detail
      - name: stock/market/block_trade
      - name: stock/market/stk_holdernumber
      - name: stock/market/stk_holdertrade
  - cron_expr: Unsupported
    name: stock/quotes
    spiders:
      - name: stock/quotes/daily
      - name: stock/quotes/weekly
      - name: stock/quotes/monthly
      - name: stock/quotes/adj_factor
      - name: stock/quotes/suspend_d
      - name: stock/quotes/hsgt_top10
      - name: stock/quotes/moneyflow
      - name: stock/quotes/moneyflow_hsgt
      - name: stock/quotes/stk_limit
      - name: stock/quotes/daily_basic
      - name: stock/quotes/ggt_top10
      - name: stock/quotes/ggt_daily
      - name: stock/quotes/bak_daily
  - cron_expr: Unsupported
    name: stock/special
    spiders:
      - name: stock/special/report_rc
      - name: stock/special/cyq_perf
      - name: stock/special/stk_factor
      - name: stock/special/ccass_hold
      - name: stock/special/ccass_hold_detail
      - name: stock/special/hk_hold
      - name: stock/special/limit_list_d
      - name: stock/special/stk_surv
      - name: stock/special/broker_recommend

```

`jobs.yaml` 中的 spider 可以增加 `update_type: full` 标记全量任务；未标记时默认作为 `incremental` 日常增量任务。运行时可以按维度过滤：

```shell
python main.py run job stock/quotes --update-type incremental
python main.py run job stock/quotes --update-type full
```

仓库中的 `scripts/run_daily_market_jobs.sh` 默认运行 `UPDATE_TYPE=incremental`，可在 crontab 中每天执行；周度或月度全量任务可使用：

```shell
UPDATE_TYPE=full scripts/run_daily_market_jobs.sh
```

`fund/portfolio` 及其 `dwd_fund_portfolio` 同步只在 `UPDATE_TYPE=full` 时调度；工作日的 `UPDATE_TYPE=incremental` 批次不再运行该长任务。

### 按指定日期重新采集

`run replay` 直接请求指定日期，绕过日频采集的最新日期与已有日期检查，用于接收 Tushare 的历史修订。
支持使用标准 `DailySpider` 请求和解析流程且具有明确完整性规则的接口；需要传精确 spider 名称。
全市场补采中，`stock/quotes/adj_factor`、`stock/special/stk_factor` 和 `fund/quotes/fund_adj` 使用分页；
`stock/quotes/daily`、`stock/quotes/daily_basic`、`stock/quotes/stk_limit` 和 `fund/quotes/fund_daily`
使用接口专属返回条数上限检查。其它标准日频接口仅在业务主键为股票代码＋日期时支持 `--ts-code`
单证券补采；没有全市场完整性规则或使用自定义采集流程的接口会报错。

先查看请求计划；`--dry-run` 不访问数据接口或数据库：

```shell
python main.py run replay stock/quotes/adj_factor \
  --trade-date 2026-10-23 --trade-date 2026-10-26 --trade-date 2026-10-27 --dry-run
```

执行时去掉 `--dry-run`。按日期请求全市场数据，也可以通过 `--ts-code` 限定单只股票：

```shell
python main.py run replay stock/quotes/adj_factor --trade-date 20261026 --ts-code 688585.SH
```

日期支持 `YYYY-MM-DD` 和 `YYYYMMDD`，可重复传入；重复日期会去重并按日期排序，未来日期会报错。
非交易日或源端没有数据时命令报错并保留已有记录，不自动选择相邻日期。重采采用现有的请求、重试和
写入管道：追加原始采集记录到 `adj_factor_raw`，更新 `adj_factor`，记录真实入库时间、批次和记录哈希。
它不删除旧原始版本，不执行其它依赖 spider，不发送外部通知，也不自动重建 DWD/DWS。

全市场分页接口使用 `limit`/`offset` 连续请求；即使源端不返回 `has_more`，满页也会继续请求，直到
收到短页或成功的空尾页。整个日期收齐并验证后才提交一次写入；重复/重叠页、超出请求页大小、
分页失败或达到分页安全上限时，该日期不写入。`--dry-run` 显示第一页请求参数，后续页在执行时生成。
未分页接口的限额分别为 `daily`/`daily_basic` 6000 条、`stk_limit` 5800 条、`fund_daily` 5000 条；
达到或超过限额就报错并阻止该响应写入，不能将满额响应认作完整修订。需要时使用 `--ts-code` 分证券补采。

空响应、截断响应、字段缺失、日期/指定股票不符、重复业务主键和无效复权因子在写入前报错。
若多日期任务部分失败，已成功日期的写入会保留；解决失败原因后可以重新执行相同日期。
成功输出包含批次、完成日期数量及接收行数。反复执行会增加原始采集记录；DWD 构建逻辑合并相邻哈希
相同的观测，保持有实际变化的版本区间。

完成补采后，可以单独更新复权因子标准层：

```shell
python main.py dwd sync dwd_stock_adj_factor --validation-mode strict
```

随后更新实际引用该因子的 DWS 与复权计算结果。补采日期是业务日期，新增版本的系统时间是实际入库
时间；不能把今天补采的修订标记为历史上已经入库的数据。

### 股票日线提前批

`pre_job.yaml` 独立维护股票日线行情所需的 `stock_basic`、`trade_cal` 和 `daily` 三个增量 spider。提前批脚本会在采集成功后立即同步 `dwd_stock_eod_price`：

```shell
scripts/run_pre_market_jobs.sh
```

请由外部调度器先运行提前批，再运行 `scripts/run_daily_market_jobs.sh`。两个脚本默认共享锁文件，避免并发执行；可用 `PRE_JOBS_FILE`（或 `JOBS_FILE`）、`CONFIG_FILE`、镜像和日志相关环境变量覆盖默认配置。

```yaml
# config.yaml
# TUSHARE相关配置
tushare_url: https://api.tushare.pro
tushare_point: 2000
tushare_token: ''
tushare_rate_limit_ratio: 0.9

database:
  # 数据库配置
  db_type: 'clickhouse'
  host: '127.0.0.1'
  port: '8123'
  user: 'default'
  password: ''
  db_name: 'default'
  template_params: { }

reporters: [ ]
#  - "tushare_integration.reporters.FeishuWebHookReporter"
#  - "tushare_integration.reporters.DingTalkWebHookReporter"

# 飞书Webhook配置
feishu_webhook: ""
# 钉钉Webhook配置
dingtalk_webhook: ""

# Scrapy配置
bot_name: tushare_integration
concurrent_requests: 1
concurrent_items: 100

downloader_middlewares:
  scrapy.downloadermiddlewares.retry.RetryMiddleware: null
  tushare_integration.middlewares.TushareRetryDownloaderMiddleware: 543

item_pipelines:
  tushare_integration.pipelines.TushareIntegrationFillNAPipeline: 298
  tushare_integration.pipelines.TransformDTypePipeline: 299
  tushare_integration.pipelines.TushareIntegrationDataPipeline: 300
  tushare_integration.pipelines.RecordLogPipeline: 301


# 重试配置
# Tushare的频次限制是一分钟为周期，重试只要大于这个周期理论上不会有任何问题
retry_enabled: true
retry_delay: 10
retry_times: 6

spider_modules:
  - "tushare_integration.spiders"

closespider_errorcount: 1
```

#### 手动运行任务

```shell
docker run -d --net=host -v /data0/tushare-integration/config/jobs.yaml:/code/app/jobs.yaml -v /data0/tushare-integration/config/config.yaml:/code/app/config.yaml zhangbc/tushare-integration:0.0.3 python main.py run job stock/basic 
```

#### 配置定时任务

配置定时任务时请避免定时任务同时启动，采集服务并发情况下可能会出现采集的数据异常

```shell
crontab -e
```

### 使用Crontab定时运行Job

将jobs.yaml和config.yaml文件放置在同一目录下，然后在crontab中添加上述命令
