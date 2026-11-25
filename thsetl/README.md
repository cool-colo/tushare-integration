# 同花顺 thsetl 文件下载客户端

独立安装目录：`thsetl/client/thsetl-2.3.8-linux/`。
部署依据：`docs/other/同花顺数据同步客户端thsetl部署手册_261118.pdf`，
手册版本 1.2，更新日期 2026-11-17。
官方仅提供客户端发行包（JAR、JDK、管理脚本），手册未提供源码仓库。
本安装使用官方 Linux 下载地址：
https://dbpg.51ifind.com/ifind-etl/attachment/client/download/thsetl-linux.zip

下载日期：2026-11-25。客户端版本：2.3.8；内置运行环境：OpenJDK 8u492-b09。
压缩包 SHA-256：`e3e44555a45276a9b9687fd157f84b696815cc2e4c8dee9e743cb2c562111f02`。
这是本地记录的校验值，供应商手册未提供用于验证的校验值。
重新部署时官方同一下载接口两次请求分别返回 HTTP 500、504，未取得新的压缩包。
本次使用当天已成功下载的 `downloads/thsetl-linux.zip`（上述 SHA-256）重新解压部署，
解压时恢复发行包文件权限。客户端 2.3.8 及内置 JDK 与新版手册的目录说明一致；
不能据此确认下载接口是否已更新为其他版本。
重新部署前的实际配置已备份在 `backups/`（权限 600，不提交 Git）。

## 配置与启动

编辑 `client/thsetl-2.3.8-linux/application.yml`，将三个 `REPLACE_WITH_...`
替换为同花顺提供的 UserId、合同账号 CrmCode（userCode）和登录密码。
YAML 单引号字符串内如果含单引号，需写成两个单引号。
该实际配置权限为 600，并与客户端、下载压缩包一起被本目录 `.gitignore` 排除。
`application.example.yml` 是不含凭据的配置模板。

从任何工作目录启动：

```bash
bash /data/flc/code/quant/tushare-integration/thsetl/start.sh
```

启动脚本会检查占位符、目录权限，然后通过 nohup 调用官方后台启动命令，关闭终端后仍继续运行。
启动命令输出保存在客户端的 `logs/launcher.log`，应用日志为 `logs/thsetl.log`。
官方 JVM 参数为 `-XX:+UseG1GC -Xmx2g -Xms2g`，使用包内 JDK。
健康检查仅监听本机 `127.0.0.1:9888`。

```bash
# 状态
bash /data/flc/code/quant/tushare-integration/thsetl/client/thsetl-2.3.8-linux/thsetlctl.sh status
# 健康检查（手册说明成功返回 OK）
curl --fail http://127.0.0.1:9888/health
# 日志
tail -f /data/flc/code/quant/tushare-integration/thsetl/client/thsetl-2.3.8-linux/logs/thsetl.log
# 停止
bash /data/flc/code/quant/tushare-integration/thsetl/client/thsetl-2.3.8-linux/thsetlctl.sh stop
```

## 下载路径与权限

- CSV 全量：`/oss_data/public/transaction/full/{date}/{table}_{date}_{time}_{num}.csv`
- CSV 增量：`/oss_data/public/transaction/inc/{date}/{table}_{date}_{time}_{num}.csv`
- 高频行情 GP（逐笔成交、逐笔委托等）：`/oss_data/public/transaction/gp`，日期目录格式 `yyyy-MM-dd`。

全量和增量分目录保存，保留表名、日期、时间、序列号信息。
CSV 设置 `expireDays: 0`（永久保留）；GP 设置 `expireDays: -1`（不删除）。
官方向导注明 GP 的 `0` 是“不保留”，与 CSV 的 `0` 含义不同。
仅文件下载，数据库同步关闭。GP 已按 transaction 目录用途配置；
若不订阅高频行情，可删除 `ifind.gp` 配置块。
本地配置不选择下载表，实际订阅表、历史范围及全量/增量投递由同花顺服务端及账号权限决定。

手册还要求同花顺为客户端服务器公网 IP 开通白名单。
已按新版手册 3.4 节执行服务连通检查，样例服务返回 HTTP 200，响应含 `pong`：

```bash
curl --fail -H 'content-type:application/json' -X POST -d '{}' \
  https://dbpg.51ifind.com/ifind-etl/server/sample-service/hello
```

这证明样例服务链路可用；账号的登录、订阅权限仍需启动后确认。
登录信息未填写时不启动同步，尚未验证认证成功及实际数据下载。

## 按新版手册验证运行

填写账号并启动后，按手册 5.3 节确认进程运行、日志出现 `Started Application`、
健康检查返回 `OK`、无鉴权报错、下载目录出现文件，并持续观察 10–30 分钟。
后台进程存活不等于登录及下载成功。

如需重新运行官方交互式配置向导（密码不回显），先备份实际配置，再执行：

```bash
bash /data/flc/code/quant/tushare-integration/thsetl/client/thsetl-2.3.8-linux/thsetlctl.sh --lang=zh config
```

向导会覆盖配置；数据库选 `n`，文件下载和 GP 选 `y`，路径及保留天数按上文填写。
手工编辑配置后必须重启生效。

## 手册与发行包的配置差异

新版附录 A 列出 `ifind.gp.enabled`，模板已显式设为 `true`；
实际官方向导启用 GP 时仅输出 `baseDir/dateFormat/expireDays`，未输出 enabled。
配置同时保留这三项，GP 的保留天数采用手册明确的 `-1`。

手册 6.2 声称日志默认保留 30 天、总量上限 10GB，
但当前发行包 `log4j2.xml` 未配置按时间或总大小删除归档的动作；
`DefaultRolloverStrategy max="30"` 不能证明该保留天数和总量限制成立。
实际配置为按天与 100MB 滚动压缩，运维时应检查日志磁盘用量。
