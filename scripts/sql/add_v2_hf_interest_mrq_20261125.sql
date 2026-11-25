-- Add six nullable V2 columns only; no backfill or table deletion.
ALTER TABLE `default`.`dws_stock_factor_wide_v2` 
    ADD COLUMN IF NOT EXISTS `fin_exp_int_exp_mrq_0` Nullable(Float64) COMMENT '财务费用中的利息费用MRQ（元）；来自dwd_stock_income.fin_exp_int_exp经income_quarter累计转单季，固定自然季度槽0，按自身公告PIT选版本；缺期或缺值为空' AFTER `ebitda_lyr_4`,
    ADD COLUMN IF NOT EXISTS `fin_exp_int_exp_mrq_4` Nullable(Float64) COMMENT '上年同季财务费用中的利息费用MRQ（元）；来自dwd_stock_income.fin_exp_int_exp经income_quarter累计转单季，固定自然季度槽4；缺期不跳期，最新NULL不回填旧值' AFTER `fin_exp_int_exp_mrq_0`,
    ADD COLUMN IF NOT EXISTS `hf_std_5m` Nullable(Float64) COMMENT '最近21个交易日五分钟对数收益样本标准差（无量纲）；仅建字段，未实现高频计算，V2同步写NULL' AFTER `sw_l1_code`,
    ADD COLUMN IF NOT EXISTS `hf_5m_return_count` Nullable(Int64) COMMENT '当日有效五分钟区间对数收益条数（个）；仅建字段，未实现高频计算，V2同步写NULL' AFTER `hf_std_5m`,
    ADD COLUMN IF NOT EXISTS `hf_5m_return_sum` Nullable(Float64) COMMENT '当日有效五分钟区间对数收益之和（无量纲）；仅建字段，未实现高频计算，V2同步写NULL' AFTER `hf_5m_return_count`,
    ADD COLUMN IF NOT EXISTS `hf_5m_return_sum_sq` Nullable(Float64) COMMENT '当日有效五分钟区间对数收益平方和（无量纲）；仅建字段，未实现高频计算，V2同步写NULL' AFTER `hf_5m_return_sum`;
