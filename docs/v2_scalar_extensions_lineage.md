# V2 Tushare 标量扩展字段血缘

本次原清单 236 项：实现 214 个标量、13 个 NULL 占位、排除 4 个米筐字段及 5 个数组。合计新增 227 列，V2 总列数 1968。

本表“数组排除”指不写入 v2 宽表。后续需求的六张数组相关 DWD 明细及日期/版本限制见 [数组 DWD 说明](v2_array_dwd_pit.md)。

财务 MRQ/TTM/LYR 以现有 V2 固定自然期间为准，覆盖文档的“最新可见期”描述。TTM 四份报告必须存在，金额字段按非空季度均值乘四；不存在的期间不跳期。

数值单位、源字段原义和近似限制以各行说明为准；不按年份混用两种研发费用，不把固定资产合计解释为已核实净固定资产。

| 文档字段 / 最终列名 | 状态 | 单位 | 实际来源或处理 |
|---|---|---|---|
| `accounts_pay_mrq_0` | 实现 | 元 | balancesheet.accounts_pay / mrq_0； |
| `accounts_pay_mrq_4` | 实现 | 元 | balancesheet.accounts_pay / mrq_4； |
| `accounts_receiv_bill_mrq_0` | 实现 | 元 | balancesheet.accounts_receiv_bill / mrq_0； |
| `accounts_receiv_bill_mrq_4` | 实现 | 元 | balancesheet.accounts_receiv_bill / mrq_4； |
| `bench_ret` | 实现 | 无量纲 | 上游明细表加工（default.dwd_index_eod_price.pct_chg）； |
| `debt_invest_mrq_0` | 实现 | 元 | balancesheet.debt_invest / mrq_0； |
| `debt_invest_mrq_4` | 实现 | 元 | balancesheet.debt_invest / mrq_4； |
| `defer_tax_assets_mrq_0` | 实现 | 元 | balancesheet.defer_tax_assets / mrq_0； |
| `fa_avail_for_sale_mrq_0` | 实现 | 元 | balancesheet.fa_avail_for_sale / mrq_0； |
| `fa_avail_for_sale_mrq_4` | 实现 | 元 | balancesheet.fa_avail_for_sale / mrq_4； |
| `fix_assets_total_mrq_0` | 实现 | 元 | balancesheet.fix_assets_total / mrq_0；按源原义提供，不声明与文档候选业务含义等价；不跨源替代 |
| `fix_assets_total_mrq_1` | 实现 | 元 | balancesheet.fix_assets_total / mrq_1；按源原义提供，不声明与文档候选业务含义等价；不跨源替代 |
| `htm_invest_mrq_0` | 实现 | 元 | balancesheet.htm_invest / mrq_0； |
| `htm_invest_mrq_4` | 实现 | 元 | balancesheet.htm_invest / mrq_4； |
| `intan_assets_mrq_0` | 实现 | 元 | balancesheet.intan_assets / mrq_0； |
| `lt_amor_exp_mrq_0` | 实现 | 元 | balancesheet.lt_amor_exp / mrq_0； |
| `lt_eqt_invest_mrq_0` | 实现 | 元 | balancesheet.lt_eqt_invest / mrq_0； |
| `lt_eqt_invest_mrq_4` | 实现 | 元 | balancesheet.lt_eqt_invest / mrq_4； |
| `non_cur_liab_due_1y_mrq_0` | 实现 | 元 | balancesheet.non_cur_liab_due_1y / mrq_0； |
| `non_cur_liab_due_1y_mrq_4` | 实现 | 元 | balancesheet.non_cur_liab_due_1y / mrq_4； |
| `notes_payable_mrq_0` | 实现 | 元 | balancesheet.notes_payable / mrq_0； |
| `notes_payable_mrq_4` | 实现 | 元 | balancesheet.notes_payable / mrq_4； |
| `oth_debt_invest_mrq_0` | 实现 | 元 | balancesheet.oth_debt_invest / mrq_0； |
| `oth_debt_invest_mrq_4` | 实现 | 元 | balancesheet.oth_debt_invest / mrq_4； |
| `oth_eq_invest_mrq_0` | 实现 | 元 | balancesheet.oth_eq_invest / mrq_0； |
| `oth_eq_invest_mrq_4` | 实现 | 元 | balancesheet.oth_eq_invest / mrq_4； |
| `oth_eq_ppbond_mrq_0` | 实现 | 元 | balancesheet.oth_eq_ppbond / mrq_0； |
| `oth_eq_ppbond_mrq_4` | 实现 | 元 | balancesheet.oth_eq_ppbond / mrq_4； |
| `oth_eqt_tools_p_shr_mrq_0` | 实现 | 元 | balancesheet.oth_eqt_tools_p_shr / mrq_0； |
| `oth_eqt_tools_p_shr_mrq_4` | 实现 | 元 | balancesheet.oth_eqt_tools_p_shr / mrq_4； |
| `r_and_d_mrq_0` | 实现 | 元 | balancesheet.r_and_d / mrq_0； |
| `st_borr_mrq_0` | 实现 | 元 | balancesheet.st_borr / mrq_0； |
| `st_borr_mrq_1` | 实现 | 元 | balancesheet.st_borr / mrq_1； |
| `st_borr_mrq_4` | 实现 | 元 | balancesheet.st_borr / mrq_4； |
| `total_share_mrq_0` | 实现 | 股 | balancesheet.total_share / mrq_0； |
| `total_share_mrq_4` | 实现 | 股 | balancesheet.total_share / mrq_4； |
| `trading_fl_mrq_0` | 实现 | 元 | balancesheet.trading_fl / mrq_0； |
| `trading_fl_mrq_4` | 实现 | 元 | balancesheet.trading_fl / mrq_4； |
| `share_action_factor` | NULL占位 | 无量纲 | 上游明细表加工（default.dwd_stock_dividend：ts_code、div_proc、stk_div、ex_date、available_trade_date、sys_from、sys_to、source_record_hash；default.ricequant_stock_split：order_book_id、ex_dividend_date、split_coefficient_from、split_coefficient_to、cum_factor、rice_create_tm、_record_hash）；缺少完整且可按历史可用日验证的拆合股数据；不接入米筐 |
| `diluted_weighted_share_mrq_0` | 实现 | 股 | 上游明细表加工（稀释加权股本直接源列缺失；近似源 default.dwd_stock_balance_sheet.total_share）；期末总股本代理；不是已披露稀释加权平均股本 |
| `diluted_weighted_share_mrq_4` | 实现 | 股 | 上游明细表加工（稀释加权股本直接源列缺失；近似源 default.dwd_stock_balance_sheet.total_share）；期末总股本代理；不是已披露稀释加权平均股本 |
| `contract_liab_mrq_0` | 实现 | 元 | balancesheet.contract_liab / mrq_0； |
| `contract_liab_mrq_4` | 实现 | 元 | balancesheet.contract_liab / mrq_4； |
| `oth_comp_income_mrq_4` | 实现 | 元 | balancesheet.oth_comp_income / mrq_4； |
| `assets_impair_loss_ttm_0` | 实现 | 元 | income.assets_impair_loss / ttm_0； |
| `rd_exp_ttm_0` | 实现 | 元 | income.rd_exp / ttm_0； |
| `sell_exp_ttm_0` | 实现 | 元 | income.sell_exp / ttm_0； |
| `admin_exp_ttm_0` | 实现 | 元 | income.admin_exp / ttm_0； |
| `rd_exp_lyr_0` | 实现 | 元 | income.rd_exp / lyr_0； |
| `rd_exp_indicator_lyr_0` | 实现 | 元 | fina_indicator.rd_exp / lyr_0；按源原义提供，不声明与文档候选业务含义等价；不跨源替代 |
| `sell_exp_lyr_0` | 实现 | 元 | income.sell_exp / lyr_0； |
| `admin_exp_lyr_0` | 实现 | 元 | income.admin_exp / lyr_0； |
| `c_fr_sale_sg_mrq_0` | 实现 | 元 | cashflow.c_fr_sale_sg / mrq_0； |
| `c_fr_sale_sg_mrq_1` | 实现 | 元 | cashflow.c_fr_sale_sg / mrq_1； |
| `c_fr_sale_sg_mrq_2` | 实现 | 元 | cashflow.c_fr_sale_sg / mrq_2； |
| `c_fr_sale_sg_mrq_3` | 实现 | 元 | cashflow.c_fr_sale_sg / mrq_3； |
| `c_fr_sale_sg_mrq_4` | 实现 | 元 | cashflow.c_fr_sale_sg / mrq_4； |
| `c_fr_sale_sg_mrq_5` | 实现 | 元 | cashflow.c_fr_sale_sg / mrq_5； |
| `c_fr_sale_sg_mrq_6` | 实现 | 元 | cashflow.c_fr_sale_sg / mrq_6； |
| `c_fr_sale_sg_mrq_7` | 实现 | 元 | cashflow.c_fr_sale_sg / mrq_7； |
| `c_fr_sale_sg_mrq_8` | 实现 | 元 | cashflow.c_fr_sale_sg / mrq_8； |
| `c_fr_sale_sg_mrq_9` | 实现 | 元 | cashflow.c_fr_sale_sg / mrq_9； |
| `c_pay_acq_const_fiolta_mrq_0` | 实现 | 元 | cashflow.c_pay_acq_const_fiolta / mrq_0； |
| `c_pay_acq_const_fiolta_mrq_4` | 实现 | 元 | cashflow.c_pay_acq_const_fiolta / mrq_4； |
| `n_recp_disp_fiolta_mrq_0` | 实现 | 元 | cashflow.n_recp_disp_fiolta / mrq_0； |
| `n_recp_disp_fiolta_mrq_4` | 实现 | 元 | cashflow.n_recp_disp_fiolta / mrq_4； |
| `revenue_ttm_12` | 实现 | 元 | income.revenue / ttm_12； |
| `c_pay_acq_const_fiolta_ttm_0` | 实现 | 元 | cashflow.c_pay_acq_const_fiolta / ttm_0； |
| `c_pay_acq_const_fiolta_ttm_4` | 实现 | 元 | cashflow.c_pay_acq_const_fiolta / ttm_4； |
| `c_pay_acq_const_fiolta_ttm_8` | 实现 | 元 | cashflow.c_pay_acq_const_fiolta / ttm_8； |
| `c_pay_acq_const_fiolta_ttm_12` | 实现 | 元 | cashflow.c_pay_acq_const_fiolta / ttm_12； |
| `n_recp_disp_fiolta_ttm_0` | 实现 | 元 | cashflow.n_recp_disp_fiolta / ttm_0； |
| `n_recp_disp_fiolta_ttm_4` | 实现 | 元 | cashflow.n_recp_disp_fiolta / ttm_4； |
| `n_recp_disp_fiolta_ttm_8` | 实现 | 元 | cashflow.n_recp_disp_fiolta / ttm_8； |
| `n_recp_disp_fiolta_ttm_12` | 实现 | 元 | cashflow.n_recp_disp_fiolta / ttm_12； |
| `stot_out_inv_act_mrq_0` | 实现 | 元 | cashflow.stot_out_inv_act / mrq_0； |
| `n_income_mrq_0` | 实现 | 元 | income.n_income / mrq_0； |
| `n_income_mrq_4` | 实现 | 元 | income.n_income / mrq_4； |
| `total_profit_mrq_0` | 实现 | 元 | income.total_profit / mrq_0； |
| `total_profit_mrq_4` | 实现 | 元 | income.total_profit / mrq_4； |
| `oper_cost_mrq_0` | 实现 | 元 | income.oper_cost / mrq_0； |
| `oper_cost_mrq_4` | 实现 | 元 | income.oper_cost / mrq_4； |
| `sell_exp_mrq_0` | 实现 | 元 | income.sell_exp / mrq_0； |
| `sell_exp_mrq_4` | 实现 | 元 | income.sell_exp / mrq_4； |
| `admin_exp_mrq_0` | 实现 | 元 | income.admin_exp / mrq_0； |
| `admin_exp_mrq_4` | 实现 | 元 | income.admin_exp / mrq_4； |
| `fin_exp_mrq_0` | 实现 | 元 | income.fin_exp / mrq_0； |
| `fin_exp_mrq_4` | 实现 | 元 | income.fin_exp / mrq_4； |
| `rd_exp_mrq_0` | 实现 | 元 | income.rd_exp / mrq_0； |
| `rd_exp_mrq_4` | 实现 | 元 | income.rd_exp / mrq_4； |
| `compr_inc_attr_p_mrq_0` | 实现 | 元 | income.compr_inc_attr_p / mrq_0； |
| `t_compr_income_mrq_0` | 实现 | 元 | income.t_compr_income / mrq_0； |
| `oth_income_mrq_0` | 实现 | 元 | income.oth_income / mrq_0； |
| `asset_disp_income_mrq_0` | 实现 | 元 | income.asset_disp_income / mrq_0； |
| `c_paid_to_for_empl_mrq_0` | 实现 | 元 | cashflow.c_paid_to_for_empl / mrq_0； |
| `use_right_asset_dep_lyr_0` | 实现 | 元 | cashflow.use_right_asset_dep / lyr_0； |
| `use_right_asset_dep_lyr_1` | 实现 | 元 | cashflow.use_right_asset_dep / lyr_1； |
| `basic_eps_mrq_0` | 实现 | 元/股 | income.basic_eps / mrq_0； |
| `basic_eps_mrq_1` | 实现 | 元/股 | income.basic_eps / mrq_1； |
| `basic_eps_mrq_2` | 实现 | 元/股 | income.basic_eps / mrq_2； |
| `basic_eps_mrq_3` | 实现 | 元/股 | income.basic_eps / mrq_3； |
| `basic_eps_mrq_4` | 实现 | 元/股 | income.basic_eps / mrq_4； |
| `basic_eps_mrq_5` | 实现 | 元/股 | income.basic_eps / mrq_5； |
| `basic_eps_mrq_6` | 实现 | 元/股 | income.basic_eps / mrq_6； |
| `basic_eps_mrq_7` | 实现 | 元/股 | income.basic_eps / mrq_7； |
| `basic_eps_mrq_8` | 实现 | 元/股 | income.basic_eps / mrq_8； |
| `basic_eps_mrq_9` | 实现 | 元/股 | income.basic_eps / mrq_9； |
| `basic_eps_mrq_10` | 实现 | 元/股 | income.basic_eps / mrq_10； |
| `basic_eps_mrq_11` | 实现 | 元/股 | income.basic_eps / mrq_11； |
| `basic_eps_mrq_12` | 实现 | 元/股 | income.basic_eps / mrq_12； |
| `basic_eps_lyr_5` | 实现 | 元/股 | income.basic_eps / lyr_5； |
| `basic_eps_lyr_6` | 实现 | 元/股 | income.basic_eps / lyr_6； |
| `basic_eps_lyr_7` | 实现 | 元/股 | income.basic_eps / lyr_7； |
| `basic_eps_lyr_8` | 实现 | 元/股 | income.basic_eps / lyr_8； |
| `basic_eps_lyr_9` | 实现 | 元/股 | income.basic_eps / lyr_9； |
| `basic_eps_lyr_10` | 实现 | 元/股 | income.basic_eps / lyr_10； |
| `revenue_mrq_0` | 实现 | 元 | income.revenue / mrq_0； |
| `revenue_mrq_1` | 实现 | 元 | income.revenue / mrq_1； |
| `revenue_mrq_2` | 实现 | 元 | income.revenue / mrq_2； |
| `revenue_mrq_3` | 实现 | 元 | income.revenue / mrq_3； |
| `revenue_mrq_4` | 实现 | 元 | income.revenue / mrq_4； |
| `revenue_mrq_5` | 实现 | 元 | income.revenue / mrq_5； |
| `revenue_mrq_6` | 实现 | 元 | income.revenue / mrq_6； |
| `revenue_mrq_7` | 实现 | 元 | income.revenue / mrq_7； |
| `revenue_mrq_8` | 实现 | 元 | income.revenue / mrq_8； |
| `revenue_mrq_9` | 实现 | 元 | income.revenue / mrq_9； |
| `revenue_mrq_10` | 实现 | 元 | income.revenue / mrq_10； |
| `revenue_mrq_11` | 实现 | 元 | income.revenue / mrq_11； |
| `revenue_mrq_12` | 实现 | 元 | income.revenue / mrq_12； |
| `n_income_attr_p_mrq_0` | 实现 | 元 | income.n_income_attr_p / mrq_0； |
| `n_income_attr_p_mrq_1` | 实现 | 元 | income.n_income_attr_p / mrq_1； |
| `n_income_attr_p_mrq_2` | 实现 | 元 | income.n_income_attr_p / mrq_2； |
| `n_income_attr_p_mrq_3` | 实现 | 元 | income.n_income_attr_p / mrq_3； |
| `n_income_attr_p_mrq_4` | 实现 | 元 | income.n_income_attr_p / mrq_4； |
| `n_income_attr_p_mrq_5` | 实现 | 元 | income.n_income_attr_p / mrq_5； |
| `n_income_attr_p_mrq_6` | 实现 | 元 | income.n_income_attr_p / mrq_6； |
| `n_income_attr_p_mrq_7` | 实现 | 元 | income.n_income_attr_p / mrq_7； |
| `n_income_attr_p_mrq_8` | 实现 | 元 | income.n_income_attr_p / mrq_8； |
| `n_income_attr_p_mrq_9` | 实现 | 元 | income.n_income_attr_p / mrq_9； |
| `n_income_attr_p_mrq_10` | 实现 | 元 | income.n_income_attr_p / mrq_10； |
| `n_income_attr_p_mrq_11` | 实现 | 元 | income.n_income_attr_p / mrq_11； |
| `n_income_attr_p_mrq_12` | 实现 | 元 | income.n_income_attr_p / mrq_12； |
| `accounts_receiv_bill_mrq_1` | 实现 | 元 | balancesheet.accounts_receiv_bill / mrq_1； |
| `accounts_receiv_bill_mrq_2` | 实现 | 元 | balancesheet.accounts_receiv_bill / mrq_2； |
| `accounts_receiv_bill_mrq_3` | 实现 | 元 | balancesheet.accounts_receiv_bill / mrq_3； |
| `accounts_receiv_bill_mrq_5` | 实现 | 元 | balancesheet.accounts_receiv_bill / mrq_5； |
| `accounts_receiv_bill_mrq_6` | 实现 | 元 | balancesheet.accounts_receiv_bill / mrq_6； |
| `accounts_receiv_bill_mrq_7` | 实现 | 元 | balancesheet.accounts_receiv_bill / mrq_7； |
| `accounts_receiv_bill_mrq_8` | 实现 | 元 | balancesheet.accounts_receiv_bill / mrq_8； |
| `accounts_receiv_bill_mrq_9` | 实现 | 元 | balancesheet.accounts_receiv_bill / mrq_9； |
| `accounts_receiv_mrq_9` | 实现 | 元 | balancesheet.accounts_receiv / mrq_9； |
| `notes_receiv_mrq_9` | 实现 | 元 | balancesheet.notes_receiv / mrq_9； |
| `inventories_mrq_9` | 实现 | 元 | balancesheet.inventories / mrq_9； |
| `prepayment_mrq_9` | 实现 | 元 | balancesheet.prepayment / mrq_9； |
| `rd_exp_lyr_1` | 实现 | 元 | income.rd_exp / lyr_1； |
| `rd_exp_lyr_2` | 实现 | 元 | income.rd_exp / lyr_2； |
| `rd_exp_lyr_3` | 实现 | 元 | income.rd_exp / lyr_3； |
| `rd_exp_lyr_4` | 实现 | 元 | income.rd_exp / lyr_4； |
| `rd_exp_lyr_5` | 实现 | 元 | income.rd_exp / lyr_5； |
| `rd_exp_lyr_6` | 实现 | 元 | income.rd_exp / lyr_6； |
| `rd_exp_lyr_7` | 实现 | 元 | income.rd_exp / lyr_7； |
| `rd_exp_lyr_8` | 实现 | 元 | income.rd_exp / lyr_8； |
| `rd_exp_lyr_9` | 实现 | 元 | income.rd_exp / lyr_9； |
| `rd_exp_indicator_lyr_1` | 实现 | 元 | fina_indicator.rd_exp / lyr_1；按源原义提供，不声明与文档候选业务含义等价；不跨源替代 |
| `rd_exp_indicator_lyr_2` | 实现 | 元 | fina_indicator.rd_exp / lyr_2；按源原义提供，不声明与文档候选业务含义等价；不跨源替代 |
| `rd_exp_indicator_lyr_3` | 实现 | 元 | fina_indicator.rd_exp / lyr_3；按源原义提供，不声明与文档候选业务含义等价；不跨源替代 |
| `rd_exp_indicator_lyr_4` | 实现 | 元 | fina_indicator.rd_exp / lyr_4；按源原义提供，不声明与文档候选业务含义等价；不跨源替代 |
| `rd_exp_indicator_lyr_5` | 实现 | 元 | fina_indicator.rd_exp / lyr_5；按源原义提供，不声明与文档候选业务含义等价；不跨源替代 |
| `rd_exp_indicator_lyr_6` | 实现 | 元 | fina_indicator.rd_exp / lyr_6；按源原义提供，不声明与文档候选业务含义等价；不跨源替代 |
| `rd_exp_indicator_lyr_7` | 实现 | 元 | fina_indicator.rd_exp / lyr_7；按源原义提供，不声明与文档候选业务含义等价；不跨源替代 |
| `rd_exp_indicator_lyr_8` | 实现 | 元 | fina_indicator.rd_exp / lyr_8；按源原义提供，不声明与文档候选业务含义等价；不跨源替代 |
| `rd_exp_indicator_lyr_9` | 实现 | 元 | fina_indicator.rd_exp / lyr_9；按源原义提供，不声明与文档候选业务含义等价；不跨源替代 |
| `sell_exp_lyr_1` | 实现 | 元 | income.sell_exp / lyr_1； |
| `sell_exp_lyr_2` | 实现 | 元 | income.sell_exp / lyr_2； |
| `sell_exp_lyr_3` | 实现 | 元 | income.sell_exp / lyr_3； |
| `sell_exp_lyr_4` | 实现 | 元 | income.sell_exp / lyr_4； |
| `sell_exp_lyr_5` | 实现 | 元 | income.sell_exp / lyr_5； |
| `sell_exp_lyr_6` | 实现 | 元 | income.sell_exp / lyr_6； |
| `sell_exp_lyr_7` | 实现 | 元 | income.sell_exp / lyr_7； |
| `sell_exp_lyr_8` | 实现 | 元 | income.sell_exp / lyr_8； |
| `sell_exp_lyr_9` | 实现 | 元 | income.sell_exp / lyr_9； |
| `admin_exp_lyr_1` | 实现 | 元 | income.admin_exp / lyr_1； |
| `admin_exp_lyr_2` | 实现 | 元 | income.admin_exp / lyr_2； |
| `admin_exp_lyr_3` | 实现 | 元 | income.admin_exp / lyr_3； |
| `admin_exp_lyr_4` | 实现 | 元 | income.admin_exp / lyr_4； |
| `admin_exp_lyr_5` | 实现 | 元 | income.admin_exp / lyr_5； |
| `admin_exp_lyr_6` | 实现 | 元 | income.admin_exp / lyr_6； |
| `admin_exp_lyr_7` | 实现 | 元 | income.admin_exp / lyr_7； |
| `admin_exp_lyr_8` | 实现 | 元 | income.admin_exp / lyr_8； |
| `admin_exp_lyr_9` | 实现 | 元 | income.admin_exp / lyr_9； |
| `up_limit` | 实现 | 元/股 | 上游明细表（default.dwd_stock_limit.up_limit）； |
| `down_limit` | 实现 | 元/股 | 上游明细表（default.dwd_stock_limit.down_limit）； |
| `top_list_flag` | 实现 | 0/1；无法确认缺失时NULL | dwd_stock_top_list ← top_list_raw；对应交易日事件，下一交易日起可用；无记录且缺覆盖证明为NULL； |
| `sw_l1_code` | 实现 | 文本/代码 | 上游明细表（default.dwd_sw_industry_member.l1_code）； |
| `hf_std_5m` | 排除 | 元 | 上游明细表加工（default.ricequant_stock_minute：order_book_id、trading_date、datetime、close）；米筐高频字段不在本次范围 |
| `hf_5m_return_count` | 排除 | 个 | 上游明细表加工（default.ricequant_stock_minute：order_book_id、trading_date、datetime、close）；米筐高频字段不在本次范围 |
| `hf_5m_return_sum` | 排除 | 元 | 上游明细表加工（default.ricequant_stock_minute：order_book_id、trading_date、datetime、close）；米筐高频字段不在本次范围 |
| `hf_5m_return_sum_sq` | 排除 | 元 | 上游明细表加工（default.ricequant_stock_minute：order_book_id、trading_date、datetime、close）；米筐高频字段不在本次范围 |
| `list_date` | 实现 | 日期 | dwd_security_master.list_date ← stock_basic；多版本日期冲突则NULL； |
| `holder_num_mrq_0` | 实现 | 户（A+B股东总户数） | dwd_stock_holder_number.holder_num ← stk_holdernumber_raw；公告下一交易日可用；固定自然季末； |
| `holder_num_mrq_1` | 实现 | 户（A+B股东总户数） | dwd_stock_holder_number.holder_num ← stk_holdernumber_raw；公告下一交易日可用；固定自然季末； |
| `northbound_hold_shares` | 实现 | 股 | dwd_stock_northbound_holding.vol；按可用日取最近披露，不与hk_hold_vol同义； |
| `fund_report_hold_shares_total` | NULL占位 | 股 | 上游明细表加工（default.dwd_fund_portfolio.amount）；缺少基金完整披露标记 |
| `fund_report_holder_count` | NULL占位 | 个 | 上游明细表加工（default.dwd_fund_portfolio.fund_id/amount）；缺少基金完整披露标记 |
| `national_team_hold_shares` | NULL占位 | 股 | 上游明细表加工（default.top10_holders：ts_code、end_date、ann_date、holder_name、hold_amount、_record_hash；default.top10_floatholders：ts_code、end_date、ann_date、holder_name、hold_amount、_record_hash，仅作流通持仓补充核对）；缺少经确认的国家队主体名单 |
| `national_team_free_hold_shares` | NULL占位 | 股 | 上游明细表加工（default.top10_floatholders.hold_amount；国家队主体名单）；缺少经确认的国家队主体名单 |
| `national_team_hold_shares_prev_report` | NULL占位 | 股 | 上游明细表加工（default.top10_holders：ts_code、end_date、ann_date、holder_name、hold_amount、_record_hash；default.top10_floatholders：ts_code、end_date、ann_date、holder_name、hold_amount、_record_hash，仅作流通持仓补充核对）；缺少经确认的国家队主体名单 |
| `national_team_report_close` | NULL占位 | 元/股 | 上游明细表（default.dwd_stock_eod_price.close）；缺少经确认的国家队主体名单 |
| `national_team_report_close_prev_report` | NULL占位 | 元/股 | 上游明细表（default.dwd_stock_eod_price.close）；缺少经确认的国家队主体名单 |
| `national_team_report_free_float_mv` | NULL占位 | 元 | 上游明细表加工（default.dwd_stock_daily_basic.free_share、default.dwd_stock_eod_price.close）；缺少经确认的国家队主体名单 |
| `national_team_hold_free_share_ratio` | NULL占位 | 无量纲 | 上游明细表加工（default.top10_holders 与 default.top10_floatholders 的 hold_amount、default.dwd_stock_daily_basic.free_share）；缺少经确认的国家队主体名单 |
| `national_team_hold_free_share_ratio_prev_report` | NULL占位 | 无量纲 | 上游明细表加工（default.top10_holders 与 default.top10_floatholders 的 hold_amount、default.dwd_stock_daily_basic.free_share）；缺少经确认的国家队主体名单 |
| `halfyear_depreciation` | 实现 | 元 | 上游明细表加工（default.dwd_stock_cashflow.depr_fa_coga_dpba）； |
| `company_province` | NULL占位 | 文本/代码 | 上游明细表候选（default.stock_company.province；历史地址生效日待补）；缺少公司地址历史生效日 |
| `company_city` | NULL占位 | 文本/代码 | 上游明细表候选（default.stock_company.city；历史地址生效日待补）；缺少公司地址历史生效日 |
| `csi800_member` | 实现 | 0/1；无法确认缺失时NULL | 上游明细表加工（default.dwd_index_weight：index_code、con_code、weight、event_date、available_trade_date、sys_from）； |
| `implemented_cash_dividend_12m_cny` | 实现 | 元 | 上游明细表加工（default.dwd_stock_dividend：div_proc、ex_date、available_trade_date、cash_div_tax、base_share）； |
| `deferred_income_tax_ttm_0` | 实现 | 元 | cashflow.deferred_income_tax / ttm_0； |
| `analyst_np_consensus_fy0` | 实现 | 元 | 上游明细表加工（default.dwd_stock_research_report.np；已披露时 default.dwd_stock_income.n_income_attr_p）；按约定文档公式；np源仅称预测净利润，归母含义未经核实；年度预测只取Q4 |
| `analyst_np_consensus_fy1` | 实现 | 元 | 上游明细表加工（default.dwd_stock_research_report.np）；按约定文档公式；np源仅称预测净利润，归母含义未经核实；年度预测只取Q4 |
| `analyst_np_consensus_fy2` | 实现 | 元 | 上游明细表加工（default.dwd_stock_research_report.np）；按约定文档公式；np源仅称预测净利润，归母含义未经核实；年度预测只取Q4 |
| `analyst_np_consensus_fy3` | 实现 | 元 | 上游明细表加工（default.dwd_stock_research_report.np）；按约定文档公式；np源仅称预测净利润，归母含义未经核实；年度预测只取Q4 |
| `analyst_bv_consensus_fy1` | 实现 | 元 | 上游明细表加工（FY1 预测净资产/BPS 直接源列缺失；近似源 default.dwd_stock_balance_sheet：total_hldr_eqy_exc_min_int、end_date、available_trade_date；default.dwd_stock_research_report：np、forecast_period_end、org_name、available_trade_date；历史留存率源 default.dwd_stock_income：n_income_attr_p、end_date、available_trade_date；default.dwd_stock_dividend：cash_div_tax、base_share、div_proc、ex_date、available_trade_date）；按约定文档公式；np源仅称预测净利润，归母含义未经核实；年度预测只取Q4 |
| `analyst_forward_pe_12m` | 实现 | 倍 | 上游明细表加工（default.dwd_stock_daily_basic：trade_date、total_mv；default.dwd_stock_research_report：np、forecast_period_end、org_name、report_date、available_trade_date）；按约定文档公式；np源仅称预测净利润，归母含义未经核实；年度预测只取Q4 |
| `analyst_np_mean_active_180d_cny` | 实现 | 元 | 上游明细表加工（default.dwd_stock_research_report.np）；按约定文档公式；np源仅称预测净利润，归母含义未经核实；年度预测只取Q4 |
| `analyst_eps_mean_active_90d` | 实现 | 元/股 | 上游明细表加工（default.dwd_stock_research_report.eps）；按约定文档公式；np源仅称预测净利润，归母含义未经核实；年度预测只取Q4 |
| `analyst_eps_dispersion_active_90d` | 实现 | 无量纲 | 上游明细表加工（default.dwd_stock_research_report.eps）；按约定文档公式；np源仅称预测净利润，归母含义未经核实；年度预测只取Q4 |
| `analyst_eps_dispersion_active_91d` | 实现 | 无量纲 | 上游明细表加工（default.dwd_stock_research_report.eps）；按约定文档公式；np源仅称预测净利润，归母含义未经核实；年度预测只取Q4 |
| `analyst_org_coverage_90d` | 实现 | 个 | 上游明细表加工（default.dwd_stock_research_report.org_name）；按约定文档公式；np源仅称预测净利润，归母含义未经核实；年度预测只取Q4 |
| `analyst_org_year_pair_count_90d` | 实现 | 个 | 上游明细表加工（default.dwd_stock_research_report.org_name 与 forecast_period_end）；按约定文档公式；np源仅称预测净利润，归母含义未经核实；年度预测只取Q4 |
| `analyst_target_price_mean_90d` | 实现 | 元/股 | 上游明细表加工（default.dwd_stock_research_report：min_price、max_price、org_name、report_date、available_trade_date；单一目标价源列缺失）；按约定文档公式；np源仅称预测净利润，归母含义未经核实；年度预测只取Q4 |
| `research_records` | 排除 | 元 | 上游明细表加工（default.dwd_stock_research_report：ts_code、report_date、available_trade_date、forecast_period_end、org_name、author_name、min_price、max_price、eps、np、pe、roe、source_record_hash）；按用户确认本次不提供数组 |
| `fund_holding_records` | 排除 | 元 | 上游明细表加工（default.dwd_fund_portfolio：ts_code、symbol、source_code、fund_id、end_date、ann_date、available_trade_date、amount、mkv、stk_mkv_ratio、source_record_hash；完整持仓标记源列缺失）；按用户确认本次不提供数组 |
| `ccass_holding_records` | 排除 | 元 | 上游明细表加工（default.ccass_hold_detail：ts_code、trade_date、col_participant_id、col_participant_name、col_shareholding、col_shareholding_percent、_record_hash；历史可用日源列缺失）；按用户确认本次不提供数组 |
| `main_business_records` | 排除 | 元 | 上游明细表加工（default.fina_mainbz：ts_code、end_date、bz_code、bz_item、bz_sales、curr_type、_record_hash；公告日及历史可用日源列缺失）；按用户确认本次不提供数组 |
| `top_holder_records` | 排除 | 元 | 上游明细表加工（default.top10_holders、default.top10_floatholders：ts_code、end_date、ann_date、holder_name、holder_type、hold_amount、hold_ratio、hold_float_ratio、_record_hash）；按用户确认本次不提供数组 |
