# DWS 因子矩阵复权口径

更新时间：2026-05-29

## 背景

`dws_stock_factor_wide_matrix` 基于 `dws_stock_factor_wide` 的数值字段和 `docs/prd/factor_mapping_readable.csv` 中的表达式生成因子矩阵。

当前实现中，`dws_stock_factor_wide` 的价格字段直接来自 `dwd_stock_eod_price`，扩展行情字段直接来自 `dwd_stock_eod_quote_metrics`，没有 join `dwd_stock_adj_factor`，也没有对 `open`、`high`、`low`、`close`、`pre_close`、`avg_price` 或筹码成本字段做前复权/后复权计算。因此当前矩阵实际使用的是未复权的源表口径。

## 总体原则

矩阵表不应整表统一使用一种价格口径。建议按因子业务含义选择：

| 场景 | 推荐口径 | 原因 |
| --- | --- | --- |
| 跨交易日比较的价格序列 | 前复权 | 排除分红、送转、配股等除权除息造成的机械跳变 |
| 当天内部形态 | 原始价格 | 反映真实日内 K 线和成交状态，同日复权比例会抵消 |
| 真实成交量、成交额、换手率 | 原始字段 | 这些是实际交易量/金额，不应被价格复权因子调整 |
| 市值、估值、财务指标 | 原始字段 | 来源字段已经是业务指标，不能按价格复权因子重算 |
| 筹码成本跨日比较 | 前复权成本 | 成本价格是价格序列，跨日比较需要价格连续性 |
| 收盘价与同日筹码成本比较 | 原始价格与原始成本 | 同日比较强调现实成本区间，若双方同时复权比例会抵消 |

不建议在矩阵因子中使用后复权。后复权会把历史价格拉到很大的累计尺度，不利于模型横截面对比、数值稳定性和结果解释。因子矩阵更适合使用前复权或 PIT 前复权。

## 推荐前复权表达式

推荐新增逻辑字段：

```text
$close_qfq = $close * $adj_factor / $anchor_adj_factor
$open_qfq  = $open  * $adj_factor / $anchor_adj_factor
$high_qfq  = $high  * $adj_factor / $anchor_adj_factor
$low_qfq   = $low   * $adj_factor / $anchor_adj_factor
$vwap_qfq  = $vwap  * $adj_factor / $anchor_adj_factor

$cost_5pct_qfq       = $cost_5pct       * $adj_factor / $anchor_adj_factor
$cost_50pct_qfq      = $cost_50pct      * $adj_factor / $anchor_adj_factor
$cost_95pct_qfq      = $cost_95pct      * $adj_factor / $anchor_adj_factor
$weight_avg_cost_qfq = $weight_avg_cost * $adj_factor / $anchor_adj_factor
```

`anchor_adj_factor` 应按该行 `available_trade_date` 做 PIT/as-of 锚定，避免使用未来才可知道的最新复权因子污染历史训练样本。

## 应使用前复权的因子

### Alpha158 价格趋势类

这些因子跨日引用 `$close`、`$high`、`$low`、`$open` 并计算趋势、均线、收益、波动、分位数、滚动极值或回撤，应改用前复权价格。

| 因子范围 | 表达式口径 | 原因 |
| --- | --- | --- |
| `a158_beta*` | `Slope($close_qfq, N) / $close_qfq` | 趋势斜率需要连续价格 |
| `a158_cnt*` | `Mean($close_qfq > Ref($close_qfq, 1), N)` | 涨跌方向不能被除权跳空污染 |
| `a158_cord*` | `Corr($close_qfq / Ref($close_qfq, 1), Log($volume / Ref($volume, 1) + 1), N)` | 收益腿用前复权，成交量保持原始 |
| `a158_corr*` | `Corr($close_qfq, Log($volume + 1), N)` | 价格序列连续，成交量原始 |
| `a158_imax*`、`a158_imin*`、`a158_imxd*` | `IdxMax($high_qfq, N)`、`IdxMin($low_qfq, N)` | 滚动高低点位置需要排除除权断点 |
| `a158_ma*` | `Mean($close_qfq, N) / $close_qfq` | 均线偏离需要连续价格 |
| `a158_max*`、`a158_min*` | `Max($high_qfq, N) / $close_qfq`、`Min($low_qfq, N) / $close_qfq` | 历史高低价比较需要同一价格尺度 |
| `a158_qtld*`、`a158_qtlu*` | `Quantile($close_qfq, N, q) / $close_qfq` | 历史分位数需要同一价格尺度 |
| `a158_rank*` | `Rank($close_qfq, N)` | 时序排名需剔除除权跳变 |
| `a158_resi*` | `Resi($close_qfq, N) / $close_qfq` | 趋势残差需要连续价格 |
| `a158_roc*` | `Ref($close_qfq, N) / $close_qfq` | ROC 本质是跨期收益 |
| `a158_rsqr*` | `Rsquare($close_qfq, N)` | 趋势拟合基于连续价格 |
| `a158_rsv*` | `($close_qfq - Min($low_qfq, N)) / (Max($high_qfq, N) - Min($low_qfq, N) + 1e-12)` | 区间位置需要前后可比 |
| `a158_std*` | `Std($close_qfq, N) / $close_qfq` | 波动率不能包含除权断点 |
| `a158_sumd*`、`a158_sumn*`、`a158_sump*` | 使用 `$close_qfq - Ref($close_qfq, 1)` | 涨跌幅度累计需要连续价格 |
| `a158_wvma*` | `Std(Abs($close_qfq / Ref($close_qfq, 1) - 1) * $volume, N) / ...` | 收益腿前复权，成交量原始 |

### 动量、收益和价量类

| 因子范围 | 表达式口径 | 原因 |
| --- | --- | --- |
| `ac_hl_range_position_delta` | 用 `$close_qfq`、`$high_qfq`、`$low_qfq` | 区间位置跨日比较需要价格连续 |
| `ac_mom_vol_mix` | `($close_qfq / Ref($close_qfq, 10) - 1) / ...` | 动量和波动使用前复权收益 |
| `ac_rankcorr_px_vol` | 价格排名用 `$close_qfq`，成交量用 `$volume` | 价量相关中价格序列需连续 |
| `ac_ret_skew_roll`、`ac_ts_rank_ret_short`、`ac_vol_cluster_ratio` | 使用 `$close_qfq / Ref($close_qfq, 1) - 1` | 收益分布类因子需要前复权收益 |
| `cs_close_vs_mean5` | `($close_qfq - Mean($close_qfq, 5)) / ...` | 均值偏离需要同一价格尺度 |
| `cs_ret5_rank` | 使用 `$close_qfq / Ref($close_qfq, 5) - 1` | 收益排名需要剔除除权跳变 |
| `cb_indneu_mom_20`、`cb_indneu_vol_20`、`cb_vol_price_asym` | 价格条件和收益用 `$close_qfq` | 行业中性动量/波动需连续价格 |
| `liq_amihud_20` | `Mean(Abs($close_qfq / Ref($close_qfq, 1) - 1) / Log($amount + 1), 20)` | 收益前复权，成交额保留真实金额 |
| `ms_gap_fill_speed`、`ms_open_gap` | 使用 `$open_qfq` 与 `Ref($close_qfq, 1)` | 隔夜跳空要排除除权日机械缺口 |
| `pv_corr_ret_vol_10`、`pv_obv_slope`、`pv_price_vol_diverge`、`pv_smart_money`、`pv_vol_price_trend` | 价格用 `_qfq`，`$volume` 或 `$vol` 原始 | 价格趋势连续，成交量真实 |
| `qb_boll_pos_20`、`qb_dist_high_20`、`qb_dist_low_20`、`qb_div_px_vol_20`、`qb_ma_bias_*`、`qb_macd_hist`、`qb_mom_*`、`qb_rev_*`、`qb_rsi_14`、`qb_vol_ret_*` | 所有价格变量用 `_qfq` | 标准技术指标应基于复权价格 |
| `stat_consecutive_up`、`stat_max_drawdown_10`、`stat_recovery_speed`、`stat_ret_autocorr_5`、`stat_ret_kurt_20`、`stat_updown_ratio` | 使用 `$close_qfq`、`$high_qfq`、`$low_qfq` | 统计收益、回撤、连涨不能受除权影响 |

### 宽表交叉因子中的价格腿

| 因子 | 推荐表达式 | 原因 |
| --- | --- | --- |
| `wide_momentum_quality` | `($close_qfq / Ref($close_qfq, 20) - 1) * $roe / 100` | 动量腿应为前复权收益，ROE 保持原始 |
| `wide_value_momentum` | `(1.0 / ($pe_ttm + 1e-12)) * ($close_qfq / Ref($close_qfq, 5) - 1)` | 估值原始，动量前复权 |
| `wide_vol_price_sync` | `Corr($close_qfq, $vol, 10)` | 价格连续，成交量真实 |

### 筹码成本跨日因子

筹码成本字段是价格水平，跨日变化和滚动偏离建议使用前复权成本。

| 因子范围 | 推荐表达式口径 | 原因 |
| --- | --- | --- |
| `wide_cost_5pct_bias20`、`wide_cost_50pct_bias20`、`wide_cost_95pct_bias20` | `($cost_x_qfq - Mean($cost_x_qfq, 20)) / (Std($cost_x_qfq, 20) + 1e-12)` | 成本价格跨日比较需要连续价格 |
| `wide_cost_5pct_chg*`、`wide_cost_50pct_chg*`、`wide_cost_95pct_chg*` | `$cost_x_qfq / (Ref($cost_x_qfq, N) + 1e-12) - 1` | 成本变化率需要排除除权断点 |
| `wide_weight_avg_cost_bias20`、`wide_weight_avg_cost_chg*` | 使用 `$weight_avg_cost_qfq` | 加权成本也是价格序列 |

## 应使用原始口径的因子

### 当日 K 线和日内形态

这些因子只比较同一天的 OHLC 或同日价格比例。复权比例在同一天相同，会在比值中抵消；保留原始口径更符合真实交易形态。

| 因子范围 | 原始表达式示例 | 原因 |
| --- | --- | --- |
| `a158_high0`、`a158_low0`、`a158_open0` | `$high / $close`、`$low / $close`、`$open / $close` | 同日比例无需复权 |
| `a158_klen`、`a158_klow*`、`a158_kmid*`、`a158_ksft*`、`a158_kup*` | `($high - $low) / $open` 等 | 反映当天 K 线实体和影线 |
| `a158_vwap0` | `$vwap / $close` | 同日均价比值无需复权 |
| `ac_hl_amp_vol_link`、`ac_oc_spread_norm`、`cs_amp_rank` | `$high / $low - 1`、`($open - $close) / $close` | 日内振幅和价差保留真实口径 |
| `ms_body_ratio`、`ms_intraday_pos`、`ms_lower_shadow`、`ms_upper_shadow` | 原表达式 | 微观结构反映日内真实位置 |
| `qb_amp_mean_10`、`qb_amp_mean_20` | `Mean($high / $low - 1, N)` | 每日振幅本身是同日比例 |

### 成交量、成交额、换手和真实交易指标

| 因子范围 | 推荐口径 | 原因 |
| --- | --- | --- |
| `a158_vma*`、`a158_vstd*`、`a158_vsumd*`、`a158_vsumn*`、`a158_vsump*` | `$volume` 原始 | 成交量不做价格复权 |
| `pv_vol_breakout`、`cs_vol_rank`、`cs_volume_trend` | `$volume` 原始 | 量能趋势应使用真实成交量 |
| `liq_amt_concentration`、`liq_large_amount_ratio` | `$amount` 原始 | 成交额是真实货币金额 |
| `qb_amt_trend_20` | 建议改为 `Slope(Mean($amount, 1), 20)` | 当前 `$close * $volume` 容易受价格复权口径影响，真实成交额应使用 `$amount` |
| `wide_activity_*`、`wide_attack_*`、`wide_buying_*`、`wide_selling_*`、`wide_strength_*`、`wide_swing_*`、`wide_turnover_rate_f_*`、`wide_vol_ratio_*` | 原始字段 | 扩展行情指标、买卖盘、换手率、量比、振幅不是价格水平 |
| `wide_vol_swing` | `$swing * $vol_ratio` | 两者均为原始扩展行情指标 |

### 市值、估值和财务指标

以下因子应保持原始口径，不应使用 `adj_factor` 调整：

| 因子范围 | 字段 | 原因 |
| --- | --- | --- |
| `wide_cashflow_leverage/*` | `$bps`、`$eps`、`$ocfps`、`$current_ratio`、`$debt_to_assets`、`$ocf_to_or`、`$ocf_to_profit` | 财务指标来自财报或财务派生指标，不是行情价格 |
| `wide_growth/*` | `$basic_eps_yoy`、`$netprofit_yoy`、`$op_yoy`、`$or_yoy`、`$q_netprofit_yoy`、`$q_sales_yoy` | 成长指标不受价格复权因子调整 |
| `wide_profitability/*`、`wide_quarter/*` | `$grossprofit_margin`、`$netprofit_margin`、`$roa`、`$roe`、`$roic`、`$q_roe`、`$q_gsprofit_margin` | 盈利能力和季度指标保持原始业务口径 |
| `wide_valuation/*` | `$pe_ttm`、`$pb`、`$ps_ttm`、`$dv_ttm` | 估值字段由源表计算，不按复权因子重算 |
| `wide_size/*` | `$circ_mv`、`$total_mv` | 市值是真实市场金额 |
| `wide_earning_yield`、`wide_ep_roe`、`wide_pb_roe`、`wide_peg`、`wide_ps_growth`、`wide_mv_ratio`、`wide_size_ln` | 原始估值、市值和财务字段 | 业务含义依赖真实估值/市值 |

### 筹码同日比较和比例指标

| 因子范围 | 推荐口径 | 原因 |
| --- | --- | --- |
| `wide_cost_*_raw`、`wide_weight_avg_cost_raw` | 原始成本 | 名称和业务含义是原始成本 |
| `wide_winner_rate_*`、`wide_winner_chg*` | 原始获利比例 | `winner_rate` 是比例，不是价格 |
| `wide_chip_pressure` | `($close - $cost_50pct) / ($cost_95pct - $cost_5pct + 1e-12)` | 同日收盘价与同日筹码成本比较，保持同一原始口径 |
| `wide_chip_support` | `($close - $cost_5pct) / ($close + 1e-12)` | 同日比较，原始价格更贴近现实成本区间 |
| `wide_cost_converge`、`wide_cost_converge_chg` | 使用原始 `$cost_95pct`、`$cost_5pct`、`$close` | 成本集中度相对当日价格，同日比例使用原始口径 |

## 实施建议

1. 在 `dws_stock_factor_wide` 或矩阵构建输入中新增前复权逻辑字段，而不是覆盖现有原始价格字段。
2. 将 `factor_mapping_readable.csv` 中需要前复权的表达式改为引用 `_qfq` 字段。
3. 保留原始字段用于当日形态、真实成交额、估值、市值、财务和可解释性分析。
4. 对 `qb_amt_trend_20` 单独调整为基于 `$amount`，避免用复权价格乘原始成交量得到非真实成交额。
5. 为前复权字段补充 PIT 锚定测试，确保历史样本不会引用未来复权因子。
