#!/usr/bin/env bash
set -euo pipefail
thsetl_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
client_dir="$thsetl_dir/client/thsetl-2.3.8-linux"
config_file="$client_dir/application.yml"
if [[ ! -f "$config_file" ]]; then
  echo "缺少配置文件：$config_file" >&2
  exit 1
fi
if rg -q 'REPLACE_WITH_' "$config_file"; then
  echo "请先填写 $config_file 中的 userId、userCode 和 password。" >&2
  exit 1
fi
chmod 600 "$config_file"
for download_dir in /oss_data/public/transaction/{full,inc,gp}; do
  mkdir -p "$download_dir"
  if [[ ! -w "$download_dir" ]]; then
    echo "下载目录不可写：$download_dir" >&2
    exit 1
  fi
done
# 官方脚本后台派生 Java；让它继承忽略 SIGHUP，关闭终端后继续下载。
mkdir -p "$client_dir/logs"
nohup bash "$client_dir/thsetlctl.sh" start >> "$client_dir/logs/launcher.log" 2>&1 < /dev/null
echo "启动命令已执行；请查看 $client_dir/logs/launcher.log 和 thsetl.log 确认运行状态。"
