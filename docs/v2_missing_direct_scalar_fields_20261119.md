# 相对 V2 需新增的因子输入字段

**表内候选字段数量：236 个。**

## 字段清单

| 字段英文名 | 字段中文名 | 来源 | 说明 |
|---|---|---|---|
| `accounts_pay_mrq_0` | 应付票据及应付账款（最近一期报告期） | 上游明细表（default.dwd_stock_balance_sheet.accounts_pay） | — |
| `accounts_pay_mrq_4` | 应付票据及应付账款（最近可见报告期向前四个自然季度） | 上游明细表（default.dwd_stock_balance_sheet.accounts_pay） | — |
| `accounts_receiv_bill_mrq_0` | 应收票据及应收账款（最近一期报告期） | 上游明细表（default.dwd_stock_balance_sheet.accounts_receiv_bill） | — |
| `accounts_receiv_bill_mrq_4` | 应收票据及应收账款（最近可见报告期向前四个自然季度） | 上游明细表（default.dwd_stock_balance_sheet.accounts_receiv_bill） | — |
| `bench_ret` | 中证全指日收益率 | 上游明细表加工（default.dwd_index_eod_price.pct_chg） | 取当日中证全指 `000985.CSI` 的 `pct_chg/100`；指数当日缺失则置空。 |
| `debt_invest_mrq_0` | 债权投资（最近一期报告期） | 上游明细表（default.dwd_stock_balance_sheet.debt_invest） | — |
| `debt_invest_mrq_4` | 债权投资（最近可见报告期向前四个自然季度） | 上游明细表（default.dwd_stock_balance_sheet.debt_invest） | — |
| `defer_tax_assets_mrq_0` | 递延所得税资产（最近一期报告期） | 上游明细表（default.dwd_stock_balance_sheet.defer_tax_assets） | — |
| `fa_avail_for_sale_mrq_0` | 可供出售金融资产（最近一期报告期） | 上游明细表（default.dwd_stock_balance_sheet.fa_avail_for_sale） | — |
| `fa_avail_for_sale_mrq_4` | 可供出售金融资产（最近可见报告期向前四个自然季度） | 上游明细表（default.dwd_stock_balance_sheet.fa_avail_for_sale） | — |
| `fix_assets_total_mrq_0` | 固定资产(合计)（最近一期报告期） | 上游明细表候选（default.dwd_stock_balance_sheet.fix_assets_total；待核是否为净固定资产） | — |
| `fix_assets_total_mrq_1` | 固定资产(合计)（最近可见报告期向前一个自然季度） | 上游明细表（default.dwd_stock_balance_sheet.fix_assets_total） | — |
| `htm_invest_mrq_0` | 持有至到期投资（最近一期报告期） | 上游明细表（default.dwd_stock_balance_sheet.htm_invest） | — |
| `htm_invest_mrq_4` | 持有至到期投资（最近可见报告期向前四个自然季度） | 上游明细表（default.dwd_stock_balance_sheet.htm_invest） | — |
| `intan_assets_mrq_0` | 无形资产（最近一期报告期） | 上游明细表（default.dwd_stock_balance_sheet.intan_assets） | — |
| `lt_amor_exp_mrq_0` | 长期待摊费用（最近一期报告期） | 上游明细表（default.dwd_stock_balance_sheet.lt_amor_exp） | — |
| `lt_eqt_invest_mrq_0` | 长期股权投资（最近一期报告期） | 上游明细表（default.dwd_stock_balance_sheet.lt_eqt_invest） | — |
| `lt_eqt_invest_mrq_4` | 长期股权投资（最近可见报告期向前四个自然季度） | 上游明细表（default.dwd_stock_balance_sheet.lt_eqt_invest） | — |
| `non_cur_liab_due_1y_mrq_0` | 一年内到期的非流动负债（最近一期报告期） | 上游明细表（default.dwd_stock_balance_sheet.non_cur_liab_due_1y） | — |
| `non_cur_liab_due_1y_mrq_4` | 一年内到期的非流动负债（最近可见报告期向前四个自然季度） | 上游明细表（default.dwd_stock_balance_sheet.non_cur_liab_due_1y） | — |
| `notes_payable_mrq_0` | 应付票据（最近一期报告期） | 上游明细表（default.dwd_stock_balance_sheet.notes_payable） | — |
| `notes_payable_mrq_4` | 应付票据（最近可见报告期向前四个自然季度） | 上游明细表（default.dwd_stock_balance_sheet.notes_payable） | — |
| `oth_debt_invest_mrq_0` | 其他债权投资（最近一期报告期） | 上游明细表（default.dwd_stock_balance_sheet.oth_debt_invest） | — |
| `oth_debt_invest_mrq_4` | 其他债权投资（最近可见报告期向前四个自然季度） | 上游明细表（default.dwd_stock_balance_sheet.oth_debt_invest） | — |
| `oth_eq_invest_mrq_0` | 其他权益工具投资（最近一期报告期） | 上游明细表（default.dwd_stock_balance_sheet.oth_eq_invest） | — |
| `oth_eq_invest_mrq_4` | 其他权益工具投资（最近可见报告期向前四个自然季度） | 上游明细表（default.dwd_stock_balance_sheet.oth_eq_invest） | — |
| `oth_eq_ppbond_mrq_0` | 其他权益工具:永续债（最近一期报告期） | 上游明细表（default.dwd_stock_balance_sheet.oth_eq_ppbond） | — |
| `oth_eq_ppbond_mrq_4` | 其他权益工具:永续债（最近可见报告期向前四个自然季度） | 上游明细表（default.dwd_stock_balance_sheet.oth_eq_ppbond） | — |
| `oth_eqt_tools_p_shr_mrq_0` | 其他权益工具(优先股)（最近一期报告期） | 上游明细表（default.dwd_stock_balance_sheet.oth_eqt_tools_p_shr） | — |
| `oth_eqt_tools_p_shr_mrq_4` | 其他权益工具(优先股)（最近可见报告期向前四个自然季度） | 上游明细表（default.dwd_stock_balance_sheet.oth_eqt_tools_p_shr） | — |
| `r_and_d_mrq_0` | 开发支出（最近一期资产负债表期末余额） | 上游明细表（default.dwd_stock_balance_sheet.r_and_d） | — |
| `st_borr_mrq_0` | 短期借款（最近一期报告期） | 上游明细表（default.dwd_stock_balance_sheet.st_borr） | — |
| `st_borr_mrq_1` | 短期借款（最近可见报告期向前一个自然季度） | 上游明细表（default.dwd_stock_balance_sheet.st_borr） | — |
| `st_borr_mrq_4` | 短期借款（最近可见报告期向前四个自然季度） | 上游明细表（default.dwd_stock_balance_sheet.st_borr） | — |
| `total_share_mrq_0` | 最新已可见报告期末总股本 | 上游明细表（default.dwd_stock_balance_sheet.total_share） | — |
| `total_share_mrq_4` | 去年同报告期末总股本 | 上游明细表（default.dwd_stock_balance_sheet.total_share） | — |
| `trading_fl_mrq_0` | 交易性金融负债（最近一期报告期） | 上游明细表（default.dwd_stock_balance_sheet.trading_fl） | — |
| `trading_fl_mrq_4` | 交易性金融负债（最近可见报告期向前四个自然季度） | 上游明细表（default.dwd_stock_balance_sheet.trading_fl） | — |
| `share_action_factor` | 股数尺度累计调整因子（送转、拆合股） | 上游明细表加工（default.dwd_stock_dividend：ts_code、div_proc、stk_div、ex_date、available_trade_date、sys_from、sys_to、source_record_hash；default.ricequant_stock_split：order_book_id、ex_dividend_date、split_coefficient_from、split_coefficient_to、cum_factor、rice_create_tm、_record_hash） | 已实施送转取倍率 `1+stk_div`；已核实历史可用日的拆合股取 `split_coefficient_to/split_coefficient_from`。同一公司行动跨源去重，以 `max(ex_date,available_trade_date)` 起生效，从统一历史基准连续累乘；拆合股历史可用日缺失的区间置空。 |
| `diluted_weighted_share_mrq_0` | 最新报告期稀释加权平均股本 | 上游明细表加工（稀释加权股本直接源列缺失；近似源 default.dwd_stock_balance_sheet.total_share） | 无附注直接值时，近似取同期报告期末 `total_share`（统一为股），即假设期内股数未变且无潜在稀释股；缺总股本置空，不用未核实分子的 `n_income_attr_p/diluted_eps` 反推。 |
| `diluted_weighted_share_mrq_4` | 去年同报告期稀释加权平均股本 | 上游明细表加工（稀释加权股本直接源列缺失；近似源 default.dwd_stock_balance_sheet.total_share） | 无附注直接值时，近似取 `_mrq_0` 对应报告期向前四个自然季度的 `total_share`（统一为股）；缺该报告期置空，不用 `n_income_attr_p/diluted_eps` 反推。 |
| `contract_liab_mrq_0` | 最近一期合同负债 | 上游明细表（default.dwd_stock_balance_sheet.contract_liab） | — |
| `contract_liab_mrq_4` | 去年同报告期合同负债 | 上游明细表（default.dwd_stock_balance_sheet.contract_liab） | — |
| `oth_comp_income_mrq_4` | 去年同报告期其他综合收益余额 | 上游明细表（default.dwd_stock_balance_sheet.oth_comp_income） | — |
| `assets_impair_loss_ttm_0` | 最近四季资产减值损失加回额 | 上游明细表加工（default.dwd_stock_income.assets_impair_loss） | 将“减：资产减值损失”源值按损失为正、转回为负保留，同年累计值先单季化，再汇总连续四季；缺季置空。 |
| `rd_exp_ttm_0` | 最近四季研发费用 | 上游明细表（default.dwd_stock_income.rd_exp） | — |
| `sell_exp_ttm_0` | 最近四季销售费用 | 上游明细表（default.dwd_stock_income.sell_exp） | — |
| `admin_exp_ttm_0` | 最近四季管理费用 | 上游明细表（default.dwd_stock_income.admin_exp） | — |
| `rd_exp_lyr_0` | 最近可见年报研发费用 | 上游明细表（default.dwd_stock_income.rd_exp） | — |
| `rd_exp_indicator_lyr_0` | 2018 年前可见年报附注研发投入 | 上游明细表候选（default.dwd_stock_financial_indicator.rd_exp；待核是否等于年报附注研发投入） | — |
| `sell_exp_lyr_0` | 最近可见年报销售费用 | 上游明细表（default.dwd_stock_income.sell_exp） | — |
| `admin_exp_lyr_0` | 最近可见年报管理费用 | 上游明细表（default.dwd_stock_income.admin_exp） | — |
| `c_fr_sale_sg_mrq_0` | 最新单季销售商品、提供劳务收到的现金 | 上游明细表（default.dwd_stock_cashflow.c_fr_sale_sg） | — |
| `c_fr_sale_sg_mrq_1` | 向前第 2 个自然季度销售商品、提供劳务收到的现金（单季） | 上游明细表（default.dwd_stock_cashflow.c_fr_sale_sg） | — |
| `c_fr_sale_sg_mrq_2` | 向前第 3 个自然季度销售商品、提供劳务收到的现金（单季） | 上游明细表（default.dwd_stock_cashflow.c_fr_sale_sg） | — |
| `c_fr_sale_sg_mrq_3` | 向前第 4 个自然季度销售商品、提供劳务收到的现金（单季） | 上游明细表（default.dwd_stock_cashflow.c_fr_sale_sg） | — |
| `c_fr_sale_sg_mrq_4` | 去年同季销售商品、提供劳务收到的现金（单季） | 上游明细表（default.dwd_stock_cashflow.c_fr_sale_sg） | — |
| `c_fr_sale_sg_mrq_5` | 向前第 6 个自然季度销售商品、提供劳务收到的现金（单季） | 上游明细表（default.dwd_stock_cashflow.c_fr_sale_sg） | — |
| `c_fr_sale_sg_mrq_6` | 向前第 7 个自然季度销售商品、提供劳务收到的现金（单季） | 上游明细表（default.dwd_stock_cashflow.c_fr_sale_sg） | — |
| `c_fr_sale_sg_mrq_7` | 向前第 8 个自然季度销售商品、提供劳务收到的现金（单季） | 上游明细表（default.dwd_stock_cashflow.c_fr_sale_sg） | — |
| `c_fr_sale_sg_mrq_8` | 向前第 9 个自然季度销售商品、提供劳务收到的现金（单季） | 上游明细表（default.dwd_stock_cashflow.c_fr_sale_sg） | — |
| `c_fr_sale_sg_mrq_9` | 向前第 10 个自然季度销售商品、提供劳务收到的现金（单季） | 上游明细表（default.dwd_stock_cashflow.c_fr_sale_sg） | — |
| `c_pay_acq_const_fiolta_mrq_0` | 最新单季购建长期资产支付现金 | 上游明细表（default.dwd_stock_cashflow.c_pay_acq_const_fiolta） | — |
| `c_pay_acq_const_fiolta_mrq_4` | 去年同季购建长期资产支付现金（单季） | 上游明细表（default.dwd_stock_cashflow.c_pay_acq_const_fiolta） | — |
| `n_recp_disp_fiolta_mrq_0` | 最新单季处置长期资产收回现金 | 上游明细表（default.dwd_stock_cashflow.n_recp_disp_fiolta） | — |
| `n_recp_disp_fiolta_mrq_4` | 去年同季处置长期资产收回现金（单季） | 上游明细表（default.dwd_stock_cashflow.n_recp_disp_fiolta） | — |
| `revenue_ttm_12` | 最近可见报告期向前 12 个自然季度起的连续四季营业收入 | 上游明细表（default.dwd_stock_income.revenue） | — |
| `c_pay_acq_const_fiolta_ttm_0` | 最近四季购建长期资产支付现金 | 上游明细表（default.dwd_stock_cashflow.c_pay_acq_const_fiolta） | — |
| `c_pay_acq_const_fiolta_ttm_4` | 滞后四季的四季购建长期资产支付现金 | 上游明细表（default.dwd_stock_cashflow.c_pay_acq_const_fiolta） | — |
| `c_pay_acq_const_fiolta_ttm_8` | 滞后八季的四季购建长期资产支付现金 | 上游明细表（default.dwd_stock_cashflow.c_pay_acq_const_fiolta） | — |
| `c_pay_acq_const_fiolta_ttm_12` | 滞后十二季的四季购建长期资产支付现金 | 上游明细表（default.dwd_stock_cashflow.c_pay_acq_const_fiolta） | — |
| `n_recp_disp_fiolta_ttm_0` | 最近四季处置长期资产收回现金 | 上游明细表（default.dwd_stock_cashflow.n_recp_disp_fiolta） | — |
| `n_recp_disp_fiolta_ttm_4` | 滞后四季的四季处置长期资产收回现金 | 上游明细表（default.dwd_stock_cashflow.n_recp_disp_fiolta） | — |
| `n_recp_disp_fiolta_ttm_8` | 滞后八季的四季处置长期资产收回现金 | 上游明细表（default.dwd_stock_cashflow.n_recp_disp_fiolta） | — |
| `n_recp_disp_fiolta_ttm_12` | 滞后十二季的四季处置长期资产收回现金 | 上游明细表（default.dwd_stock_cashflow.n_recp_disp_fiolta） | — |
| `stot_out_inv_act_mrq_0` | 最新单季投资活动现金流出小计 | 上游明细表（default.dwd_stock_cashflow.stot_out_inv_act） | — |
| `n_income_mrq_0` | 最新单季净利润（含少数股东损益） | 上游明细表（default.dwd_stock_income.n_income） | — |
| `n_income_mrq_4` | 去年同季净利润（含少数股东损益） | 上游明细表（default.dwd_stock_income.n_income） | — |
| `total_profit_mrq_0` | 最新单季利润总额 | 上游明细表（default.dwd_stock_income.total_profit） | — |
| `total_profit_mrq_4` | 去年同季利润总额 | 上游明细表（default.dwd_stock_income.total_profit） | — |
| `oper_cost_mrq_0` | 最新单季营业成本 | 上游明细表（default.dwd_stock_income.oper_cost） | — |
| `oper_cost_mrq_4` | 去年同季营业成本 | 上游明细表（default.dwd_stock_income.oper_cost） | — |
| `sell_exp_mrq_0` | 最新单季销售费用 | 上游明细表（default.dwd_stock_income.sell_exp） | — |
| `sell_exp_mrq_4` | 去年同季销售费用 | 上游明细表（default.dwd_stock_income.sell_exp） | — |
| `admin_exp_mrq_0` | 最新单季管理费用 | 上游明细表（default.dwd_stock_income.admin_exp） | — |
| `admin_exp_mrq_4` | 去年同季管理费用 | 上游明细表（default.dwd_stock_income.admin_exp） | — |
| `fin_exp_mrq_0` | 最新单季财务费用 | 上游明细表（default.dwd_stock_income.fin_exp） | — |
| `fin_exp_mrq_4` | 去年同季财务费用 | 上游明细表（default.dwd_stock_income.fin_exp） | — |
| `rd_exp_mrq_0` | 最新单季研发费用 | 上游明细表（default.dwd_stock_income.rd_exp） | — |
| `rd_exp_mrq_4` | 去年同季研发费用 | 上游明细表（default.dwd_stock_income.rd_exp） | — |
| `compr_inc_attr_p_mrq_0` | 最新单季归母综合收益 | 上游明细表（default.dwd_stock_income.compr_inc_attr_p） | — |
| `t_compr_income_mrq_0` | 最新单季综合收益总额 | 上游明细表（default.dwd_stock_income.t_compr_income） | — |
| `oth_income_mrq_0` | 最新单季其他收益 | 上游明细表（default.dwd_stock_income.oth_income） | — |
| `asset_disp_income_mrq_0` | 最新单季资产处置收益 | 上游明细表（default.dwd_stock_income.asset_disp_income） | — |
| `c_paid_to_for_empl_mrq_0` | 最新单季支付给职工以及为职工支付的现金 | 上游明细表（default.dwd_stock_cashflow.c_paid_to_for_empl） | — |
| `use_right_asset_dep_lyr_0` | 最近年报使用权资产折旧 | 上游明细表（default.dwd_stock_cashflow.use_right_asset_dep） | — |
| `use_right_asset_dep_lyr_1` | 最近可见年报前一自然财年的年报使用权资产折旧 | 上游明细表（default.dwd_stock_cashflow.use_right_asset_dep） | — |
| `basic_eps_mrq_0` | 最新单季基本每股收益 | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_mrq_1` | 向前第 2 个自然季度基本每股收益（单季） | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_mrq_2` | 向前第 3 个自然季度基本每股收益（单季） | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_mrq_3` | 向前第 4 个自然季度基本每股收益（单季） | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_mrq_4` | 去年同季基本每股收益（单季） | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_mrq_5` | 向前第 6 个自然季度基本每股收益（单季） | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_mrq_6` | 向前第 7 个自然季度基本每股收益（单季） | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_mrq_7` | 向前第 8 个自然季度基本每股收益（单季） | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_mrq_8` | 向前第 9 个自然季度基本每股收益（单季） | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_mrq_9` | 向前第 10 个自然季度基本每股收益（单季） | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_mrq_10` | 向前第 11 个自然季度基本每股收益（单季） | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_mrq_11` | 向前第 12 个自然季度基本每股收益（单季） | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_mrq_12` | 向前第 13 个自然季度基本每股收益（单季） | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_lyr_5` | 最近可见年报向前5个自然财年的年报基本每股收益 | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_lyr_6` | 最近可见年报向前6个自然财年的年报基本每股收益 | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_lyr_7` | 最近可见年报向前7个自然财年的年报基本每股收益 | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_lyr_8` | 最近可见年报向前8个自然财年的年报基本每股收益 | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_lyr_9` | 最近可见年报向前9个自然财年的年报基本每股收益 | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `basic_eps_lyr_10` | 最近可见年报向前10个自然财年的年报基本每股收益 | 上游明细表（default.dwd_stock_income.basic_eps） | — |
| `revenue_mrq_0` | 最新可见报告期营业收入（单季） | 上游明细表（default.dwd_stock_income.revenue） | — |
| `revenue_mrq_1` | 向前第 2 个自然季度营业收入（单季） | 上游明细表（default.dwd_stock_income.revenue） | — |
| `revenue_mrq_2` | 向前第 3 个自然季度营业收入（单季） | 上游明细表（default.dwd_stock_income.revenue） | — |
| `revenue_mrq_3` | 向前第 4 个自然季度营业收入（单季） | 上游明细表（default.dwd_stock_income.revenue） | — |
| `revenue_mrq_4` | 向前第 5 个自然季度营业收入（单季） | 上游明细表（default.dwd_stock_income.revenue） | — |
| `revenue_mrq_5` | 向前第 6 个自然季度营业收入（单季） | 上游明细表（default.dwd_stock_income.revenue） | — |
| `revenue_mrq_6` | 向前第 7 个自然季度营业收入（单季） | 上游明细表（default.dwd_stock_income.revenue） | — |
| `revenue_mrq_7` | 向前第 8 个自然季度营业收入（单季） | 上游明细表（default.dwd_stock_income.revenue） | — |
| `revenue_mrq_8` | 向前第 9 个自然季度营业收入（单季） | 上游明细表（default.dwd_stock_income.revenue） | — |
| `revenue_mrq_9` | 向前第 10 个自然季度营业收入（单季） | 上游明细表（default.dwd_stock_income.revenue） | — |
| `revenue_mrq_10` | 向前第 11 个自然季度营业收入（单季） | 上游明细表（default.dwd_stock_income.revenue） | — |
| `revenue_mrq_11` | 向前第 12 个自然季度营业收入（单季） | 上游明细表（default.dwd_stock_income.revenue） | — |
| `revenue_mrq_12` | 向前第 13 个自然季度营业收入（单季） | 上游明细表（default.dwd_stock_income.revenue） | — |
| `n_income_attr_p_mrq_0` | 最新单季归母净利润 | 上游明细表（default.dwd_stock_income.n_income_attr_p） | — |
| `n_income_attr_p_mrq_1` | 向前第 2 个自然季度归母净利润（单季） | 上游明细表（default.dwd_stock_income.n_income_attr_p） | — |
| `n_income_attr_p_mrq_2` | 向前第 3 个自然季度归母净利润（单季） | 上游明细表（default.dwd_stock_income.n_income_attr_p） | — |
| `n_income_attr_p_mrq_3` | 向前第 4 个自然季度归母净利润（单季） | 上游明细表（default.dwd_stock_income.n_income_attr_p） | — |
| `n_income_attr_p_mrq_4` | 去年同季归母净利润（单季） | 上游明细表（default.dwd_stock_income.n_income_attr_p） | — |
| `n_income_attr_p_mrq_5` | 向前第 6 个自然季度归母净利润（单季） | 上游明细表（default.dwd_stock_income.n_income_attr_p） | — |
| `n_income_attr_p_mrq_6` | 向前第 7 个自然季度归母净利润（单季） | 上游明细表（default.dwd_stock_income.n_income_attr_p） | — |
| `n_income_attr_p_mrq_7` | 向前第 8 个自然季度归母净利润（单季） | 上游明细表（default.dwd_stock_income.n_income_attr_p） | — |
| `n_income_attr_p_mrq_8` | 向前第 9 个自然季度归母净利润（单季） | 上游明细表（default.dwd_stock_income.n_income_attr_p） | — |
| `n_income_attr_p_mrq_9` | 向前第 10 个自然季度归母净利润（单季） | 上游明细表（default.dwd_stock_income.n_income_attr_p） | — |
| `n_income_attr_p_mrq_10` | 向前第 11 个自然季度归母净利润（单季） | 上游明细表（default.dwd_stock_income.n_income_attr_p） | — |
| `n_income_attr_p_mrq_11` | 向前第 12 个自然季度归母净利润（单季） | 上游明细表（default.dwd_stock_income.n_income_attr_p） | — |
| `n_income_attr_p_mrq_12` | 向前第 13 个自然季度归母净利润（单季） | 上游明细表（default.dwd_stock_income.n_income_attr_p） | — |
| `accounts_receiv_bill_mrq_1` | 向前第 2 个自然季度应收票据及应收账款余额 | 上游明细表（default.dwd_stock_balance_sheet.accounts_receiv_bill） | — |
| `accounts_receiv_bill_mrq_2` | 向前第 3 个自然季度应收票据及应收账款余额 | 上游明细表（default.dwd_stock_balance_sheet.accounts_receiv_bill） | — |
| `accounts_receiv_bill_mrq_3` | 向前第 4 个自然季度应收票据及应收账款余额 | 上游明细表（default.dwd_stock_balance_sheet.accounts_receiv_bill） | — |
| `accounts_receiv_bill_mrq_5` | 向前第 6 个自然季度应收票据及应收账款余额 | 上游明细表（default.dwd_stock_balance_sheet.accounts_receiv_bill） | — |
| `accounts_receiv_bill_mrq_6` | 向前第 7 个自然季度应收票据及应收账款余额 | 上游明细表（default.dwd_stock_balance_sheet.accounts_receiv_bill） | — |
| `accounts_receiv_bill_mrq_7` | 向前第 8 个自然季度应收票据及应收账款余额 | 上游明细表（default.dwd_stock_balance_sheet.accounts_receiv_bill） | — |
| `accounts_receiv_bill_mrq_8` | 向前第 9 个自然季度应收票据及应收账款余额 | 上游明细表（default.dwd_stock_balance_sheet.accounts_receiv_bill） | — |
| `accounts_receiv_bill_mrq_9` | 向前第 10 个自然季度应收票据及应收账款余额 | 上游明细表（default.dwd_stock_balance_sheet.accounts_receiv_bill） | — |
| `accounts_receiv_mrq_9` | 向前第 10 个自然季度应收账款余额 | 上游明细表（default.dwd_stock_balance_sheet.accounts_receiv） | — |
| `notes_receiv_mrq_9` | 向前第 10 个自然季度应收票据余额 | 上游明细表（default.dwd_stock_balance_sheet.notes_receiv） | — |
| `inventories_mrq_9` | 向前第 10 个自然季度存货余额 | 上游明细表（default.dwd_stock_balance_sheet.inventories） | — |
| `prepayment_mrq_9` | 向前第 10 个自然季度预付款项余额 | 上游明细表（default.dwd_stock_balance_sheet.prepayment） | — |
| `rd_exp_lyr_1` | 最近可见年报向前1个自然财年的年报研发费用 | 上游明细表（default.dwd_stock_income.rd_exp） | — |
| `rd_exp_lyr_2` | 最近可见年报向前2个自然财年的年报研发费用 | 上游明细表（default.dwd_stock_income.rd_exp） | — |
| `rd_exp_lyr_3` | 最近可见年报向前3个自然财年的年报研发费用 | 上游明细表（default.dwd_stock_income.rd_exp） | — |
| `rd_exp_lyr_4` | 最近可见年报向前4个自然财年的年报研发费用 | 上游明细表（default.dwd_stock_income.rd_exp） | — |
| `rd_exp_lyr_5` | 最近可见年报向前5个自然财年的年报研发费用 | 上游明细表（default.dwd_stock_income.rd_exp） | — |
| `rd_exp_lyr_6` | 最近可见年报向前6个自然财年的年报研发费用 | 上游明细表（default.dwd_stock_income.rd_exp） | — |
| `rd_exp_lyr_7` | 最近可见年报向前7个自然财年的年报研发费用 | 上游明细表（default.dwd_stock_income.rd_exp） | — |
| `rd_exp_lyr_8` | 最近可见年报向前8个自然财年的年报研发费用 | 上游明细表（default.dwd_stock_income.rd_exp） | — |
| `rd_exp_lyr_9` | 最近可见年报向前9个自然财年的年报研发费用 | 上游明细表（default.dwd_stock_income.rd_exp） | — |
| `rd_exp_indicator_lyr_1` | 最近可见年报向前1个自然财年的年报研发投入（2018 年前回退） | 上游明细表候选（default.dwd_stock_financial_indicator.rd_exp；待核是否等于年报附注研发投入） | — |
| `rd_exp_indicator_lyr_2` | 最近可见年报向前2个自然财年的年报研发投入（2018 年前回退） | 上游明细表候选（default.dwd_stock_financial_indicator.rd_exp；待核是否等于年报附注研发投入） | — |
| `rd_exp_indicator_lyr_3` | 最近可见年报向前3个自然财年的年报研发投入（2018 年前回退） | 上游明细表候选（default.dwd_stock_financial_indicator.rd_exp；待核是否等于年报附注研发投入） | — |
| `rd_exp_indicator_lyr_4` | 最近可见年报向前4个自然财年的年报研发投入（2018 年前回退） | 上游明细表候选（default.dwd_stock_financial_indicator.rd_exp；待核是否等于年报附注研发投入） | — |
| `rd_exp_indicator_lyr_5` | 最近可见年报向前5个自然财年的年报研发投入（2018 年前回退） | 上游明细表候选（default.dwd_stock_financial_indicator.rd_exp；待核是否等于年报附注研发投入） | — |
| `rd_exp_indicator_lyr_6` | 最近可见年报向前6个自然财年的年报研发投入（2018 年前回退） | 上游明细表候选（default.dwd_stock_financial_indicator.rd_exp；待核是否等于年报附注研发投入） | — |
| `rd_exp_indicator_lyr_7` | 最近可见年报向前7个自然财年的年报研发投入（2018 年前回退） | 上游明细表候选（default.dwd_stock_financial_indicator.rd_exp；待核是否等于年报附注研发投入） | — |
| `rd_exp_indicator_lyr_8` | 最近可见年报向前8个自然财年的年报研发投入（2018 年前回退） | 上游明细表候选（default.dwd_stock_financial_indicator.rd_exp；待核是否等于年报附注研发投入） | — |
| `rd_exp_indicator_lyr_9` | 最近可见年报向前9个自然财年的年报研发投入（2018 年前回退） | 上游明细表候选（default.dwd_stock_financial_indicator.rd_exp；待核是否等于年报附注研发投入） | — |
| `sell_exp_lyr_1` | 最近可见年报向前1个自然财年的年报销售费用 | 上游明细表（default.dwd_stock_income.sell_exp） | — |
| `sell_exp_lyr_2` | 最近可见年报向前2个自然财年的年报销售费用 | 上游明细表（default.dwd_stock_income.sell_exp） | — |
| `sell_exp_lyr_3` | 最近可见年报向前3个自然财年的年报销售费用 | 上游明细表（default.dwd_stock_income.sell_exp） | — |
| `sell_exp_lyr_4` | 最近可见年报向前4个自然财年的年报销售费用 | 上游明细表（default.dwd_stock_income.sell_exp） | — |
| `sell_exp_lyr_5` | 最近可见年报向前5个自然财年的年报销售费用 | 上游明细表（default.dwd_stock_income.sell_exp） | — |
| `sell_exp_lyr_6` | 最近可见年报向前6个自然财年的年报销售费用 | 上游明细表（default.dwd_stock_income.sell_exp） | — |
| `sell_exp_lyr_7` | 最近可见年报向前7个自然财年的年报销售费用 | 上游明细表（default.dwd_stock_income.sell_exp） | — |
| `sell_exp_lyr_8` | 最近可见年报向前8个自然财年的年报销售费用 | 上游明细表（default.dwd_stock_income.sell_exp） | — |
| `sell_exp_lyr_9` | 最近可见年报向前9个自然财年的年报销售费用 | 上游明细表（default.dwd_stock_income.sell_exp） | — |
| `admin_exp_lyr_1` | 最近可见年报向前1个自然财年的年报管理费用 | 上游明细表（default.dwd_stock_income.admin_exp） | — |
| `admin_exp_lyr_2` | 最近可见年报向前2个自然财年的年报管理费用 | 上游明细表（default.dwd_stock_income.admin_exp） | — |
| `admin_exp_lyr_3` | 最近可见年报向前3个自然财年的年报管理费用 | 上游明细表（default.dwd_stock_income.admin_exp） | — |
| `admin_exp_lyr_4` | 最近可见年报向前4个自然财年的年报管理费用 | 上游明细表（default.dwd_stock_income.admin_exp） | — |
| `admin_exp_lyr_5` | 最近可见年报向前5个自然财年的年报管理费用 | 上游明细表（default.dwd_stock_income.admin_exp） | — |
| `admin_exp_lyr_6` | 最近可见年报向前6个自然财年的年报管理费用 | 上游明细表（default.dwd_stock_income.admin_exp） | — |
| `admin_exp_lyr_7` | 最近可见年报向前7个自然财年的年报管理费用 | 上游明细表（default.dwd_stock_income.admin_exp） | — |
| `admin_exp_lyr_8` | 最近可见年报向前8个自然财年的年报管理费用 | 上游明细表（default.dwd_stock_income.admin_exp） | — |
| `admin_exp_lyr_9` | 最近可见年报向前9个自然财年的年报管理费用 | 上游明细表（default.dwd_stock_income.admin_exp） | — |
| `up_limit` | 当日未复权涨停价 | 上游明细表（default.dwd_stock_limit.up_limit） | — |
| `down_limit` | 当日未复权跌停价 | 上游明细表（default.dwd_stock_limit.down_limit） | — |
| `top_list_flag` | 对应交易日龙虎榜入榜标记（盘后披露后方可用） | 上游明细表加工（default.top_list：ts_code、trade_date、_record_hash） | 按 `(ts_code,trade_date)` 去重，有记录记 1、源覆盖完整且无记录记 0、源缺档置空；盘后公布的 `trade_date` 事件仅从下一交易日起用于交易信号。 |
| `sw_l1_code` | 计算时点已生效且已可见的申万一级行业代码 | 上游明细表（default.dwd_sw_industry_member.l1_code） | — |
| `hf_std_5m` | 最近 21 个交易日五分钟收益标准差 | 上游明细表加工（default.ricequant_stock_minute：order_book_id、trading_date、datetime、close） | 汇集截至计算日连续 21 个交易日的有效日内五分钟收益 `r`，计算合并样本标准差 `sqrt((Σr²-(Σr)²/N)/(N-1))`；不跨午休、缺口或隔夜，`N<2` 置空。 |
| `hf_5m_return_count` | 当日有效五分钟区间收益条数 | 上游明细表加工（default.ricequant_stock_minute：order_book_id、trading_date、datetime、close） | 同一交易时段内以时间相邻且均为正的五分钟收盘价计算 `r=log(P_k/P_{k-1})`，统计当日有效 `r` 条数；不跨午休、缺口或隔夜。 |
| `hf_5m_return_sum` | 当日五分钟区间对数收益之和 | 上游明细表加工（default.ricequant_stock_minute：order_book_id、trading_date、datetime、close） | 对 `hf_5m_return_count` 所计的当日收益求 `Σr`；完整数据但无有效区间为 0，源缺档置空。 |
| `hf_5m_return_sum_sq` | 当日五分钟区间对数收益平方和 | 上游明细表加工（default.ricequant_stock_minute：order_book_id、trading_date、datetime、close） | 对 `hf_5m_return_count` 所计的当日收益求 `Σr²`；完整数据但无有效区间为 0，源缺档置空。 |
| `list_date` | 股票上市日期 | 上游明细表（default.stock_basic.list_date） | — |
| `holder_num_mrq_0` | 最新可见定期报告季度的股东户数 | 上游明细表（default.stk_holdernumber.holder_num） | — |
| `holder_num_mrq_1` | 上一自然季度定期报告的股东户数（缺期置空） | 上游明细表（default.stk_holdernumber.holder_num） | — |
| `northbound_hold_shares` | 计算时点最近已披露的陆股通持股数 | 上游明细表（default.dwd_stock_northbound_holding.vol） | — |
| `fund_report_hold_shares_total` | 最近已完整披露半年报或年报的公募基金持股合计数（仅基金代理） | 上游明细表加工（default.dwd_fund_portfolio.amount） | 仅取已确认完整披露的最近半年报或年报；同基金、股票、报告期保留可见最新版，汇总 `amount` 并统一为股；缺完整披露标记置空。 |
| `fund_report_holder_count` | 最近已完整披露半年报或年报持有该股的公募基金数（仅基金代理） | 上游明细表加工（default.dwd_fund_portfolio.fund_id/amount） | 同一完整披露报告期内，筛选 `amount>0`，按股票统计去重的基金产品 `fund_id` 数；缺完整披露标记置空，不作全机构家数。 |
| `national_team_hold_shares` | 最近可见报告期国家队持股数合计 | 上游明细表加工（default.top10_holders：ts_code、end_date、ann_date、holder_name、hold_amount、_record_hash；default.top10_floatholders：ts_code、end_date、ann_date、holder_name、hold_amount、_record_hash，仅作流通持仓补充核对） | 用固定国家队主体清单匹配两张前十表，按股票、报告期、主体去重：总持仓仅使用 `top10_holders.hold_amount` 求和；`top10_floatholders.hold_amount` 仅用于非限售持仓核对，不能替代总持仓，重叠主体需记录总持仓与非限售持仓的差异及影响；缺主体清单或持仓未知置空，不补 0。 |
| `national_team_free_hold_shares` | 最近已可见报告期国家队非限售持股数合计 | 上游明细表加工（default.top10_floatholders.hold_amount；国家队主体名单） | 用国家队主体清单匹配流通股东表，按股票、报告期、主体去重后求 `Σhold_amount`；本期跌出前十的主体最多沿用上一季值一次并标记估计，无上期值则置空。 |
| `national_team_hold_shares_prev_report` | 上一自然季度报告期国家队持股数合计 | 上游明细表加工（default.top10_holders：ts_code、end_date、ann_date、holder_name、hold_amount、_record_hash；default.top10_floatholders：ts_code、end_date、ann_date、holder_name、hold_amount、_record_hash，仅作流通持仓补充核对） | 取 `national_team_hold_shares` 最新报告期之前的相邻自然季度，仅对 `top10_holders.hold_amount` 按相同主体匹配和去重规则求和，流通表只作核对；该季度未披露或持仓未知置空。 |
| `national_team_report_close` | 最近可见国家队持仓报告期末最近交易日收盘价 | 上游明细表（default.dwd_stock_eod_price.close） | — |
| `national_team_report_close_prev_report` | 上一自然季度报告期末最近交易日收盘价 | 上游明细表（default.dwd_stock_eod_price.close） | — |
| `national_team_report_free_float_mv` | 最近可见国家队持仓报告期末自由流通市值（元） | 上游明细表加工（default.dwd_stock_daily_basic.free_share、default.dwd_stock_eod_price.close） | 取该持仓报告期末当日或之前最近交易日的 `free_share×close×10000` 元（`free_share` 单位万股）；任一项缺失置空。 |
| `national_team_hold_free_share_ratio` | 最近可见报告期国家队持股数／同期自由流通股本 | 上游明细表加工（default.top10_holders.hold_amount、default.dwd_stock_daily_basic.free_share） | 取 `national_team_hold_shares` 除以同报告期末最近交易日的 `free_share×10000` 股；分母非正或持仓未知置空。 |
| `national_team_hold_free_share_ratio_prev_report` | 上一自然季度国家队持股数／同期自由流通股本 | 上游明细表加工（default.top10_holders.hold_amount、default.dwd_stock_daily_basic.free_share） | 取 `national_team_hold_shares_prev_report` 除以该上一自然季度期末最近交易日的 `free_share×10000` 股；缺期或分母非正置空。 |
| `halfyear_depreciation` | 最近有效半年度折旧金额 | 上游明细表加工（default.dwd_stock_cashflow.depr_fa_coga_dpba） | 上半年取 6 月 30 日报告累计 `depr_fa_coga_dpba`；下半年取 12 月 31 日累计减同年 6 月 30 日累计；一季报、三季报期间沿用最近已披露半年值，所需报告缺失置空。 |
| `company_province` | 公司所在省份 | 上游明细表候选（default.stock_company.province；历史地址生效日待补） | — |
| `company_city` | 公司所在城市 | 上游明细表候选（default.stock_company.city；历史地址生效日待补） | — |
| `csi800_member` | 当日中证 800 成分资格 | 上游明细表加工（default.dwd_index_weight：index_code、con_code、weight、event_date、available_trade_date、sys_from） | 取计算日已可见且已生效的最新中证 800（`000906.SH`）权重快照；`weight>0` 记 1、快照完整但未入选记 0、快照缺失置空。 |
| `implemented_cash_dividend_12m_cny` | 过去 12 个月已实施现金分红总额 | 上游明细表加工（default.dwd_stock_dividend：div_proc、ex_date、available_trade_date、cash_div_tax、base_share） | 取 `div_proc='实施'`、`cash_div_tax>0`、除息日落在 `(t-12个月,t]` 且计算日已可见的事件，按公司行动去重后求 `Σcash_div_tax×base_share×10000` 元；`base_share` 为万股。 |
| `deferred_income_tax_ttm_0` | 最近四季递延所得税费用 | 上游明细表加工（default.dwd_stock_cashflow.decr_def_inc_tax_assets 与 incr_def_inc_tax_liab） | 每期按源字段自身正负号求 `decr_def_inc_tax_assets+incr_def_inc_tax_liab`，同年累计值先单季化，再汇总连续四季；缺任一季或源项置空。 |
| `analyst_np_consensus_fy0` | FY0 一致预期归母净利润 | 上游明细表加工（default.dwd_stock_research_report.np；财年定位使用最新可见定期财报报告期） | FY0 取最新可见定期财报所属财年；仅取同财年每机构最新 `np` 的等权均值乘 10000 元；财报实际净利润另作核对并报告与预测的差异及影响，不替代一致预期；无有效输入置空。 |
| `analyst_np_consensus_fy1` | FY1 一致预期归母净利润 | 上游明细表加工（default.dwd_stock_research_report.np） | FY1=FY0 后一财年；同一绝对预测年度每机构留最新 `np`，等权平均后乘 10000 元；对要求机构加权的原式，此值为等权近似。 |
| `analyst_np_consensus_fy2` | FY2 一致预期归母净利润 | 上游明细表加工（default.dwd_stock_research_report.np） | FY2=FY0 后两财年；同一绝对预测年度每机构留最新 `np`，等权平均后乘 10000 元；无有效预测置空。 |
| `analyst_np_consensus_fy3` | FY3 一致预期归母净利润 | 上游明细表加工（default.dwd_stock_research_report.np） | FY3=FY0 后三财年；同一绝对预测年度每机构留最新 `np`，等权平均后乘 10000 元；跨期比较始终匹配相同绝对年度。 |
| `analyst_bv_consensus_fy1` | FY1 预期归母净资产 | 上游明细表加工（FY1 预测净资产/BPS 直接源列缺失；近似源 default.dwd_stock_balance_sheet：total_hldr_eqy_exc_min_int、end_date、available_trade_date；default.dwd_stock_research_report：np、forecast_period_end、org_name、available_trade_date；历史留存率源 default.dwd_stock_income：n_income_attr_p、end_date、available_trade_date；default.dwd_stock_dividend：cash_div_tax、base_share、div_proc、ex_date、available_trade_date） | 近似 `BV_FY1=最近可见归母净资产+ρ×Σ_y(NP_y×报告期末次日至FY1年末落在y年的天数/y年总天数)`；`NP_y=该年每机构最新np等权均值×10000元`，`ρ=clip(1-最近3个完整财年已实施现金分红额/同期正归母净利润合计,0,1)`；缺预测或分母非正置空。 |
| `analyst_forward_pe_12m` | 未来 12 个月一致预期市盈率 | 上游明细表加工（default.dwd_stock_daily_basic：trade_date、total_mv；default.dwd_stock_research_report：np、forecast_period_end、org_name、report_date、available_trade_date） | 近似 `PE_NTM=当日total_mv×10000/[(1-w)×NP_当年+w×NP_次年]`，`w=当年已过日历天数/当年总天数`；各年 `NP` 为该绝对财年每机构最新预测等权均值（元），分母非正或缺预测置空。 |
| `analyst_np_mean_active_180d_cny` | 近 180 日有效预测财年机构净利润均值（元） | 上游明细表加工（default.dwd_stock_research_report.np） | 目标财年取截至 `t` 最近尚未披露正式年报的年度；在 `(t-180日,t]` 取该年每机构最新 `np`，至少 3 家时等权平均乘 10000 元，否则置空。 |
| `analyst_eps_mean_active_90d` | 近 90 日有效预测财年机构 EPS 均值 | 上游明细表加工（default.dwd_stock_research_report.eps） | 目标财年取截至 `t` 最近尚未披露正式年报的年度；在 `(t-90日,t]` 取该年每机构最新 EPS 等权平均，无有效机构置空。 |
| `analyst_eps_dispersion_active_90d` | 近 90 日机构 EPS 预测分歧度 | 上游明细表加工（default.dwd_stock_research_report.eps） | 在 `(t-90日,t]` 取计算日所属自然年每机构最新 EPS；机构数至少 5 且 `abs(均值)≥0.05 元/股` 时求 `样本标准差/abs(均值)`，否则置空。 |
| `analyst_eps_dispersion_active_91d` | 近 91 日机构 EPS 预测分歧度 | 上游明细表加工（default.dwd_stock_research_report.eps） | 在 `(t-91日,t]` 取计算日所属自然年每机构最新 EPS；机构数至少 5 且 `abs(均值)≥0.05 元/股` 时求 `样本标准差/abs(均值)`，否则置空。 |
| `analyst_org_coverage_90d` | 近 90 日覆盖机构数 | 上游明细表加工（default.dwd_stock_research_report.org_name） | 对 `(t-90日,t]` 已发布研报的非空 `org_name` 去重计数；完整源中无记录为 0，源缺档置空。 |
| `analyst_org_year_pair_count_90d` | 近 90 日机构—预测年度去重配对数 | 上游明细表加工（default.dwd_stock_research_report.org_name 与 forecast_period_end） | 对 `(t-90日,t]` 盈利预测的 `(org_name,forecast_period_end所属财年)` 去重计数；机构或预测年缺失不计。 |
| `analyst_target_price_mean_90d` | 近 90 日各机构最新目标价均值 | 上游明细表加工（default.dwd_stock_research_report：min_price、max_price、org_name、report_date、available_trade_date；单一目标价源列缺失） | 近似逐篇目标价 `TP=(min_price+max_price)/2`，仅取 `0<min_price≤max_price`；在 `(t-90日,t]` 每机构留最新有效 `TP` 后等权平均，无有效机构置空。 |
| `research_records` | 研报逐篇预测记录结构化数组 | 上游明细表加工（default.dwd_stock_research_report：ts_code、report_date、available_trade_date、forecast_period_end、org_name、author_name、min_price、max_price、eps、np、pe、roe、source_record_hash） | `Array(Tuple(record_id String, report_date Date, available_trade_date Date, forecast_period_end Nullable(Date), org_name Nullable(String), author_name Nullable(String), min_price Nullable(Float64), max_price Nullable(Float64), eps Nullable(Float64), np Nullable(Float64), pe Nullable(Float64), roe Nullable(Float64)))`；股票键=`ts_code`，`record_id=source_record_hash`，其余字段同名映射；仅收录计算日已可见版本，按哈希去完全重复记录，`np` 保留源表万元单位。 |
| `fund_holding_records` | 公募基金逐基金持仓记录结构化数组 | 上游明细表加工（default.dwd_fund_portfolio：ts_code、symbol、source_code、fund_id、end_date、ann_date、available_trade_date、amount、mkv、stk_mkv_ratio、source_record_hash；完整持仓标记源列缺失） | `Array(Tuple(record_id String, fund_id Nullable(String), fund_code Nullable(String), report_date Date, available_trade_date Date, is_complete_holdings Nullable(UInt8), amount Nullable(Float64), market_value Nullable(Float64), stock_market_value_ratio Nullable(Float64)))`；股票键=`symbol`，基金代码=`ts_code`，报告期=`end_date`，市值=`mkv`，比例=`stk_mkv_ratio`，ID=`source_record_hash`；仅收录已可见版本并按哈希去重，完整持仓标记未补齐时填 NULL，不得填 1。 |
| `ccass_holding_records` | CCASS 逐参与者持仓记录结构化数组 | 上游明细表加工（default.ccass_hold_detail：ts_code、trade_date、col_participant_id、col_participant_name、col_shareholding、col_shareholding_percent、_record_hash；历史可用日源列缺失） | `Array(Tuple(record_id String, holding_date Date, available_trade_date Date, participant_id String, participant_name Nullable(String), shareholding Nullable(Float64), shareholding_percent Nullable(Float64)))`；股票键=`ts_code`，持仓日=`trade_date`，参与者字段取 `col_participant_*`，股数去千分位后转数值、百分比转 0～1 比例，ID=`_record_hash`；历史可用日未补齐时不产出该数组，不能用持仓日冒充披露日。 |
| `main_business_records` | 主营业务逐分类记录结构化数组 | 上游明细表加工（default.fina_mainbz：ts_code、end_date、bz_code、bz_item、bz_sales、curr_type、_record_hash；公告日及历史可用日源列缺失） | `Array(Tuple(record_id String, report_date Date, available_trade_date Date, bz_code Nullable(String), bz_item Nullable(String), sales Nullable(Float64), curr_type Nullable(String)))`；股票键=`ts_code`，报告期=`end_date`，销售额=`bz_sales`，ID=`_record_hash`，保留 `P/D/I` 分类和币种；历史披露可用日未补齐时不产出该数组，不能按报告期末回填。 |
| `top_holder_records` | 前十大股东逐主体持仓记录结构化数组 | 上游明细表加工（default.top10_holders、default.top10_floatholders：ts_code、end_date、ann_date、holder_name、holder_type、hold_amount、hold_ratio、hold_float_ratio、_record_hash） | `Array(Tuple(record_id String, report_date Date, available_trade_date Date, source_kind String, holder_name String, holder_type Nullable(String), hold_amount Nullable(Float64), hold_ratio Nullable(Float64), hold_float_ratio Nullable(Float64)))`；股票键=`ts_code`，报告期=`end_date`，ID=`_record_hash`，`source_kind` 取源表名；`ann_date` 无日内时刻时自下一交易日可用，按可见版本及 `(报告期,源表,主体)` 去重，两表同主体留待汇总时去重。 |

## 说明
- **取期口径**：本候选合同规定 `_mrq_N` 为最新可见季度向前 N 个自然季度（流量先单季化、存量取期末），`_ttm_N` 为从该期起连续四季，`_lyr_N` 为最新可见年报所在财年向前 N 个自然财年；缺自然季度/财年置空，不能跳到更早可见记录。V2 字典 `/nfs_data/dong.wang/Project/QuantitativeTrading_offline_data_service/docs/dws_stock_factor_wide_tushare_lineage.md` 使用 `report_offset` 术语，不能仅凭同名推定 V2 历史数据已满足此自然期间合同；原始写入 SQL 与数值仍须验收。
- **PIT 与数组**：`report_date`、`available_trade_date` 等只可作数组元素/上游明细的事件元数据，不新增为股票日顶层单值列；`sys_from` 留在长表血缘层。候选 ClickHouse `Array(Tuple(...))` 导出 Parquet 时对应 `list<struct<...>>`；快照只含计算时点已可见记录，以稳定 `record_id` 保留身份/期间/数值并区分确无记录与源缺失。核对单位及版本；长表仍是权威源，跨股票关系可继续直接读长表。
- **近似与缺口**：标有“近似”或“代理”的字段按表内公式验收，不等于严格复现原文；拆合股历史可用日、CCASS/主营业务可用日、基金完整持仓标记或国家队主体名单缺失时，相应字段置空。
