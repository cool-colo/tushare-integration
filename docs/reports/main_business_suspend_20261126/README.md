# 停复牌 DWD 与主营业务 DWS 发布核验

已发布 `default.dwd_stock_suspend` 和 `default.dws_stock_main_business`。
生成 SQL 与完整质量规则结果见本目录；设计规则见 [分层说明](../../main_business_suspend_dwd_dws.md)。

## 结果

- 停复牌 DWD：468,952 行，468,952 个独立事件键；可用日全部 NULL，隔离表 0 行。
- 主营业务 DWS：700,833 行；逐行数据保留校验通过。

| 主营业务日期选择方式 | 行数 | 占比 |
|---|---:|---:|
| 金额匹配候选中取最晚 | 191,141 | 27.27% |
| 无有效报告期候选，日期 NULL | 26,048 | 3.72% |
| 金额无匹配，报告期候选中取最晚 | 483,644 | 69.01% |

原主营业务 DWD 在构建前后均为 700,833 行，可用日全部 NULL，记录哈希汇总一致。
已选日期是普通合并利润表的关联代理，`is_public_date_pit_eligible` 全部为 0。
金额匹配采用已确认的同批次分类汇总依据，不汇总包含层级和总额的明细。

## 验证

- 107 项相关测试通过；兼容性修复后再次通过 6 项主营业务测试。
- 当前 ClickHouse 25.8：停复牌 9 项、主营业务 6 项 BLOCKER 全部 PASS，issue_count 为 0。
- 首次主营业务候选校验发现 25.8 限制 WHERE 中使用 isNotDistinctFrom，发布被拦截。修复 NULL 比较表达式后校验保留候选，再发布；失败记录留在 audit.json 中。
- 发布统计、构建前后指纹、所选版本样例与规则结果见 [audit.json](audit.json)。

## 当前校验模式

初次发布使用 strict，以上历史记录保留。现已按用户要求，将两表的
`quality.table_modes` 显式配置为 `warn_only`，构建示例同步更新。
当前模式继续执行和记录校验，BLOCKER 失败也不阻止发布。
两张正式表已使用 warn_only 重新校验，9 项和 6 项规则均 PASS、issue_count 为 0；
运行 ID 与模式记录在 audit.json 的 `current_validation_mode` 中。
