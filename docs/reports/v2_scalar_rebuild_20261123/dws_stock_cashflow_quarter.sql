
INSERT INTO v2_scalar_rebuild_20261123.dws_stock_cashflow_quarter_rebuilt (`instrument_id`, `instrument_type`, `exchange`, `source_code`, `event_date`, `fiscal_year`, `fiscal_quarter`, `available_trade_date`, `c_fr_sale_sg`, `c_paid_to_for_empl`, `c_pay_acq_const_fiolta`, `decr_def_inc_tax_assets`, `incr_def_inc_tax_liab`, `n_recp_disp_fiolta`, `stot_out_inv_act`, `deferred_income_tax`, `amort_intang_assets`, `depr_fa_coga_dpba`, `eff_fx_flu_cash`, `lt_amort_deferred_exp`, `n_cash_flows_fnc_act`, `n_cashflow_act`, `n_cashflow_inv_act`, `n_incr_cash_cash_equ`, `prov_depr_assets`, `build_time`, `source`, `source_table`, `source_batch_id`, `source_record_hash`)
WITH
reports AS (
    SELECT
        instrument_id,
        instrument_type,
        exchange,
        source_code,
        event_date,
        available_trade_date,
        source_batch_id,
        source_record_hash,
        update_flag,
        sys_from,
        report_type,
        f_ann_date,
        `c_fr_sale_sg`,
        `c_paid_to_for_empl`,
        `c_pay_acq_const_fiolta`,
        `decr_def_inc_tax_assets`,
        `incr_def_inc_tax_liab`,
        `n_recp_disp_fiolta`,
        `stot_out_inv_act`,
        `deferred_income_tax`,
        `amort_intang_assets`,
        `depr_fa_coga_dpba`,
        `eff_fx_flu_cash`,
        `lt_amort_deferred_exp`,
        `n_cash_flows_fnc_act`,
        `n_cashflow_act`,
        `n_cashflow_inv_act`,
        `n_incr_cash_cash_equ`,
        `prov_depr_assets`
    FROM (
        SELECT
            src.*, src.decr_def_inc_tax_assets + src.incr_def_inc_tax_liab AS deferred_income_tax,
            row_number() OVER (
                PARTITION BY src.instrument_id, src.event_date, src.available_trade_date
                ORDER BY
                    multiIf(src.report_type = '4', 2, src.report_type = '1', 1, 0) DESC,
                    src.f_ann_date DESC,
                    src.update_flag DESC,
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS report_rank
        FROM v2_scalar_rebuild_20261123.dwd_stock_cashflow src
        WHERE src.sys_to = toDateTime64('9999-12-31 00:00:00', 3)
          AND src.event_date >= toDate32('2010-01-01')
          AND toMonth(src.event_date) IN (3, 6, 9, 12)
          AND src.report_type IN ('1', '4')
          AND src.ann_date >= src.event_date
    ) src
    WHERE report_rank = 1
),
report_changes AS (
    SELECT DISTINCT
        instrument_id,
        available_trade_date AS state_available_trade_date,
        event_date AS affected_event_date
    FROM reports
),
affected_quarters AS (
    -- A cumulative revision changes its own quarter and, except for Q4, the
    -- following quarter whose delta subtracts this cumulative value.
    SELECT
        instrument_id,
        state_available_trade_date,
        affected_event_date
    FROM report_changes
    UNION DISTINCT
    SELECT
        change.instrument_id,
        change.state_available_trade_date,
        toLastDayOfMonth(addMonths(change.affected_event_date, 3)) AS affected_event_date
    FROM report_changes AS change
    -- Qualify the input column: ClickHouse otherwise expands the SELECT alias
    -- in WHERE, tests the *next* quarter, and reverses the intended Q3/Q4 edge.
    WHERE toQuarter(change.affected_event_date) != 4
),
current_candidates AS (
    SELECT
        a.state_available_trade_date AS state_available_trade_date,
        r.instrument_id AS instrument_id,
        r.instrument_type AS instrument_type,
        r.exchange AS exchange,
        r.source_code AS source_code,
        r.event_date AS event_date,
        r.available_trade_date AS report_available_trade_date,
        r.source_batch_id AS source_batch_id,
        r.source_record_hash AS source_record_hash,
        r.`c_fr_sale_sg` AS `c_fr_sale_sg`,
        r.`c_paid_to_for_empl` AS `c_paid_to_for_empl`,
        r.`c_pay_acq_const_fiolta` AS `c_pay_acq_const_fiolta`,
        r.`decr_def_inc_tax_assets` AS `decr_def_inc_tax_assets`,
        r.`incr_def_inc_tax_liab` AS `incr_def_inc_tax_liab`,
        r.`n_recp_disp_fiolta` AS `n_recp_disp_fiolta`,
        r.`stot_out_inv_act` AS `stot_out_inv_act`,
        r.`deferred_income_tax` AS `deferred_income_tax`,
        r.`amort_intang_assets` AS `amort_intang_assets`,
        r.`depr_fa_coga_dpba` AS `depr_fa_coga_dpba`,
        r.`eff_fx_flu_cash` AS `eff_fx_flu_cash`,
        r.`lt_amort_deferred_exp` AS `lt_amort_deferred_exp`,
        r.`n_cash_flows_fnc_act` AS `n_cash_flows_fnc_act`,
        r.`n_cashflow_act` AS `n_cashflow_act`,
        r.`n_cashflow_inv_act` AS `n_cashflow_inv_act`,
        r.`n_incr_cash_cash_equ` AS `n_incr_cash_cash_equ`,
        r.`prov_depr_assets` AS `prov_depr_assets`,
        row_number() OVER (
            PARTITION BY a.instrument_id, a.affected_event_date, a.state_available_trade_date
            ORDER BY
                r.available_trade_date DESC,
                    multiIf(r.report_type = '4', 2, r.report_type = '1', 1, 0) DESC,
                    r.f_ann_date DESC,
                    r.update_flag DESC,
                    r.sys_from DESC,
                    r.source_record_hash DESC
        ) AS current_rank
    FROM affected_quarters a
    INNER JOIN reports r
        ON r.instrument_id = a.instrument_id
       AND r.event_date = a.affected_event_date
    WHERE r.available_trade_date <= a.state_available_trade_date
),
current_reports AS (
    SELECT
        *,
        if(
            toQuarter(event_date) = 1,
            toDate32('1970-01-01'),
            toLastDayOfMonth(addMonths(event_date, -3))
        ) AS previous_event_date
    FROM current_candidates
    WHERE current_rank = 1
),
quarter_candidates AS (
    SELECT
        curr.instrument_id AS instrument_id,
        curr.instrument_type AS instrument_type,
        curr.exchange AS exchange,
        curr.source_code AS source_code,
        curr.event_date AS event_date,
        toUInt16(toYear(curr.event_date)) AS fiscal_year,
        toUInt8(toQuarter(curr.event_date)) AS fiscal_quarter,
        curr.state_available_trade_date AS available_trade_date,
        curr.source_batch_id AS source_batch_id,
        curr.source_record_hash AS source_record_hash,
        prev.instrument_id AS prev_instrument_id,
        prev.source_batch_id AS prev_source_batch_id,
        prev.source_record_hash AS prev_source_record_hash,
        curr.`c_fr_sale_sg` AS `c_fr_sale_sg`,
        curr.`c_paid_to_for_empl` AS `c_paid_to_for_empl`,
        curr.`c_pay_acq_const_fiolta` AS `c_pay_acq_const_fiolta`,
        curr.`decr_def_inc_tax_assets` AS `decr_def_inc_tax_assets`,
        curr.`incr_def_inc_tax_liab` AS `incr_def_inc_tax_liab`,
        curr.`n_recp_disp_fiolta` AS `n_recp_disp_fiolta`,
        curr.`stot_out_inv_act` AS `stot_out_inv_act`,
        curr.`deferred_income_tax` AS `deferred_income_tax`,
        curr.`amort_intang_assets` AS `amort_intang_assets`,
        curr.`depr_fa_coga_dpba` AS `depr_fa_coga_dpba`,
        curr.`eff_fx_flu_cash` AS `eff_fx_flu_cash`,
        curr.`lt_amort_deferred_exp` AS `lt_amort_deferred_exp`,
        curr.`n_cash_flows_fnc_act` AS `n_cash_flows_fnc_act`,
        curr.`n_cashflow_act` AS `n_cashflow_act`,
        curr.`n_cashflow_inv_act` AS `n_cashflow_inv_act`,
        curr.`n_incr_cash_cash_equ` AS `n_incr_cash_cash_equ`,
        curr.`prov_depr_assets` AS `prov_depr_assets`,
        prev.`amort_intang_assets` AS `prev_amort_intang_assets`,
        prev.`c_fr_sale_sg` AS `prev_c_fr_sale_sg`,
        prev.`c_paid_to_for_empl` AS `prev_c_paid_to_for_empl`,
        prev.`c_pay_acq_const_fiolta` AS `prev_c_pay_acq_const_fiolta`,
        prev.`decr_def_inc_tax_assets` AS `prev_decr_def_inc_tax_assets`,
        prev.`deferred_income_tax` AS `prev_deferred_income_tax`,
        prev.`depr_fa_coga_dpba` AS `prev_depr_fa_coga_dpba`,
        prev.`eff_fx_flu_cash` AS `prev_eff_fx_flu_cash`,
        prev.`incr_def_inc_tax_liab` AS `prev_incr_def_inc_tax_liab`,
        prev.`lt_amort_deferred_exp` AS `prev_lt_amort_deferred_exp`,
        prev.`n_cash_flows_fnc_act` AS `prev_n_cash_flows_fnc_act`,
        prev.`n_cashflow_act` AS `prev_n_cashflow_act`,
        prev.`n_cashflow_inv_act` AS `prev_n_cashflow_inv_act`,
        prev.`n_incr_cash_cash_equ` AS `prev_n_incr_cash_cash_equ`,
        prev.`n_recp_disp_fiolta` AS `prev_n_recp_disp_fiolta`,
        prev.`prov_depr_assets` AS `prev_prov_depr_assets`,
        prev.`stot_out_inv_act` AS `prev_stot_out_inv_act`
    FROM current_reports curr
    -- reports is unique per report period and availability date. ASOF therefore
    -- returns the latest previous-quarter version visible at this state date.
    -- Q1 uses an impossible report period so it keeps an empty previous side.
    ASOF LEFT JOIN reports prev
        ON prev.instrument_id = curr.instrument_id
       AND prev.event_date = curr.previous_event_date
       AND curr.state_available_trade_date >= prev.available_trade_date
)
SELECT
    instrument_id,
    instrument_type,
    exchange,
    source_code,
    event_date,
    fiscal_year,
    fiscal_quarter,
    available_trade_date,
    if(toQuarter(event_date) = 1, `c_fr_sale_sg`, if(coalesce(prev_instrument_id, '') = '' OR `c_fr_sale_sg` IS NULL OR `prev_c_fr_sale_sg` IS NULL, CAST(NULL, 'Nullable(Float64)'), `c_fr_sale_sg` - `prev_c_fr_sale_sg`)) AS `c_fr_sale_sg`,
    if(toQuarter(event_date) = 1, `c_paid_to_for_empl`, if(coalesce(prev_instrument_id, '') = '' OR `c_paid_to_for_empl` IS NULL OR `prev_c_paid_to_for_empl` IS NULL, CAST(NULL, 'Nullable(Float64)'), `c_paid_to_for_empl` - `prev_c_paid_to_for_empl`)) AS `c_paid_to_for_empl`,
    if(toQuarter(event_date) = 1, `c_pay_acq_const_fiolta`, if(coalesce(prev_instrument_id, '') = '' OR `c_pay_acq_const_fiolta` IS NULL OR `prev_c_pay_acq_const_fiolta` IS NULL, CAST(NULL, 'Nullable(Float64)'), `c_pay_acq_const_fiolta` - `prev_c_pay_acq_const_fiolta`)) AS `c_pay_acq_const_fiolta`,
    if(toQuarter(event_date) = 1, `decr_def_inc_tax_assets`, if(coalesce(prev_instrument_id, '') = '' OR `decr_def_inc_tax_assets` IS NULL OR `prev_decr_def_inc_tax_assets` IS NULL, CAST(NULL, 'Nullable(Float64)'), `decr_def_inc_tax_assets` - `prev_decr_def_inc_tax_assets`)) AS `decr_def_inc_tax_assets`,
    if(toQuarter(event_date) = 1, `incr_def_inc_tax_liab`, if(coalesce(prev_instrument_id, '') = '' OR `incr_def_inc_tax_liab` IS NULL OR `prev_incr_def_inc_tax_liab` IS NULL, CAST(NULL, 'Nullable(Float64)'), `incr_def_inc_tax_liab` - `prev_incr_def_inc_tax_liab`)) AS `incr_def_inc_tax_liab`,
    if(toQuarter(event_date) = 1, `n_recp_disp_fiolta`, if(coalesce(prev_instrument_id, '') = '' OR `n_recp_disp_fiolta` IS NULL OR `prev_n_recp_disp_fiolta` IS NULL, CAST(NULL, 'Nullable(Float64)'), `n_recp_disp_fiolta` - `prev_n_recp_disp_fiolta`)) AS `n_recp_disp_fiolta`,
    if(toQuarter(event_date) = 1, `stot_out_inv_act`, if(coalesce(prev_instrument_id, '') = '' OR `stot_out_inv_act` IS NULL OR `prev_stot_out_inv_act` IS NULL, CAST(NULL, 'Nullable(Float64)'), `stot_out_inv_act` - `prev_stot_out_inv_act`)) AS `stot_out_inv_act`,
    if(toQuarter(event_date) = 1, `deferred_income_tax`, if(coalesce(prev_instrument_id, '') = '' OR `deferred_income_tax` IS NULL OR `prev_deferred_income_tax` IS NULL, CAST(NULL, 'Nullable(Float64)'), `deferred_income_tax` - `prev_deferred_income_tax`)) AS `deferred_income_tax`,
    if(toQuarter(event_date) = 1, `amort_intang_assets`, if(coalesce(prev_instrument_id, '') = '' OR `amort_intang_assets` IS NULL OR `prev_amort_intang_assets` IS NULL, CAST(NULL, 'Nullable(Float64)'), `amort_intang_assets` - `prev_amort_intang_assets`)) AS `amort_intang_assets`,
    if(toQuarter(event_date) = 1, `depr_fa_coga_dpba`, if(coalesce(prev_instrument_id, '') = '' OR `depr_fa_coga_dpba` IS NULL OR `prev_depr_fa_coga_dpba` IS NULL, CAST(NULL, 'Nullable(Float64)'), `depr_fa_coga_dpba` - `prev_depr_fa_coga_dpba`)) AS `depr_fa_coga_dpba`,
    if(toQuarter(event_date) = 1, `eff_fx_flu_cash`, if(coalesce(prev_instrument_id, '') = '' OR `eff_fx_flu_cash` IS NULL OR `prev_eff_fx_flu_cash` IS NULL, CAST(NULL, 'Nullable(Float64)'), `eff_fx_flu_cash` - `prev_eff_fx_flu_cash`)) AS `eff_fx_flu_cash`,
    if(toQuarter(event_date) = 1, `lt_amort_deferred_exp`, if(coalesce(prev_instrument_id, '') = '' OR `lt_amort_deferred_exp` IS NULL OR `prev_lt_amort_deferred_exp` IS NULL, CAST(NULL, 'Nullable(Float64)'), `lt_amort_deferred_exp` - `prev_lt_amort_deferred_exp`)) AS `lt_amort_deferred_exp`,
    if(toQuarter(event_date) = 1, `n_cash_flows_fnc_act`, if(coalesce(prev_instrument_id, '') = '' OR `n_cash_flows_fnc_act` IS NULL OR `prev_n_cash_flows_fnc_act` IS NULL, CAST(NULL, 'Nullable(Float64)'), `n_cash_flows_fnc_act` - `prev_n_cash_flows_fnc_act`)) AS `n_cash_flows_fnc_act`,
    if(toQuarter(event_date) = 1, `n_cashflow_act`, if(coalesce(prev_instrument_id, '') = '' OR `n_cashflow_act` IS NULL OR `prev_n_cashflow_act` IS NULL, CAST(NULL, 'Nullable(Float64)'), `n_cashflow_act` - `prev_n_cashflow_act`)) AS `n_cashflow_act`,
    if(toQuarter(event_date) = 1, `n_cashflow_inv_act`, if(coalesce(prev_instrument_id, '') = '' OR `n_cashflow_inv_act` IS NULL OR `prev_n_cashflow_inv_act` IS NULL, CAST(NULL, 'Nullable(Float64)'), `n_cashflow_inv_act` - `prev_n_cashflow_inv_act`)) AS `n_cashflow_inv_act`,
    if(toQuarter(event_date) = 1, `n_incr_cash_cash_equ`, if(coalesce(prev_instrument_id, '') = '' OR `n_incr_cash_cash_equ` IS NULL OR `prev_n_incr_cash_cash_equ` IS NULL, CAST(NULL, 'Nullable(Float64)'), `n_incr_cash_cash_equ` - `prev_n_incr_cash_cash_equ`)) AS `n_incr_cash_cash_equ`,
    if(toQuarter(event_date) = 1, `prov_depr_assets`, if(coalesce(prev_instrument_id, '') = '' OR `prov_depr_assets` IS NULL OR `prev_prov_depr_assets` IS NULL, CAST(NULL, 'Nullable(Float64)'), `prov_depr_assets` - `prev_prov_depr_assets`)) AS `prov_depr_assets`,
    now64(3) AS build_time,
    'derived' AS source,
    'dwd_stock_cashflow' AS source_table,
    concat(source_batch_id, '|', coalesce(prev_source_batch_id, '')) AS source_batch_id,
    lower(hex(MD5(concat(
        source_record_hash,
        '|',
        coalesce(prev_source_record_hash, '')
    )))) AS source_record_hash
FROM quarter_candidates
