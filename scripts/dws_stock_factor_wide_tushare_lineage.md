# dws_stock_factor_wide Tushare 原始字段来源说明

本文档用于业务对齐，说明 `dws_stock_factor_wide` 每个字段追溯到的 Tushare 原始 API/字段，以及宽表中额外加工字段的计算口径。

## 口径说明

- 文档刻意跳过 DWD 字段名，直接写 Tushare 原始 API 与原始字段。
- `PIT/as-of` 只表示按公告日可见性选择历史版本，不作为业务计算逻辑展开；字段表中的计算说明只保留会改变业务数值含义的加工。
- 财务历史窗口字段后缀约定：`lyr_N` 表示最近年度报告向前第 N 期；`mrq_N` 表示最近季度报告向前第 N 期；`lf` 等同最新报告期；`ttm_N` 表示从第 N 期开始连续 4 个季度的 TTM 窗口。
- TTM 聚合规则来自当前实现：利润表与现金流量表默认求和；资产负债表默认求平均；财务指标默认求平均，但 `ebit`、`ebitda`、`extra_item`、`fcfe`、`fcff`、`profit_dedt` 求和。
- 利润表、现金流量表以及部分财务指标的季度口径会先做单季化：Q1 取当期值，Q2-Q4 取当期累计值减上一季度累计值；缺上一季度时为空。
- `ev_lyr`、`ev_no_cash_lyr` 当前公式一致；`ev_ttm`、`ev_no_cash_ttm` 当前公式一致，这是代码实现现状。
- 当前本地 Tushare schema 中 `bak_daily.buying` 注释为“内盘”、`bak_daily.selling` 注释为“外盘”，但宽表字段注释分别写为“外盘/内盘”；字段来源按代码实现原样记录，建议业务侧确认注释口径。

## 字段来源明细

| dws_stock_factor_wide字段名 | 注释 | Tushare原始表/API | Tushare原始字段 | Tushare字段注释 | 计算逻辑说明 |
|---|---|---|---|---|---|
| `instrument_id` | 统一证券ID | daily（日线行情） | ts_code | ts_code: 股票代码 | 由 Tushare 股票代码加工为统一证券ID：concat('stock:', ts_code)。 |
| `instrument_type` | 证券类型 | 无直接 Tushare 原始表 | - | - | 固定赋值为 stock。 |
| `exchange` | 交易所 | daily（日线行情） | ts_code | ts_code: 股票代码 | 由 ts_code 后缀拆分得到交易所，例如 000001.SZ -> SZ。 |
| `source_code` | 源侧证券代码 | daily（日线行情） | ts_code | ts_code: 股票代码 | 保留源侧股票代码 ts_code。 |
| `event_date` | 业务归属日期 | daily（日线行情） | trade_date | trade_date: 交易日期 | 业务归属日期取日线行情交易日期。 |
| `trade_date` | 交易日期 | daily（日线行情） | trade_date | trade_date: 交易日期 | 交易日期取日线行情交易日期。 |
| `available_trade_date` | 最早可用交易日 | 无直接 Tushare 原始表 | - | - | PIT可见日期聚合字段：取行情、估值、扩展行情、财报、北向、融资融券、筹码等已关联来源的可用交易日最大值；财报类来源由 ann_date 映射到下一交易日。 |
| `open` | 开盘价 | daily（日线行情） | open | open: 开盘价 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `high` | 最高价 | daily（日线行情） | high | high: 最高价 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `low` | 最低价 | daily（日线行情） | low | low: 最低价 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `close` | 收盘价 | daily（日线行情） | close | close: 收盘价 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `pre_close` | 昨收价 | daily（日线行情） | pre_close | pre_close: 昨收价 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `pct_chg` | 涨跌幅 | daily（日线行情） | pct_chg | pct_chg: 涨跌幅 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `vol` | 成交量 | daily（日线行情） | vol | vol: 成交量 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `amount` | 成交额 | daily（日线行情） | amount | amount: 成交额 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `adj_factor` | 复权因子 | adj_factor（复权因子） | adj_factor | adj_factor: 复权因子 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `buying` | 外盘 | bak_daily（备用行情） | buying | buying: 内盘 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `selling` | 内盘 | bak_daily（备用行情） | selling | selling: 外盘 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `vol_ratio` | 量比 | bak_daily（备用行情） | vol_ratio | vol_ratio: 量比 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `turn_over` | 换手率 | bak_daily（备用行情） | turn_over | turn_over: 换手率 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `swing` | 振幅 | bak_daily（备用行情） | swing | swing: 振幅 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `avg_price` | 均价 | bak_daily（备用行情） | avg_price | avg_price: 平均价 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `strength` | 强弱度 | bak_daily（备用行情） | strength | strength: 强弱度(%) | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `activity` | 活跃度 | bak_daily（备用行情） | activity | activity: 活跃度(%) | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `avg_turnover` | 笔换手 | bak_daily（备用行情） | avg_turnover | avg_turnover: 笔换手 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `attack` | 攻击波 | bak_daily（备用行情） | attack | attack: 攻击波(%) | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `pe_ttm` | 市盈率TTM | daily_basic（每日指标） | pe_ttm | pe_ttm: 市盈率（TTM） | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `pb` | 市净率 | daily_basic（每日指标） | pb | pb: 市净率（总市值/净资产） | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `ps_ttm` | 市销率TTM | daily_basic（每日指标） | ps_ttm | ps_ttm: 市销率（TTM） | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `dv_ttm` | 股息率TTM | daily_basic（每日指标） | dv_ttm | dv_ttm: 股息率（TTM） （%） | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `turnover_rate_f` | 自由流通股换手率 | daily_basic（每日指标） | turnover_rate_f | turnover_rate_f: 换手率(自由流通股) | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `volume_ratio_db` | 量比每日指标 | daily_basic（每日指标） | volume_ratio | volume_ratio: 量比 | 字段重命名：daily_basic.volume_ratio -> volume_ratio_db。 |
| `circ_mv` | 流通市值 | daily_basic（每日指标） | circ_mv | circ_mv: 流通市值 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `total_mv` | 总市值 | daily_basic（每日指标） | total_mv | total_mv: 总市值 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `total_share` | 总股本 | daily_basic（每日指标） | total_share | total_share: 总股本 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `float_share` | 流通股本 | daily_basic（每日指标） | float_share | float_share: 流通股本 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `free_share` | 自由流通股本 | daily_basic（每日指标） | free_share | free_share: 自由流通股本 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `roe` | 净资产收益率 | fina_indicator（财务指标数据） | roe | roe: 净资产收益率 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `roa` | 总资产报酬率 | fina_indicator（财务指标数据） | roa | roa: 总资产报酬率 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `roic` | 投入资本回报率 | fina_indicator（财务指标数据） | roic | roic: 投入资本回报率 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `grossprofit_margin` | 销售毛利率 | fina_indicator（财务指标数据） | grossprofit_margin | grossprofit_margin: 销售毛利率 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `netprofit_margin` | 销售净利率 | fina_indicator（财务指标数据） | netprofit_margin | netprofit_margin: 销售净利率 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `or_yoy` | 营业收入同比增长率 | fina_indicator（财务指标数据） | or_yoy | or_yoy: 营业收入同比增长率(%) | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `netprofit_yoy` | 归母净利润同比增长率 | fina_indicator（财务指标数据） | netprofit_yoy | netprofit_yoy: 归属母公司股东的净利润同比增长率(%) | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `op_yoy` | 营业利润同比增长率 | fina_indicator（财务指标数据） | op_yoy | op_yoy: 营业利润同比增长率(%) | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `basic_eps_yoy` | 基本每股收益同比增长率 | fina_indicator（财务指标数据） | basic_eps_yoy | basic_eps_yoy: 基本每股收益同比增长率(%) | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `q_roe` | 单季度净资产收益率 | fina_indicator（财务指标数据） | q_roe | q_roe: 净资产收益率(单季度) | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `q_gsprofit_margin` | 单季度销售毛利率 | fina_indicator（财务指标数据） | q_gsprofit_margin | q_gsprofit_margin: 销售毛利率(单季度) | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `q_netprofit_yoy` | 单季度归母净利润同比增长率 | fina_indicator（财务指标数据） | q_netprofit_yoy | q_netprofit_yoy: 归属母公司股东的净利润同比增长率(%)(单季度) | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `q_sales_yoy` | 单季度营业收入同比增长率 | fina_indicator（财务指标数据） | q_sales_yoy | q_sales_yoy: 营业收入同比增长率(%)(单季度) | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `ocf_to_or` | 经营现金流营业收入比 | fina_indicator（财务指标数据） | ocf_to_or | ocf_to_or: 经营活动产生的现金流量净额/营业收入 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `ocf_to_profit` | 经营现金流营业利润比 | fina_indicator（财务指标数据） | ocf_to_profit | ocf_to_profit: 经营活动产生的现金流量净额／营业利润 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `debt_to_assets` | 资产负债率 | fina_indicator（财务指标数据） | debt_to_assets | debt_to_assets: 资产负债率 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `current_ratio` | 流动比率 | fina_indicator（财务指标数据） | current_ratio | current_ratio: 流动比率 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `eps` | 基本每股收益 | fina_indicator（财务指标数据） | eps | eps: 基本每股收益 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `bps` | 每股净资产 | fina_indicator（财务指标数据） | bps | bps: 每股净资产 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `ocfps` | 每股经营现金流 | fina_indicator（财务指标数据） | ocfps | ocfps: 每股经营活动产生的现金流量净额 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `rd_exp` | 研发费用 | fina_indicator（财务指标数据） | rd_exp | rd_exp: 研发费用 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `assets_turn` | 总资产周转率 | fina_indicator（财务指标数据） | assets_turn | assets_turn: 总资产周转率 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `inv_turn` | 存货周转率 | fina_indicator（财务指标数据） | inv_turn | inv_turn: 存货周转率 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `ar_turn` | 应收账款周转率 | fina_indicator（财务指标数据） | ar_turn | ar_turn: 应收账款周转率 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `total_revenue` | 营业总收入 | income（利润表） | total_revenue | total_revenue: 营业总收入 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `revenue` | 营业收入 | income（利润表） | revenue | revenue: 营业收入 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `n_income` | 净利润 | income（利润表） | n_income | n_income: 净利润(含少数股东损益) | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `n_income_attr_p` | 归属于母公司所有者的净利润 | income（利润表） | n_income_attr_p | n_income_attr_p: 净利润(不含少数股东损益) | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `compr_inc_attr_p` | 归属于母公司所有者的综合收益总额 | income（利润表） | compr_inc_attr_p | compr_inc_attr_p: 归属于母公司(或股东)的综合收益总额 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `compr_inc_attr_m_s` | 归属于少数股东的综合收益总额 | income（利润表） | compr_inc_attr_m_s | compr_inc_attr_m_s: 归属于少数股东的综合收益总额 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `oper_cost` | 营业成本 | income（利润表） | oper_cost | oper_cost: 减:营业成本 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `total_profit` | 利润总额 | income（利润表） | total_profit | total_profit: 利润总额 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `ebit` | 息税前利润 | fina_indicator（财务指标数据） | ebit | ebit: 息税前利润 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `ebitda` | 息税折旧摊销前利润 | fina_indicator（财务指标数据） | ebitda | ebitda: 息税折旧摊销前利润 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `admin_exp` | 管理费用 | income（利润表） | admin_exp | admin_exp: 减:管理费用 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `sell_exp` | 销售费用 | income（利润表） | sell_exp | sell_exp: 减:销售费用 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `fin_exp` | 财务费用 | income（利润表） | fin_exp | fin_exp: 减:财务费用 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `income_tax` | 所得税费用 | income（利润表） | income_tax | income_tax: 所得税费用 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `total_opcost` | 营业总成本 | income（利润表） | total_opcost | total_opcost: 营业总成本2 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `total_assets` | 资产总计 | balancesheet（资产负债表） | total_assets | total_assets: 资产总计 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `total_liab` | 负债合计 | balancesheet（资产负债表） | total_liab | total_liab: 负债合计 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `total_cur_liab` | 流动负债合计 | balancesheet（资产负债表） | total_cur_liab | total_cur_liab: 流动负债合计 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `total_cur_assets` | 流动资产合计 | balancesheet（资产负债表） | total_cur_assets | total_cur_assets: 流动资产合计 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `money_cap` | 货币资金 | balancesheet（资产负债表） | money_cap | money_cap: 货币资金 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `total_hldr_eqy_exc_min_int` | 股东权益合计(不含少数股东权益) | balancesheet（资产负债表） | total_hldr_eqy_exc_min_int | total_hldr_eqy_exc_min_int: 股东权益合计(不含少数股东权益) | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `c_inf_fr_operate_a` | 经营活动现金流入小计 | cashflow（现金流量表） | c_inf_fr_operate_a | c_inf_fr_operate_a: 经营活动现金流入小计 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `st_cash_out_act` | 经营活动现金流出小计 | cashflow（现金流量表） | st_cash_out_act | st_cash_out_act: 经营活动现金流出小计 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `stot_out_inv_act` | 投资活动现金流出小计 | cashflow（现金流量表） | stot_out_inv_act | stot_out_inv_act: 投资活动现金流出小计 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `stot_inflows_inv_act` | 投资活动现金流入小计 | cashflow（现金流量表） | stot_inflows_inv_act | stot_inflows_inv_act: 投资活动现金流入小计 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `stot_cash_in_fnc_act` | 筹资活动现金流入小计 | cashflow（现金流量表） | stot_cash_in_fnc_act | stot_cash_in_fnc_act: 筹资活动现金流入小计 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `stot_cashout_fnc_act` | 筹资活动现金流出小计 | cashflow（现金流量表） | stot_cashout_fnc_act | stot_cashout_fnc_act: 筹资活动现金流出小计 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `bond_payable_ttm_0` | 应付债券ttm_0 | balancesheet（资产负债表） | bond_payable | bond_payable: 应付债券 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `bond_payable_ttm_1` | 应付债券ttm_1 | balancesheet（资产负债表） | bond_payable | bond_payable: 应付债券 | TTM窗口口径，report_offset 从 1 到 4 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `fix_assets_lyr_0` | 固定资产lyr_0 | balancesheet（资产负债表） | fix_assets | fix_assets: 固定资产 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `fix_assets_lyr_1` | 固定资产lyr_1 | balancesheet（资产负债表） | fix_assets | fix_assets: 固定资产 | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `fix_assets_ttm_0` | 固定资产ttm_0 | balancesheet（资产负债表） | fix_assets | fix_assets: 固定资产 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `fix_assets_ttm_1` | 固定资产ttm_1 | balancesheet（资产负债表） | fix_assets | fix_assets: 固定资产 | TTM窗口口径，report_offset 从 1 到 4 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `lt_borr_ttm_0` | 长期借款ttm_0 | balancesheet（资产负债表） | lt_borr | lt_borr: 长期借款 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `lt_borr_ttm_1` | 长期借款ttm_1 | balancesheet（资产负债表） | lt_borr | lt_borr: 长期借款 | TTM窗口口径，report_offset 从 1 到 4 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `money_cap_lyr_0` | 货币资金lyr_0 | balancesheet（资产负债表） | money_cap | money_cap: 货币资金 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `money_cap_lyr_1` | 货币资金lyr_1 | balancesheet（资产负债表） | money_cap | money_cap: 货币资金 | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `money_cap_mrq_0` | 货币资金mrq_0 | balancesheet（资产负债表） | money_cap | money_cap: 货币资金 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `money_cap_ttm_0` | 货币资金ttm_0 | balancesheet（资产负债表） | money_cap | money_cap: 货币资金 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `money_cap_ttm_1` | 货币资金ttm_1 | balancesheet（资产负债表） | money_cap | money_cap: 货币资金 | TTM窗口口径，report_offset 从 1 到 4 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `non_cur_liab_due_1y_lyr_0` | 一年内到期的非流动负债lyr_0 | balancesheet（资产负债表） | non_cur_liab_due_1y | non_cur_liab_due_1y: 一年内到期的非流动负债 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `non_cur_liab_due_1y_lyr_1` | 一年内到期的非流动负债lyr_1 | balancesheet（资产负债表） | non_cur_liab_due_1y | non_cur_liab_due_1y: 一年内到期的非流动负债 | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `non_cur_liab_due_1y_ttm_0` | 一年内到期的非流动负债ttm_0 | balancesheet（资产负债表） | non_cur_liab_due_1y | non_cur_liab_due_1y: 一年内到期的非流动负债 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `non_cur_liab_due_1y_ttm_1` | 一年内到期的非流动负债ttm_1 | balancesheet（资产负债表） | non_cur_liab_due_1y | non_cur_liab_due_1y: 一年内到期的非流动负债 | TTM窗口口径，report_offset 从 1 到 4 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `notes_payable_lyr_0` | 应付票据lyr_0 | balancesheet（资产负债表） | notes_payable | notes_payable: 应付票据 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `notes_payable_lyr_1` | 应付票据lyr_1 | balancesheet（资产负债表） | notes_payable | notes_payable: 应付票据 | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `notes_payable_ttm_0` | 应付票据ttm_0 | balancesheet（资产负债表） | notes_payable | notes_payable: 应付票据 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `notes_payable_ttm_1` | 应付票据ttm_1 | balancesheet（资产负债表） | notes_payable | notes_payable: 应付票据 | TTM窗口口径，report_offset 从 1 到 4 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `st_borr_ttm_0` | 短期借款ttm_0 | balancesheet（资产负债表） | st_borr | st_borr: 短期借款 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `st_borr_ttm_1` | 短期借款ttm_1 | balancesheet（资产负债表） | st_borr | st_borr: 短期借款 | TTM窗口口径，report_offset 从 1 到 4 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `total_assets_lyr_0` | 总资产lyr_0 | balancesheet（资产负债表） | total_assets | total_assets: 资产总计 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `total_assets_lyr_1` | 总资产lyr_1 | balancesheet（资产负债表） | total_assets | total_assets: 资产总计 | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `total_assets_mrq_0` | 总资产mrq_0 | balancesheet（资产负债表） | total_assets | total_assets: 资产总计 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `total_assets_mrq_4` | 总资产mrq_4 | balancesheet（资产负债表） | total_assets | total_assets: 资产总计 | 最近季度报告口径，report_offset=4；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `total_assets_ttm_0` | 总资产ttm_0 | balancesheet（资产负债表） | total_assets | total_assets: 资产总计 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `total_assets_ttm_4` | 总资产ttm_4 | balancesheet（资产负债表） | total_assets | total_assets: 资产总计 | TTM窗口口径，report_offset 从 4 到 7 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `total_cur_assets_lyr_0` | 流动资产合计lyr_0 | balancesheet（资产负债表） | total_cur_assets | total_cur_assets: 流动资产合计 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `total_cur_assets_lyr_1` | 流动资产合计lyr_1 | balancesheet（资产负债表） | total_cur_assets | total_cur_assets: 流动资产合计 | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `total_cur_assets_ttm_0` | 流动资产合计ttm_0 | balancesheet（资产负债表） | total_cur_assets | total_cur_assets: 流动资产合计 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `total_cur_assets_ttm_1` | 流动资产合计ttm_1 | balancesheet（资产负债表） | total_cur_assets | total_cur_assets: 流动资产合计 | TTM窗口口径，report_offset 从 1 到 4 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `total_cur_liab_lyr_0` | 流动负债合计lyr_0 | balancesheet（资产负债表） | total_cur_liab | total_cur_liab: 流动负债合计 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `total_cur_liab_lyr_1` | 流动负债合计lyr_1 | balancesheet（资产负债表） | total_cur_liab | total_cur_liab: 流动负债合计 | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `total_cur_liab_ttm_0` | 流动负债合计ttm_0 | balancesheet（资产负债表） | total_cur_liab | total_cur_liab: 流动负债合计 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `total_cur_liab_ttm_1` | 流动负债合计ttm_1 | balancesheet（资产负债表） | total_cur_liab | total_cur_liab: 流动负债合计 | TTM窗口口径，report_offset 从 1 到 4 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `total_hldr_eqy_exc_min_int_lyr_0` | 股东权益合计(不含少数股东权益)lyr_0 | balancesheet（资产负债表） | total_hldr_eqy_exc_min_int | total_hldr_eqy_exc_min_int: 股东权益合计(不含少数股东权益) | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `total_hldr_eqy_exc_min_int_lyr_1` | 股东权益合计(不含少数股东权益)lyr_1 | balancesheet（资产负债表） | total_hldr_eqy_exc_min_int | total_hldr_eqy_exc_min_int: 股东权益合计(不含少数股东权益) | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `total_hldr_eqy_exc_min_int_mrq_0` | 股东权益合计(不含少数股东权益)mrq_0 | balancesheet（资产负债表） | total_hldr_eqy_exc_min_int | total_hldr_eqy_exc_min_int: 股东权益合计(不含少数股东权益) | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `total_hldr_eqy_exc_min_int_mrq_4` | 股东权益合计(不含少数股东权益)mrq_4 | balancesheet（资产负债表） | total_hldr_eqy_exc_min_int | total_hldr_eqy_exc_min_int: 股东权益合计(不含少数股东权益) | 最近季度报告口径，report_offset=4；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `total_hldr_eqy_exc_min_int_ttm_0` | 股东权益合计(不含少数股东权益)ttm_0 | balancesheet（资产负债表） | total_hldr_eqy_exc_min_int | total_hldr_eqy_exc_min_int: 股东权益合计(不含少数股东权益) | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `total_hldr_eqy_exc_min_int_ttm_4` | 股东权益合计(不含少数股东权益)ttm_4 | balancesheet（资产负债表） | total_hldr_eqy_exc_min_int | total_hldr_eqy_exc_min_int: 股东权益合计(不含少数股东权益) | TTM窗口口径，report_offset 从 4 到 7 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `total_hldr_eqy_inc_min_int_lyr_0` | 股东权益合计(含少数股东权益)lyr_0 | balancesheet（资产负债表） | total_hldr_eqy_inc_min_int | total_hldr_eqy_inc_min_int: 股东权益合计(含少数股东权益) | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `total_hldr_eqy_inc_min_int_lyr_1` | 股东权益合计(含少数股东权益)lyr_1 | balancesheet（资产负债表） | total_hldr_eqy_inc_min_int | total_hldr_eqy_inc_min_int: 股东权益合计(含少数股东权益) | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `total_hldr_eqy_inc_min_int_ttm_0` | 股东权益合计(含少数股东权益)ttm_0 | balancesheet（资产负债表） | total_hldr_eqy_inc_min_int | total_hldr_eqy_inc_min_int: 股东权益合计(含少数股东权益) | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `total_hldr_eqy_inc_min_int_ttm_4` | 股东权益合计(含少数股东权益)ttm_4 | balancesheet（资产负债表） | total_hldr_eqy_inc_min_int | total_hldr_eqy_inc_min_int: 股东权益合计(含少数股东权益) | TTM窗口口径，report_offset 从 4 到 7 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `total_liab_lyr_0` | 负债合计lyr_0 | balancesheet（资产负债表） | total_liab | total_liab: 负债合计 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `total_liab_mrq_0` | 负债合计mrq_0 | balancesheet（资产负债表） | total_liab | total_liab: 负债合计 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `total_liab_ttm_0` | 负债合计ttm_0 | balancesheet（资产负债表） | total_liab | total_liab: 负债合计 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `amort_intang_assets_lyr_0` | 无形资产摊销lyr_0 | cashflow（现金流量表） | amort_intang_assets | amort_intang_assets: 无形资产摊销 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `amort_intang_assets_ttm_0` | 无形资产摊销ttm_0 | cashflow（现金流量表） | amort_intang_assets | amort_intang_assets: 无形资产摊销 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `depr_fa_coga_dpba_lyr_0` | 固定资产折旧等lyr_0 | cashflow（现金流量表） | depr_fa_coga_dpba | depr_fa_coga_dpba: 固定资产折旧、油气资产折耗、生产性生物资产折旧 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `depr_fa_coga_dpba_ttm_0` | 固定资产折旧等ttm_0 | cashflow（现金流量表） | depr_fa_coga_dpba | depr_fa_coga_dpba: 固定资产折旧、油气资产折耗、生产性生物资产折旧 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `n_cash_flows_fnc_act_lyr_0` | 筹资活动产生的现金流量净额lyr_0 | cashflow（现金流量表） | n_cash_flows_fnc_act | n_cash_flows_fnc_act: 筹资活动产生的现金流量净额 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `n_cash_flows_fnc_act_lyr_1` | 筹资活动产生的现金流量净额lyr_1 | cashflow（现金流量表） | n_cash_flows_fnc_act | n_cash_flows_fnc_act: 筹资活动产生的现金流量净额 | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `n_cash_flows_fnc_act_ttm_0` | 筹资活动产生的现金流量净额ttm_0 | cashflow（现金流量表） | n_cash_flows_fnc_act | n_cash_flows_fnc_act: 筹资活动产生的现金流量净额 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `n_cash_flows_fnc_act_ttm_4` | 筹资活动产生的现金流量净额ttm_4 | cashflow（现金流量表） | n_cash_flows_fnc_act | n_cash_flows_fnc_act: 筹资活动产生的现金流量净额 | TTM窗口口径，report_offset 从 4 到 7 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `n_cashflow_act_lyr_0` | 经营活动产生的现金流量净额lyr_0 | cashflow（现金流量表） | n_cashflow_act | n_cashflow_act: 经营活动产生的现金流量净额 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `n_cashflow_act_lyr_1` | 经营活动产生的现金流量净额lyr_1 | cashflow（现金流量表） | n_cashflow_act | n_cashflow_act: 经营活动产生的现金流量净额 | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `n_cashflow_act_ttm_0` | 经营活动产生的现金流量净额ttm_0 | cashflow（现金流量表） | n_cashflow_act | n_cashflow_act: 经营活动产生的现金流量净额 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `n_cashflow_act_ttm_4` | 经营活动产生的现金流量净额ttm_4 | cashflow（现金流量表） | n_cashflow_act | n_cashflow_act: 经营活动产生的现金流量净额 | TTM窗口口径，report_offset 从 4 到 7 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `n_cashflow_inv_act_lyr_0` | 投资活动产生的现金流量净额lyr_0 | cashflow（现金流量表） | n_cashflow_inv_act | n_cashflow_inv_act: 投资活动产生的现金流量净额 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `n_cashflow_inv_act_lyr_1` | 投资活动产生的现金流量净额lyr_1 | cashflow（现金流量表） | n_cashflow_inv_act | n_cashflow_inv_act: 投资活动产生的现金流量净额 | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `n_cashflow_inv_act_ttm_0` | 投资活动产生的现金流量净额ttm_0 | cashflow（现金流量表） | n_cashflow_inv_act | n_cashflow_inv_act: 投资活动产生的现金流量净额 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `n_cashflow_inv_act_ttm_4` | 投资活动产生的现金流量净额ttm_4 | cashflow（现金流量表） | n_cashflow_inv_act | n_cashflow_inv_act: 投资活动产生的现金流量净额 | TTM窗口口径，report_offset 从 4 到 7 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `n_incr_cash_cash_equ_lyr_0` | 现金及现金等价物净增加额lyr_0 | cashflow（现金流量表） | n_incr_cash_cash_equ | n_incr_cash_cash_equ: 现金及现金等价物净增加额 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `n_incr_cash_cash_equ_lyr_1` | 现金及现金等价物净增加额lyr_1 | cashflow（现金流量表） | n_incr_cash_cash_equ | n_incr_cash_cash_equ: 现金及现金等价物净增加额 | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `n_incr_cash_cash_equ_ttm_0` | 现金及现金等价物净增加额ttm_0 | cashflow（现金流量表） | n_incr_cash_cash_equ | n_incr_cash_cash_equ: 现金及现金等价物净增加额 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `n_incr_cash_cash_equ_ttm_4` | 现金及现金等价物净增加额ttm_4 | cashflow（现金流量表） | n_incr_cash_cash_equ | n_incr_cash_cash_equ: 现金及现金等价物净增加额 | TTM窗口口径，report_offset 从 4 到 7 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `prov_depr_assets_lyr_0` | 资产减值准备lyr_0 | cashflow（现金流量表） | prov_depr_assets | prov_depr_assets: 加:资产减值准备 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `prov_depr_assets_ttm_0` | 资产减值准备ttm_0 | cashflow（现金流量表） | prov_depr_assets | prov_depr_assets: 加:资产减值准备 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `ebitda_lyr` | EBITDAlyr | fina_indicator（财务指标数据） | ebitda | ebitda: 息税折旧摊销前利润 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `ebitda_ttm` | EBITDAttm | fina_indicator（财务指标数据） | ebitda | ebitda: 息税折旧摊销前利润 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对单季化后的字段求和，否则为空；该财务指标先由累计口径单季化。 |
| `fin_exp_int_exp_lyr_0` | 利息支出lyr_0 | income（利润表） | fin_exp_int_exp | fin_exp_int_exp: 财务费用:利息费用 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `fin_exp_int_exp_ttm_0` | 利息支出ttm_0 | income（利润表） | fin_exp_int_exp | fin_exp_int_exp: 财务费用:利息费用 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `fin_exp_int_inc_lyr_0` | 利息收入lyr_0 | income（利润表） | fin_exp_int_inc | fin_exp_int_inc: 财务费用:利息收入 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `fin_exp_int_inc_ttm_0` | 利息收入ttm_0 | income（利润表） | fin_exp_int_inc | fin_exp_int_inc: 财务费用:利息收入 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `income_tax_lyr_0` | 所得税费用lyr_0 | income（利润表） | income_tax | income_tax: 所得税费用 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `income_tax_ttm_0` | 所得税费用ttm_0 | income（利润表） | income_tax | income_tax: 所得税费用 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `int_income_ttm_0` | 利息收入ttm_0 | income（利润表） | int_income | int_income: 利息收入 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `n_income_lyr_0` | 净利润(含少数股东损益)lyr_0 | income（利润表） | n_income | n_income: 净利润(含少数股东损益) | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `n_income_lyr_1` | 净利润(含少数股东损益)lyr_1 | income（利润表） | n_income | n_income: 净利润(含少数股东损益) | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `n_income_ttm_0` | 净利润(含少数股东损益)ttm_0 | income（利润表） | n_income | n_income: 净利润(含少数股东损益) | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `n_income_ttm_1` | 净利润(含少数股东损益)ttm_1 | income（利润表） | n_income | n_income: 净利润(含少数股东损益) | TTM窗口口径，report_offset 从 1 到 4 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `n_income_ttm_4` | 净利润(含少数股东损益)ttm_4 | income（利润表） | n_income | n_income: 净利润(含少数股东损益) | TTM窗口口径，report_offset 从 4 到 7 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `n_income_attr_p_lyr_0` | 净利润(不含少数股东损益)lyr_0 | income（利润表） | n_income_attr_p | n_income_attr_p: 净利润(不含少数股东损益) | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `n_income_attr_p_lyr_1` | 净利润(不含少数股东损益)lyr_1 | income（利润表） | n_income_attr_p | n_income_attr_p: 净利润(不含少数股东损益) | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `n_income_attr_p_ttm_0` | 净利润(不含少数股东损益)ttm_0 | income（利润表） | n_income_attr_p | n_income_attr_p: 净利润(不含少数股东损益) | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `n_income_attr_p_ttm_4` | 净利润(不含少数股东损益)ttm_4 | income（利润表） | n_income_attr_p | n_income_attr_p: 净利润(不含少数股东损益) | TTM窗口口径，report_offset 从 4 到 7 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `operate_profit_lyr_0` | 营业利润lyr_0 | income（利润表） | operate_profit | operate_profit: 营业利润 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `operate_profit_lyr_1` | 营业利润lyr_1 | income（利润表） | operate_profit | operate_profit: 营业利润 | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `operate_profit_ttm_0` | 营业利润ttm_0 | income（利润表） | operate_profit | operate_profit: 营业利润 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `operate_profit_ttm_4` | 营业利润ttm_4 | income（利润表） | operate_profit | operate_profit: 营业利润 | TTM窗口口径，report_offset 从 4 到 7 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `revenue_lyr_0` | 营业收入lyr_0 | income（利润表） | revenue | revenue: 营业收入 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `revenue_lyr_1` | 营业收入lyr_1 | income（利润表） | revenue | revenue: 营业收入 | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `revenue_ttm_0` | 营业收入ttm_0 | income（利润表） | revenue | revenue: 营业收入 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `revenue_ttm_4` | 营业收入ttm_4 | income（利润表） | revenue | revenue: 营业收入 | TTM窗口口径，report_offset 从 4 到 7 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `total_cogs_lyr_0` | 营业总成本lyr_0 | income（利润表） | total_cogs | total_cogs: 营业总成本 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `total_cogs_lyr_1` | 营业总成本lyr_1 | income（利润表） | total_cogs | total_cogs: 营业总成本 | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `total_cogs_ttm_0` | 营业总成本ttm_0 | income（利润表） | total_cogs | total_cogs: 营业总成本 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `total_cogs_ttm_4` | 营业总成本ttm_4 | income（利润表） | total_cogs | total_cogs: 营业总成本 | TTM窗口口径，report_offset 从 4 到 7 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `total_profit_lyr_0` | 利润总额lyr_0 | income（利润表） | total_profit | total_profit: 利润总额 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `total_profit_lyr_1` | 利润总额lyr_1 | income（利润表） | total_profit | total_profit: 利润总额 | 最近年度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `total_profit_ttm_0` | 利润总额ttm_0 | income（利润表） | total_profit | total_profit: 利润总额 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `total_profit_ttm_4` | 利润总额ttm_4 | income（利润表） | total_profit | total_profit: 利润总额 | TTM窗口口径，report_offset 从 4 到 7 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `basic_eps_lyr_0` | 基本每股收益 | income（利润表） | basic_eps | basic_eps: 基本每股收益 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `basic_eps_ttm_0` | 基本每股收益 | income（利润表） | basic_eps | basic_eps: 基本每股收益 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `oper_cost_lyr_0` | 营业成本 | income（利润表） | oper_cost | oper_cost: 减:营业成本 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `oper_cost_ttm_0` | 营业成本 | income（利润表） | oper_cost | oper_cost: 减:营业成本 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `ebit_lyr` | 息税前利润(EBIT)（最近年报） | fina_indicator（财务指标数据） | ebit | ebit: 息税前利润 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `ebit_ttm` | 息税前利润(EBIT)（TTM） | fina_indicator（财务指标数据） | ebit | ebit: 息税前利润 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对单季化后的字段求和，否则为空；该财务指标先由累计口径单季化。 |
| `fv_value_chg_gain_lyr_0` | 公允价值变动收益 | income（利润表） | fv_value_chg_gain | fv_value_chg_gain: 加:公允价值变动净收益 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `fv_value_chg_gain_ttm_0` | 公允价值变动收益 | income（利润表） | fv_value_chg_gain | fv_value_chg_gain: 加:公允价值变动净收益 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `fin_exp_lyr_0` | 财务费用（LYR，滞后0期） | income（利润表） | fin_exp | fin_exp: 减:财务费用 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `fin_exp_ttm_0` | 财务费用 | income（利润表） | fin_exp | fin_exp: 减:财务费用 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `diluted_eps_lyr_0` | 稀释每股收益 | income（利润表） | diluted_eps | diluted_eps: 稀释每股收益 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `diluted_eps_ttm_0` | 稀释每股收益 | income（利润表） | diluted_eps | diluted_eps: 稀释每股收益 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `oth_impair_loss_assets_lyr_0` | 开发支出 | income（利润表） | oth_impair_loss_assets | oth_impair_loss_assets: 其他资产减值损失 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `oth_impair_loss_assets_mrq_0` | 开发支出 | income（利润表） | oth_impair_loss_assets | oth_impair_loss_assets: 其他资产减值损失 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段；利润表/现金流量表季度值先由累计口径单季化：Q1取当期值，Q2-Q4取当期累计值减上一季度累计值。。 |
| `oth_impair_loss_assets_ttm_0` | 开发支出 | income（利润表） | oth_impair_loss_assets | oth_impair_loss_assets: 其他资产减值损失 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `int_income_lyr_0` | 利息收入(财务费用) | income（利润表） | int_income | int_income: 利息收入 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `ass_invest_income_lyr_0` | 对联营合营公司的投资收益 | income（利润表） | ass_invest_income | ass_invest_income: 其中:对联营企业和合营企业的投资收益 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `ass_invest_income_ttm_0` | 对联营合营公司的投资收益 | income（利润表） | ass_invest_income | ass_invest_income: 其中:对联营企业和合营企业的投资收益 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `invest_income_lyr_0` | 投资收益（LYR，滞后0期） | income（利润表） | invest_income | invest_income: 加:投资净收益 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `invest_income_ttm_0` | 投资收益（TTM） | income（利润表） | invest_income | invest_income: 加:投资净收益 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `non_oper_exp_lyr_0` | 营业外支出（LYR，滞后0期） | income（利润表） | non_oper_exp | non_oper_exp: 减:营业外支出 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `non_oper_exp_ttm_0` | 营业外支出（TTM） | income（利润表） | non_oper_exp | non_oper_exp: 减:营业外支出 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `non_oper_income_lyr_0` | 营业外收入（LYR，滞后0期） | income（利润表） | non_oper_income | non_oper_income: 加:营业外收入 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `non_oper_income_ttm_0` | 营业外收入（LYR，滞后0期） | income（利润表） | non_oper_income | non_oper_income: 加:营业外收入 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `biz_tax_surchg_lyr_0` | 营业税金及附加 | income（利润表） | biz_tax_surchg | biz_tax_surchg: 减:营业税金及附加 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `biz_tax_surchg_ttm_0` | 营业税金及附加 | income（利润表） | biz_tax_surchg | biz_tax_surchg: 减:营业税金及附加 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `acc_exp_lyr_0` | 预提费用 | balancesheet（资产负债表） | acc_exp | acc_exp: 预提费用 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `acc_exp_mrq_0` | 预提费用 | balancesheet（资产负债表） | acc_exp | acc_exp: 预提费用 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `acc_exp_ttm_0` | 预提费用 | balancesheet（资产负债表） | acc_exp | acc_exp: 预提费用 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `acct_payable_lyr_0` | 应付账款（LYR，滞后0期） | balancesheet（资产负债表） | acct_payable | acct_payable: 应付账款 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `acct_payable_mrq_0` | 应付账款（MRQ） | balancesheet（资产负债表） | acct_payable | acct_payable: 应付账款 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `acct_payable_ttm_0` | 应付账款（TTM） | balancesheet（资产负债表） | acct_payable | acct_payable: 应付账款 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `accounts_receiv_ttm_0` | 应收账款（TTM） | balancesheet（资产负债表） | accounts_receiv | accounts_receiv: 应收账款 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `adv_receipts_lyr_0` | 预收款项 | balancesheet（资产负债表） | adv_receipts | adv_receipts: 预收款项 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `adv_receipts_mrq_0` | 预收款项 | balancesheet（资产负债表） | adv_receipts | adv_receipts: 预收款项 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `adv_receipts_ttm_0` | 预收款项 | balancesheet（资产负债表） | adv_receipts | adv_receipts: 预收款项 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `notes_receiv_lyr_0` | 应收票据 | balancesheet（资产负债表） | notes_receiv | notes_receiv: 应收票据 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `notes_receiv_mrq_0` | 应收票据（MRQ） | balancesheet（资产负债表） | notes_receiv | notes_receiv: 应收票据 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `notes_receiv_ttm_0` | 应收票据（TTM） | balancesheet（资产负债表） | notes_receiv | notes_receiv: 应收票据 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `bond_payable_lyr_0` | 应付债券（LYR，滞后0期） | balancesheet（资产负债表） | bond_payable | bond_payable: 应付债券 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `bond_payable_mrq_0` | 应付债券（MRQ） | balancesheet（资产负债表） | bond_payable | bond_payable: 应付债券 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `cap_rese_lyr_0` | 资本公积金 | balancesheet（资产负债表） | cap_rese | cap_rese: 资本公积金 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `cap_rese_mrq_0` | 资本公积金 | balancesheet（资产负债表） | cap_rese | cap_rese: 资本公积金 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `cap_rese_ttm_0` | 资本公积金 | balancesheet（资产负债表） | cap_rese | cap_rese: 资本公积金 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `total_cur_assets_mrq_0` | 流动资产（MRQ） | balancesheet（资产负债表） | total_cur_assets | total_cur_assets: 流动资产合计 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `total_cur_liab_mrq_0` | 流动负债（MRQ） | balancesheet（资产负债表） | total_cur_liab | total_cur_liab: 流动负债合计 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `amor_exp_lyr_0` | 待摊费用 | balancesheet（资产负债表） | amor_exp | amor_exp: 长期待摊费用 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `amor_exp_mrq_0` | 待摊费用 | balancesheet（资产负债表） | amor_exp | amor_exp: 长期待摊费用 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `amor_exp_ttm_0` | 待摊费用 | balancesheet（资产负债表） | amor_exp | amor_exp: 长期待摊费用 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `deferred_inc_lyr_0` | 递延收益（LYR，滞后0期） | balancesheet（资产负债表） | deferred_inc | deferred_inc: 递延收益 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `deferred_inc_mrq_0` | 递延收益（MRQ） | balancesheet（资产负债表） | deferred_inc | deferred_inc: 递延收益 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `deferred_inc_ttm_0` | 递延收益（TTM） | balancesheet（资产负债表） | deferred_inc | deferred_inc: 递延收益 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `const_materials_lyr_0` | 工程物资 | balancesheet（资产负债表） | const_materials | const_materials: 工程物资 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `const_materials_mrq_0` | 工程物资（MRQ） | balancesheet（资产负债表） | const_materials | const_materials: 工程物资 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `const_materials_ttm_0` | 工程物资（TTM） | balancesheet（资产负债表） | const_materials | const_materials: 工程物资 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `total_hldr_eqy_exc_min_int_ttm_1` | 归属于母公司股东权益（TTM（滞后1期）） | balancesheet（资产负债表） | total_hldr_eqy_exc_min_int | total_hldr_eqy_exc_min_int: 股东权益合计(不含少数股东权益) | TTM窗口口径，report_offset 从 1 到 4 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `trad_asset_lyr_0` | 交易性金融资产 | balancesheet（资产负债表） | trad_asset | trad_asset: 交易性金融资产 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `trad_asset_mrq_0` | 交易性金融资产 | balancesheet（资产负债表） | trad_asset | trad_asset: 交易性金融资产 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `trad_asset_ttm_0` | 交易性金融资产 | balancesheet（资产负债表） | trad_asset | trad_asset: 交易性金融资产 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `goodwill_lyr_0` | 商誉 | balancesheet（资产负债表） | goodwill | goodwill: 商誉 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `goodwill_mrq_0` | 商誉（MRQ） | balancesheet（资产负债表） | goodwill | goodwill: 商誉 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `goodwill_ttm_0` | 商誉（TTM） | balancesheet（资产负债表） | goodwill | goodwill: 商誉 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `inventories_lyr_0` | 本期年报披露存货 | balancesheet（资产负债表） | inventories | inventories: 存货 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `inventories_mrq_0` | 本期年报披露存货 | balancesheet（资产负债表） | inventories | inventories: 存货 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `inventories_ttm_0` | 本期年报披露存货 | balancesheet（资产负债表） | inventories | inventories: 存货 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `lt_borr_lyr_0` | 长期借款（LYR，滞后0期） | balancesheet（资产负债表） | lt_borr | lt_borr: 长期借款 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `lt_borr_mrq_0` | 长期借款（MRQ） | balancesheet（资产负债表） | lt_borr | lt_borr: 长期借款 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `accounts_receiv_lyr_0` | 应收账款净额（LYR，滞后0期） | balancesheet（资产负债表） | accounts_receiv | accounts_receiv: 应收账款 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `accounts_receiv_mrq_0` | 应收账款净额 | balancesheet（资产负债表） | accounts_receiv | accounts_receiv: 应收账款 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `total_nca_lyr_0` | 非流动资产（LYR，滞后0期） | balancesheet（资产负债表） | total_nca | total_nca: 非流动资产合计 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `total_nca_mrq_0` | 非流动资产（MRQ） | balancesheet（资产负债表） | total_nca | total_nca: 非流动资产合计 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `total_nca_ttm_0` | 非流动资产（TTM） | balancesheet（资产负债表） | total_nca | total_nca: 非流动资产合计 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `total_ncl_lyr_0` | 非流动负债（LYR，滞后0期） | balancesheet（资产负债表） | total_ncl | total_ncl: 非流动负债合计 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `total_ncl_mrq_0` | 非流动负债（MRQ） | balancesheet（资产负债表） | total_ncl | total_ncl: 非流动负债合计 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `total_ncl_ttm_0` | 非流动负债（TTM） | balancesheet（资产负债表） | total_ncl | total_ncl: 非流动负债合计 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `oth_receiv_lyr_0` | 其他应收款（MRQ） | balancesheet（资产负债表） | oth_receiv | oth_receiv: 其他应收款 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `oth_receiv_mrq_0` | 其他应收款（MRQ） | balancesheet（资产负债表） | oth_receiv | oth_receiv: 其他应收款 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `oth_receiv_ttm_0` | 其他应收款（TTM） | balancesheet（资产负债表） | oth_receiv | oth_receiv: 其他应收款 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `oth_cur_liab_lyr_0` | 其他流动负债 | balancesheet（资产负债表） | oth_cur_liab | oth_cur_liab: 其他流动负债 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `oth_cur_liab_mrq_0` | 其他流动负债 | balancesheet（资产负债表） | oth_cur_liab | oth_cur_liab: 其他流动负债 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `oth_cur_liab_ttm_0` | 其他流动负债 | balancesheet（资产负债表） | oth_cur_liab | oth_cur_liab: 其他流动负债 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `oth_payable_lyr_0` | 其他应付款 | balancesheet（资产负债表） | oth_payable | oth_payable: 其他应付款 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `oth_payable_mrq_0` | 其他应付款（MRQ） | balancesheet（资产负债表） | oth_payable | oth_payable: 其他应付款 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `oth_payable_ttm_0` | 其他应付款（TTM） | balancesheet（资产负债表） | oth_payable | oth_payable: 其他应付款 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `payroll_payable_lyr_0` | 应付职工薪酬 | balancesheet（资产负债表） | payroll_payable | payroll_payable: 应付职工薪酬 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `payroll_payable_mrq_0` | 应付职工薪酬（MRQ） | balancesheet（资产负债表） | payroll_payable | payroll_payable: 应付职工薪酬 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `payroll_payable_ttm_0` | 应付职工薪酬（TTM） | balancesheet（资产负债表） | payroll_payable | payroll_payable: 应付职工薪酬 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `prepayment_lyr_0` | 预付账款 | balancesheet（资产负债表） | prepayment | prepayment: 预付款项 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `prepayment_mrq_0` | 预付款项（MRQ） | balancesheet（资产负债表） | prepayment | prepayment: 预付款项 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `prepayment_ttm_0` | 预付款项（TTM） | balancesheet（资产负债表） | prepayment | prepayment: 预付款项 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `st_borr_lyr_0` | 短期借款 | balancesheet（资产负债表） | st_borr | st_borr: 短期借款 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `surplus_rese_lyr_0` | 盈余公积（LYR，滞后0期） | balancesheet（资产负债表） | surplus_rese | surplus_rese: 盈余公积金 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `surplus_rese_mrq_0` | 盈余公积（MRQ） | balancesheet（资产负债表） | surplus_rese | surplus_rese: 盈余公积金 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `surplus_rese_ttm_0` | 盈余公积（TTM） | balancesheet（资产负债表） | surplus_rese | surplus_rese: 盈余公积金 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `taxes_payable_lyr_0` | 应交税费 | balancesheet（资产负债表） | taxes_payable | taxes_payable: 应交税费 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `taxes_payable_mrq_0` | 应交税费（MRQ） | balancesheet（资产负债表） | taxes_payable | taxes_payable: 应交税费 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `taxes_payable_ttm_0` | 应交税费（TTM） | balancesheet（资产负债表） | taxes_payable | taxes_payable: 应交税费 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `total_assets_mrq_1` | 资产总计（MRQ（滞后1期）） | balancesheet（资产负债表） | total_assets | total_assets: 资产总计 | 最近季度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `total_assets_ttm_1` | 资产总计（TTM（滞后1期）） | balancesheet（资产负债表） | total_assets | total_assets: 资产总计 | TTM窗口口径，report_offset 从 1 到 4 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `fix_assets_mrq_0` | 固定资产合计（MRQ） | balancesheet（资产负债表） | fix_assets | fix_assets: 固定资产 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `undistr_porfit_lyr_0` | 未分配利润 | balancesheet（资产负债表） | undistr_porfit | undistr_porfit: 未分配利润 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `undistr_porfit_mrq_0` | 未分配利润 | balancesheet（资产负债表） | undistr_porfit | undistr_porfit: 未分配利润 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `undistr_porfit_ttm_0` | 未分配利润 | balancesheet（资产负债表） | undistr_porfit | undistr_porfit: 未分配利润 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `working_capital_lyr` | 营运资本 | fina_indicator（财务指标数据） | working_capital | working_capital: 营运资金 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `cip_lyr_0` | 在建工程合计（LYR，滞后0期） | balancesheet（资产负债表） | cip | cip: 在建工程 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `cip_mrq_0` | 在建工程合计（MRQ） | balancesheet（资产负债表） | cip | cip: 在建工程 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `cip_ttm_0` | 在建工程合计（TTM） | balancesheet（资产负债表） | cip | cip: 在建工程 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `fix_assets_total_lyr_0` | 固定资产净额（LYR，滞后0期） | balancesheet（资产负债表） | fix_assets_total | fix_assets_total: 固定资产(合计)(元) | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `fix_assets_total_ttm_0` | 固定资产净额 | balancesheet（资产负债表） | fix_assets_total | fix_assets_total: 固定资产(合计)(元) | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `cip_total_lyr_0` | 在建工程合计（LYR，滞后0期） | balancesheet（资产负债表） | cip_total | cip_total: 在建工程(合计)(元) | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `cip_total_mrq_0` | 在建工程合计（MRQ） | balancesheet（资产负债表） | cip_total | cip_total: 在建工程(合计)(元) | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `cip_total_ttm_0` | 在建工程合计（TTM） | balancesheet（资产负债表） | cip_total | cip_total: 在建工程(合计)(元) | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `total_hldr_eqy_inc_min_int_mrq_0` | 股东权益合计 | balancesheet（资产负债表） | total_hldr_eqy_inc_min_int | total_hldr_eqy_inc_min_int: 股东权益合计(含少数股东权益) | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `total_hldr_eqy_inc_min_int_mrq_1` | 股东权益合计 | balancesheet（资产负债表） | total_hldr_eqy_inc_min_int | total_hldr_eqy_inc_min_int: 股东权益合计(含少数股东权益) | 最近季度报告口径，report_offset=1；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `total_hldr_eqy_inc_min_int_ttm_1` | 股东权益合计 | balancesheet（资产负债表） | total_hldr_eqy_inc_min_int | total_hldr_eqy_inc_min_int: 股东权益合计(含少数股东权益) | TTM窗口口径，report_offset 从 1 到 4 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `lt_amort_deferred_exp_ttm_0` | 长期待摊费用摊销 | cashflow（现金流量表） | lt_amort_deferred_exp | lt_amort_deferred_exp: 长期待摊费用摊销 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `lt_amort_deferred_exp_mrq_0` | 长期待摊费用摊销 | cashflow（现金流量表） | lt_amort_deferred_exp | lt_amort_deferred_exp: 长期待摊费用摊销 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段；利润表/现金流量表季度值先由累计口径单季化：Q1取当期值，Q2-Q4取当期累计值减上一季度累计值。。 |
| `eff_fx_flu_cash_lyr_0` | 汇兑损益（LYR，滞后0期） | cashflow（现金流量表） | eff_fx_flu_cash | eff_fx_flu_cash: 汇率变动对现金的影响 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `eff_fx_flu_cash_ttm_0` | 汇兑损益 | cashflow（现金流量表） | eff_fx_flu_cash | eff_fx_flu_cash: 汇率变动对现金的影响 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；利润表/现金流量表季度值先由累计口径单季化。 |
| `depr_fa_coga_dpba_mrq_0` | 固定资产折旧 | cashflow（现金流量表） | depr_fa_coga_dpba | depr_fa_coga_dpba: 固定资产折旧、油气资产折耗、生产性生物资产折旧 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段；利润表/现金流量表季度值先由累计口径单季化：Q1取当期值，Q2-Q4取当期累计值减上一季度累计值。。 |
| `amort_intang_assets_mrq_0` | intangible asset amortization（MRQ） | cashflow（现金流量表） | amort_intang_assets | amort_intang_assets: 无形资产摊销 | 最近季度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应报告期字段；利润表/现金流量表季度值先由累计口径单季化：Q1取当期值，Q2-Q4取当期累计值减上一季度累计值。。 |
| `arturn_days_lyr` | 应付账款周转天数（最近年报） | fina_indicator（财务指标数据） | arturn_days | arturn_days: 应收账款周转天数 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `ar_turn_lyr` | 应付账款周转率（最近年报） | fina_indicator（财务指标数据） | ar_turn | ar_turn: 应收账款周转率 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `ar_turn_ttm` | 应付账款周转率（TTM） | fina_indicator（财务指标数据） | ar_turn | ar_turn: 应收账款周转率 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `arturn_days_ttm` | 应收账款周转天数（TTM） | fina_indicator（财务指标数据） | arturn_days | arturn_days: 应收账款周转天数 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `profit_dedt_lyr_0` | 扣除非经常性损益的净利润 | fina_indicator（财务指标数据） | profit_dedt | profit_dedt: 扣除非经常性损益后的净利润 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `profit_dedt_ttm_0` | 扣除非经常性损益的净利润 | fina_indicator（财务指标数据） | profit_dedt | profit_dedt: 扣除非经常性损益后的净利润 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；该财务指标先由累计口径单季化。 |
| `fcfe_lyr_0` | 股东自由现金流量 | fina_indicator（财务指标数据） | fcfe | fcfe: 股权自由现金流量 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `fcfe_ttm_0` | 股东自由现金流量 | fina_indicator（财务指标数据） | fcfe | fcfe: 股权自由现金流量 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；该财务指标先由累计口径单季化。 |
| `fcff_lyr_0` | 股东自由现金流量 | fina_indicator（财务指标数据） | fcff | fcff: 企业自由现金流量 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `fcff_ttm_0` | 股东自由现金流量 | fina_indicator（财务指标数据） | fcff | fcff: 企业自由现金流量 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；该财务指标先由累计口径单季化。 |
| `interestdebt_lf` | 带息债务 | fina_indicator（财务指标数据） | interestdebt | interestdebt: 带息债务 | 最新报告期；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `interestdebt_lyr` | 带息债务 | fina_indicator（财务指标数据） | interestdebt | interestdebt: 带息债务 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `interestdebt_ttm` | 带息债务 | fina_indicator（财务指标数据） | interestdebt | interestdebt: 带息债务 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `inv_turn_lyr` | 存货周转率（最近年报） | fina_indicator（财务指标数据） | inv_turn | inv_turn: 存货周转率 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `inv_turn_ttm` | 存货周转率（TTM） | fina_indicator（财务指标数据） | inv_turn | inv_turn: 存货周转率 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `invest_capital_lf` | 投入资本（最新口径） | fina_indicator（财务指标数据） | invest_capital | invest_capital: 全部投入资本 | 最新报告期；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `invest_capital_lyr` | 投入资本（最近年报） | fina_indicator（财务指标数据） | invest_capital | invest_capital: 全部投入资本 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `invest_capital_ttm` | 投入资本（TTM） | fina_indicator（财务指标数据） | invest_capital | invest_capital: 全部投入资本 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `netdebt_lyr` | 净负债/净债务（LYR） | fina_indicator（财务指标数据） | netdebt | netdebt: 净债务 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `netdebt_ttm` | 净负债（TTM） | fina_indicator（财务指标数据） | netdebt | netdebt: 净债务 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `current_exint_lf` | 无息流动负债(口径)（最新口径） | fina_indicator（财务指标数据） | current_exint | current_exint: 无息流动负债 | 最新报告期；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `current_exint_lyr` | 无息流动负债/无息流动债务（LYR） | fina_indicator（财务指标数据） | current_exint | current_exint: 无息流动负债 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `current_exint_ttm` | 无息流动负债(口径)（TTM） | fina_indicator（财务指标数据） | current_exint | current_exint: 无息流动负债 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `noncurrent_exint_lf` | 无息非流动负债(口径)（最新口径） | fina_indicator（财务指标数据） | noncurrent_exint | noncurrent_exint: 无息非流动负债 | 最新报告期；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `noncurrent_exint_lyr` | 无息非流动负债/无息非流动债务（LYR） | fina_indicator（财务指标数据） | noncurrent_exint | noncurrent_exint: 无息非流动负债 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `noncurrent_exint_ttm` | 无息非流动负债(口径)（TTM） | fina_indicator（财务指标数据） | noncurrent_exint | noncurrent_exint: 无息非流动负债 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `extra_item_lyr_0` | 非经常性损益（LYR，滞后0期） | fina_indicator（财务指标数据） | extra_item | extra_item: 非经常性损益 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `extra_item_ttm_0` | 非经常性损益（TTM） | fina_indicator（财务指标数据） | extra_item | extra_item: 非经常性损益 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求和，否则为空；该财务指标先由累计口径单季化。 |
| `turn_days_lyr_0` | 营业周期（TTM） | fina_indicator（财务指标数据） | turn_days | turn_days: 营业周期 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `turn_days_ttm_0` | 营业周期（TTM） | fina_indicator（财务指标数据） | turn_days | turn_days: 营业周期 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `retained_earnings_lf` | 留存收益（最新口径） | fina_indicator（财务指标数据） | retained_earnings | retained_earnings: 留存收益 | 最新报告期；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `retained_earnings_lyr` | 留存收益（最近年报） | fina_indicator（财务指标数据） | retained_earnings | retained_earnings: 留存收益 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `retained_earnings_ttm` | 留存收益（TTM） | fina_indicator（财务指标数据） | retained_earnings | retained_earnings: 留存收益 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `assets_turn_lyr` | 总资产周转率（最近年报） | fina_indicator（财务指标数据） | assets_turn | assets_turn: 总资产周转率 | 最近年度报告口径，report_offset=0；先按公告可见日期选取可见版本，再取对应年度报告字段。 |
| `assets_turn_ttm` | 总资产周转率（TTM） | fina_indicator（财务指标数据） | assets_turn | assets_turn: 总资产周转率 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `working_capital_lf` | 营运资本 | fina_indicator（财务指标数据） | working_capital | working_capital: 营运资金 | 最新报告期；先按公告可见日期选取可见版本，再取对应报告期字段。 |
| `working_capital_ttm` | 营运资本 | fina_indicator（财务指标数据） | working_capital | working_capital: 营运资金 | TTM窗口口径，report_offset 从 0 到 3 共4个报告期；4期均非空时对原始字段求平均，否则为空 |
| `volume_ratio` | 情绪/交易活跃因子(近似) | daily_basic（每日指标） | volume_ratio | volume_ratio: 量比 | 直接取 daily_basic.volume_ratio；与 volume_ratio_db 同源，保留给因子表达式使用。 |
| `assets_impair_loss` | 资产减值损失TTM | income（利润表） | assets_impair_loss | assets_impair_loss: 减:资产减值损失 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `int_exp` | 利息支出TTM | income（利润表） | int_exp | int_exp: 减:利息支出 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `div_receiv` | 应收股利 | balancesheet（资产负债表） | div_receiv | div_receiv: 应收股利 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `fa_avail_for_sale` | 可供出售金融资产 | balancesheet（资产负债表） | fa_avail_for_sale | fa_avail_for_sale: 可供出售金融资产 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `htm_invest` | 持有至到期投资 | balancesheet（资产负债表） | htm_invest | htm_invest: 持有至到期投资 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `int_receiv` | 应收利息 | balancesheet（资产负债表） | int_receiv | int_receiv: 应收利息 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `intan_assets` | 无形资产 | balancesheet（资产负债表） | intan_assets | intan_assets: 无形资产 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `r_and_d` | 研发支出 | balancesheet（资产负债表） | r_and_d | r_and_d: 研发支出 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `c_cash_equ_end_period` | 期末现金及现金等价物余额 | cashflow（现金流量表） | c_cash_equ_end_period | c_cash_equ_end_period: 期末现金及现金等价物余额 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `c_fr_sale_sg` | 销售商品、提供劳务收到的现金TTM | cashflow（现金流量表） | c_fr_sale_sg | c_fr_sale_sg: 销售商品、提供劳务收到的现金 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `c_pay_acq_const_fiolta` | 投资能力(可用CAPEX强度等近似) | cashflow（现金流量表） | c_pay_acq_const_fiolta | c_pay_acq_const_fiolta: 购建固定资产、无形资产和其他长期资产支付的现金 | 按公告可见日期做 PIT as-of 取最新可见财报记录。 |
| `ev_lyr` | 企业价值 | daily_basic（每日指标）<br>fina_indicator（财务指标数据）<br>balancesheet（资产负债表） | total_mv<br>interestdebt<br>money_cap | total_mv: 总市值<br>interestdebt: 带息债务<br>money_cap: 货币资金 | 计算字段：total_mv * 10000 + interestdebt_lyr - money_cap_lyr_0。 |
| `ev_no_cash_lyr` | 企业价值(剔除现金)（最近年报） | daily_basic（每日指标）<br>fina_indicator（财务指标数据）<br>balancesheet（资产负债表） | total_mv<br>interestdebt<br>money_cap | total_mv: 总市值<br>interestdebt: 带息债务<br>money_cap: 货币资金 | 计算字段：total_mv * 10000 + interestdebt_lyr - money_cap_lyr_0。当前实现与 ev_lyr 相同。 |
| `ev_no_cash_ttm` | 企业价值(剔除现金)（TTM） | daily_basic（每日指标）<br>fina_indicator（财务指标数据）<br>balancesheet（资产负债表） | total_mv<br>interestdebt<br>money_cap | total_mv: 总市值<br>interestdebt: 带息债务<br>money_cap: 货币资金 | 计算字段：total_mv * 10000 + interestdebt_ttm - money_cap_ttm_0。 |
| `ev_ttm` | 企业价值(EV)（TTM） | daily_basic（每日指标）<br>fina_indicator（财务指标数据）<br>balancesheet（资产负债表） | total_mv<br>interestdebt<br>money_cap | total_mv: 总市值<br>interestdebt: 带息债务<br>money_cap: 货币资金 | 计算字段：total_mv * 10000 + interestdebt_ttm - money_cap_ttm_0。当前实现与 ev_no_cash_ttm 相同。 |
| `hk_hold_vol` | 北向持股数量 | hk_hold（沪深股通持股明细） | vol | vol: 持股数量 | 字段重命名：hk_hold.vol -> hk_hold_vol。 |
| `hk_hold_ratio` | 北向持股占比 | hk_hold（沪深股通持股明细） | ratio | ratio: 持股占比 | 字段重命名：hk_hold.ratio -> hk_hold_ratio。 |
| `rzye` | 融资余额 | margin_detail（融资融券交易明细） | rzye | rzye: 融资余额(元) | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `rzmre` | 融资买入额 | margin_detail（融资融券交易明细） | rzmre | rzmre: 融资买入额(元) | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `rzche` | 融资偿还额 | margin_detail（融资融券交易明细） | rzche | rzche: 融资偿还额(元) | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `rqye` | 融券余额 | margin_detail（融资融券交易明细） | rqye | rqye: 融券余额(元) | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `rqyl` | 融券余量 | margin_detail（融资融券交易明细） | rqyl | rqyl: 融券余量（手） | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `rqmcl` | 融券卖出量 | margin_detail（融资融券交易明细） | rqmcl | rqmcl: 融券卖出量(股,份,手) | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `winner_rate` | 获利比例 | cyq_perf（每日筹码及胜率） | winner_rate | winner_rate: 胜率 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `cost_5pct` | 5分位成本 | cyq_perf（每日筹码及胜率） | cost_5pct | cost_5pct: 5分位成本 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `cost_50pct` | 50分位成本 | cyq_perf（每日筹码及胜率） | cost_50pct | cost_50pct: 50分位成本 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `cost_95pct` | 95分位成本 | cyq_perf（每日筹码及胜率） | cost_95pct | cost_95pct: 95分位成本 | 直接取 Tushare 原始字段；仅做字段标准化、PIT可见性或同日/历史可见关联。 |
| `weight_avg_cost` | 加权平均成本 | cyq_perf（每日筹码及胜率） | weight_avg | weight_avg: 加权平均成本 | 字段重命名：cyq_perf.weight_avg -> weight_avg_cost。 |
| `build_time` | 汇总构建时间 | 无直接 Tushare 原始表 | - | - | 系统构建时间：now64(3)。 |
| `source` | 来源系统 | 无直接 Tushare 原始表 | - | - | 固定赋值为 derived。 |
| `source_table` | 来源表 | 无直接 Tushare 原始表 | - | - | 系统血缘字段：记录参与构建的上游标准层表列表；非 Tushare 原始字段。 |
| `source_batch_id` | 来源批次ID | 无直接 Tushare 原始表 | - | - | 系统血缘字段：拼接参与构建记录的批次ID；非 Tushare 原始字段。 |
| `source_record_hash` | 来源记录哈希 | 无直接 Tushare 原始表 | - | - | 系统血缘字段：对参与构建记录的哈希拼接后 MD5；非 Tushare 原始字段。 |
