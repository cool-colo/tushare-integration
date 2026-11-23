
INSERT INTO v2_scalar_rebuild_20261123.dws_stock_income_quarter_rebuilt (`instrument_id`, `instrument_type`, `exchange`, `source_code`, `event_date`, `fiscal_year`, `fiscal_quarter`, `available_trade_date`, `admin_exp`, `asset_disp_income`, `assets_impair_loss`, `compr_inc_attr_p`, `oth_income`, `rd_exp`, `sell_exp`, `t_compr_income`, `ass_invest_income`, `basic_eps`, `biz_tax_surchg`, `diluted_eps`, `fin_exp`, `fin_exp_int_exp`, `fin_exp_int_inc`, `fv_value_chg_gain`, `income_tax`, `int_income`, `invest_income`, `n_income`, `n_income_attr_p`, `non_oper_exp`, `non_oper_income`, `oper_cost`, `operate_profit`, `oth_impair_loss_assets`, `revenue`, `total_cogs`, `total_profit`, `build_time`, `source`, `source_table`, `source_batch_id`, `source_record_hash`)
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
        `admin_exp`,
        `asset_disp_income`,
        `assets_impair_loss`,
        `compr_inc_attr_p`,
        `oth_income`,
        `rd_exp`,
        `sell_exp`,
        `t_compr_income`,
        `ass_invest_income`,
        `basic_eps`,
        `biz_tax_surchg`,
        `diluted_eps`,
        `fin_exp`,
        `fin_exp_int_exp`,
        `fin_exp_int_inc`,
        `fv_value_chg_gain`,
        `income_tax`,
        `int_income`,
        `invest_income`,
        `n_income`,
        `n_income_attr_p`,
        `non_oper_exp`,
        `non_oper_income`,
        `oper_cost`,
        `operate_profit`,
        `oth_impair_loss_assets`,
        `revenue`,
        `total_cogs`,
        `total_profit`
    FROM (
        SELECT
            src.*,
            row_number() OVER (
                PARTITION BY src.instrument_id, src.event_date, src.available_trade_date
                ORDER BY
                    multiIf(src.report_type = '4', 2, src.report_type = '1', 1, 0) DESC,
                    src.f_ann_date DESC,
                    src.update_flag DESC,
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS report_rank
        FROM v2_scalar_rebuild_20261123.dwd_stock_income src
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
        r.`admin_exp` AS `admin_exp`,
        r.`asset_disp_income` AS `asset_disp_income`,
        r.`assets_impair_loss` AS `assets_impair_loss`,
        r.`compr_inc_attr_p` AS `compr_inc_attr_p`,
        r.`oth_income` AS `oth_income`,
        r.`rd_exp` AS `rd_exp`,
        r.`sell_exp` AS `sell_exp`,
        r.`t_compr_income` AS `t_compr_income`,
        r.`ass_invest_income` AS `ass_invest_income`,
        r.`basic_eps` AS `basic_eps`,
        r.`biz_tax_surchg` AS `biz_tax_surchg`,
        r.`diluted_eps` AS `diluted_eps`,
        r.`fin_exp` AS `fin_exp`,
        r.`fin_exp_int_exp` AS `fin_exp_int_exp`,
        r.`fin_exp_int_inc` AS `fin_exp_int_inc`,
        r.`fv_value_chg_gain` AS `fv_value_chg_gain`,
        r.`income_tax` AS `income_tax`,
        r.`int_income` AS `int_income`,
        r.`invest_income` AS `invest_income`,
        r.`n_income` AS `n_income`,
        r.`n_income_attr_p` AS `n_income_attr_p`,
        r.`non_oper_exp` AS `non_oper_exp`,
        r.`non_oper_income` AS `non_oper_income`,
        r.`oper_cost` AS `oper_cost`,
        r.`operate_profit` AS `operate_profit`,
        r.`oth_impair_loss_assets` AS `oth_impair_loss_assets`,
        r.`revenue` AS `revenue`,
        r.`total_cogs` AS `total_cogs`,
        r.`total_profit` AS `total_profit`,
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
        curr.`admin_exp` AS `admin_exp`,
        curr.`asset_disp_income` AS `asset_disp_income`,
        curr.`assets_impair_loss` AS `assets_impair_loss`,
        curr.`compr_inc_attr_p` AS `compr_inc_attr_p`,
        curr.`oth_income` AS `oth_income`,
        curr.`rd_exp` AS `rd_exp`,
        curr.`sell_exp` AS `sell_exp`,
        curr.`t_compr_income` AS `t_compr_income`,
        curr.`ass_invest_income` AS `ass_invest_income`,
        curr.`basic_eps` AS `basic_eps`,
        curr.`biz_tax_surchg` AS `biz_tax_surchg`,
        curr.`diluted_eps` AS `diluted_eps`,
        curr.`fin_exp` AS `fin_exp`,
        curr.`fin_exp_int_exp` AS `fin_exp_int_exp`,
        curr.`fin_exp_int_inc` AS `fin_exp_int_inc`,
        curr.`fv_value_chg_gain` AS `fv_value_chg_gain`,
        curr.`income_tax` AS `income_tax`,
        curr.`int_income` AS `int_income`,
        curr.`invest_income` AS `invest_income`,
        curr.`n_income` AS `n_income`,
        curr.`n_income_attr_p` AS `n_income_attr_p`,
        curr.`non_oper_exp` AS `non_oper_exp`,
        curr.`non_oper_income` AS `non_oper_income`,
        curr.`oper_cost` AS `oper_cost`,
        curr.`operate_profit` AS `operate_profit`,
        curr.`oth_impair_loss_assets` AS `oth_impair_loss_assets`,
        curr.`revenue` AS `revenue`,
        curr.`total_cogs` AS `total_cogs`,
        curr.`total_profit` AS `total_profit`,
        prev.`admin_exp` AS `prev_admin_exp`,
        prev.`ass_invest_income` AS `prev_ass_invest_income`,
        prev.`asset_disp_income` AS `prev_asset_disp_income`,
        prev.`assets_impair_loss` AS `prev_assets_impair_loss`,
        prev.`basic_eps` AS `prev_basic_eps`,
        prev.`biz_tax_surchg` AS `prev_biz_tax_surchg`,
        prev.`compr_inc_attr_p` AS `prev_compr_inc_attr_p`,
        prev.`diluted_eps` AS `prev_diluted_eps`,
        prev.`fin_exp` AS `prev_fin_exp`,
        prev.`fin_exp_int_exp` AS `prev_fin_exp_int_exp`,
        prev.`fin_exp_int_inc` AS `prev_fin_exp_int_inc`,
        prev.`fv_value_chg_gain` AS `prev_fv_value_chg_gain`,
        prev.`income_tax` AS `prev_income_tax`,
        prev.`int_income` AS `prev_int_income`,
        prev.`invest_income` AS `prev_invest_income`,
        prev.`n_income` AS `prev_n_income`,
        prev.`n_income_attr_p` AS `prev_n_income_attr_p`,
        prev.`non_oper_exp` AS `prev_non_oper_exp`,
        prev.`non_oper_income` AS `prev_non_oper_income`,
        prev.`oper_cost` AS `prev_oper_cost`,
        prev.`operate_profit` AS `prev_operate_profit`,
        prev.`oth_impair_loss_assets` AS `prev_oth_impair_loss_assets`,
        prev.`oth_income` AS `prev_oth_income`,
        prev.`rd_exp` AS `prev_rd_exp`,
        prev.`revenue` AS `prev_revenue`,
        prev.`sell_exp` AS `prev_sell_exp`,
        prev.`t_compr_income` AS `prev_t_compr_income`,
        prev.`total_cogs` AS `prev_total_cogs`,
        prev.`total_profit` AS `prev_total_profit`
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
    if(toQuarter(event_date) = 1, `admin_exp`, if(coalesce(prev_instrument_id, '') = '' OR `admin_exp` IS NULL OR `prev_admin_exp` IS NULL, CAST(NULL, 'Nullable(Float64)'), `admin_exp` - `prev_admin_exp`)) AS `admin_exp`,
    if(toQuarter(event_date) = 1, `asset_disp_income`, if(coalesce(prev_instrument_id, '') = '' OR `asset_disp_income` IS NULL OR `prev_asset_disp_income` IS NULL, CAST(NULL, 'Nullable(Float64)'), `asset_disp_income` - `prev_asset_disp_income`)) AS `asset_disp_income`,
    if(toQuarter(event_date) = 1, `assets_impair_loss`, if(coalesce(prev_instrument_id, '') = '' OR `assets_impair_loss` IS NULL OR `prev_assets_impair_loss` IS NULL, CAST(NULL, 'Nullable(Float64)'), `assets_impair_loss` - `prev_assets_impair_loss`)) AS `assets_impair_loss`,
    if(toQuarter(event_date) = 1, `compr_inc_attr_p`, if(coalesce(prev_instrument_id, '') = '' OR `compr_inc_attr_p` IS NULL OR `prev_compr_inc_attr_p` IS NULL, CAST(NULL, 'Nullable(Float64)'), `compr_inc_attr_p` - `prev_compr_inc_attr_p`)) AS `compr_inc_attr_p`,
    if(toQuarter(event_date) = 1, `oth_income`, if(coalesce(prev_instrument_id, '') = '' OR `oth_income` IS NULL OR `prev_oth_income` IS NULL, CAST(NULL, 'Nullable(Float64)'), `oth_income` - `prev_oth_income`)) AS `oth_income`,
    if(toQuarter(event_date) = 1, `rd_exp`, if(coalesce(prev_instrument_id, '') = '' OR `rd_exp` IS NULL OR `prev_rd_exp` IS NULL, CAST(NULL, 'Nullable(Float64)'), `rd_exp` - `prev_rd_exp`)) AS `rd_exp`,
    if(toQuarter(event_date) = 1, `sell_exp`, if(coalesce(prev_instrument_id, '') = '' OR `sell_exp` IS NULL OR `prev_sell_exp` IS NULL, CAST(NULL, 'Nullable(Float64)'), `sell_exp` - `prev_sell_exp`)) AS `sell_exp`,
    if(toQuarter(event_date) = 1, `t_compr_income`, if(coalesce(prev_instrument_id, '') = '' OR `t_compr_income` IS NULL OR `prev_t_compr_income` IS NULL, CAST(NULL, 'Nullable(Float64)'), `t_compr_income` - `prev_t_compr_income`)) AS `t_compr_income`,
    if(toQuarter(event_date) = 1, `ass_invest_income`, if(coalesce(prev_instrument_id, '') = '' OR `ass_invest_income` IS NULL OR `prev_ass_invest_income` IS NULL, CAST(NULL, 'Nullable(Float64)'), `ass_invest_income` - `prev_ass_invest_income`)) AS `ass_invest_income`,
    if(toQuarter(event_date) = 1, `basic_eps`, if(coalesce(prev_instrument_id, '') = '' OR `basic_eps` IS NULL OR `prev_basic_eps` IS NULL, CAST(NULL, 'Nullable(Float64)'), `basic_eps` - `prev_basic_eps`)) AS `basic_eps`,
    if(toQuarter(event_date) = 1, `biz_tax_surchg`, if(coalesce(prev_instrument_id, '') = '' OR `biz_tax_surchg` IS NULL OR `prev_biz_tax_surchg` IS NULL, CAST(NULL, 'Nullable(Float64)'), `biz_tax_surchg` - `prev_biz_tax_surchg`)) AS `biz_tax_surchg`,
    if(toQuarter(event_date) = 1, `diluted_eps`, if(coalesce(prev_instrument_id, '') = '' OR `diluted_eps` IS NULL OR `prev_diluted_eps` IS NULL, CAST(NULL, 'Nullable(Float64)'), `diluted_eps` - `prev_diluted_eps`)) AS `diluted_eps`,
    if(toQuarter(event_date) = 1, `fin_exp`, if(coalesce(prev_instrument_id, '') = '' OR `fin_exp` IS NULL OR `prev_fin_exp` IS NULL, CAST(NULL, 'Nullable(Float64)'), `fin_exp` - `prev_fin_exp`)) AS `fin_exp`,
    if(toQuarter(event_date) = 1, `fin_exp_int_exp`, if(coalesce(prev_instrument_id, '') = '' OR `fin_exp_int_exp` IS NULL OR `prev_fin_exp_int_exp` IS NULL, CAST(NULL, 'Nullable(Float64)'), `fin_exp_int_exp` - `prev_fin_exp_int_exp`)) AS `fin_exp_int_exp`,
    if(toQuarter(event_date) = 1, `fin_exp_int_inc`, if(coalesce(prev_instrument_id, '') = '' OR `fin_exp_int_inc` IS NULL OR `prev_fin_exp_int_inc` IS NULL, CAST(NULL, 'Nullable(Float64)'), `fin_exp_int_inc` - `prev_fin_exp_int_inc`)) AS `fin_exp_int_inc`,
    if(toQuarter(event_date) = 1, `fv_value_chg_gain`, if(coalesce(prev_instrument_id, '') = '' OR `fv_value_chg_gain` IS NULL OR `prev_fv_value_chg_gain` IS NULL, CAST(NULL, 'Nullable(Float64)'), `fv_value_chg_gain` - `prev_fv_value_chg_gain`)) AS `fv_value_chg_gain`,
    if(toQuarter(event_date) = 1, `income_tax`, if(coalesce(prev_instrument_id, '') = '' OR `income_tax` IS NULL OR `prev_income_tax` IS NULL, CAST(NULL, 'Nullable(Float64)'), `income_tax` - `prev_income_tax`)) AS `income_tax`,
    if(toQuarter(event_date) = 1, `int_income`, if(coalesce(prev_instrument_id, '') = '' OR `int_income` IS NULL OR `prev_int_income` IS NULL, CAST(NULL, 'Nullable(Float64)'), `int_income` - `prev_int_income`)) AS `int_income`,
    if(toQuarter(event_date) = 1, `invest_income`, if(coalesce(prev_instrument_id, '') = '' OR `invest_income` IS NULL OR `prev_invest_income` IS NULL, CAST(NULL, 'Nullable(Float64)'), `invest_income` - `prev_invest_income`)) AS `invest_income`,
    if(toQuarter(event_date) = 1, `n_income`, if(coalesce(prev_instrument_id, '') = '' OR `n_income` IS NULL OR `prev_n_income` IS NULL, CAST(NULL, 'Nullable(Float64)'), `n_income` - `prev_n_income`)) AS `n_income`,
    if(toQuarter(event_date) = 1, `n_income_attr_p`, if(coalesce(prev_instrument_id, '') = '' OR `n_income_attr_p` IS NULL OR `prev_n_income_attr_p` IS NULL, CAST(NULL, 'Nullable(Float64)'), `n_income_attr_p` - `prev_n_income_attr_p`)) AS `n_income_attr_p`,
    if(toQuarter(event_date) = 1, `non_oper_exp`, if(coalesce(prev_instrument_id, '') = '' OR `non_oper_exp` IS NULL OR `prev_non_oper_exp` IS NULL, CAST(NULL, 'Nullable(Float64)'), `non_oper_exp` - `prev_non_oper_exp`)) AS `non_oper_exp`,
    if(toQuarter(event_date) = 1, `non_oper_income`, if(coalesce(prev_instrument_id, '') = '' OR `non_oper_income` IS NULL OR `prev_non_oper_income` IS NULL, CAST(NULL, 'Nullable(Float64)'), `non_oper_income` - `prev_non_oper_income`)) AS `non_oper_income`,
    if(toQuarter(event_date) = 1, `oper_cost`, if(coalesce(prev_instrument_id, '') = '' OR `oper_cost` IS NULL OR `prev_oper_cost` IS NULL, CAST(NULL, 'Nullable(Float64)'), `oper_cost` - `prev_oper_cost`)) AS `oper_cost`,
    if(toQuarter(event_date) = 1, `operate_profit`, if(coalesce(prev_instrument_id, '') = '' OR `operate_profit` IS NULL OR `prev_operate_profit` IS NULL, CAST(NULL, 'Nullable(Float64)'), `operate_profit` - `prev_operate_profit`)) AS `operate_profit`,
    if(toQuarter(event_date) = 1, `oth_impair_loss_assets`, if(coalesce(prev_instrument_id, '') = '' OR `oth_impair_loss_assets` IS NULL OR `prev_oth_impair_loss_assets` IS NULL, CAST(NULL, 'Nullable(Float64)'), `oth_impair_loss_assets` - `prev_oth_impair_loss_assets`)) AS `oth_impair_loss_assets`,
    if(toQuarter(event_date) = 1, `revenue`, if(coalesce(prev_instrument_id, '') = '' OR `revenue` IS NULL OR `prev_revenue` IS NULL, CAST(NULL, 'Nullable(Float64)'), `revenue` - `prev_revenue`)) AS `revenue`,
    if(toQuarter(event_date) = 1, `total_cogs`, if(coalesce(prev_instrument_id, '') = '' OR `total_cogs` IS NULL OR `prev_total_cogs` IS NULL, CAST(NULL, 'Nullable(Float64)'), `total_cogs` - `prev_total_cogs`)) AS `total_cogs`,
    if(toQuarter(event_date) = 1, `total_profit`, if(coalesce(prev_instrument_id, '') = '' OR `total_profit` IS NULL OR `prev_total_profit` IS NULL, CAST(NULL, 'Nullable(Float64)'), `total_profit` - `prev_total_profit`)) AS `total_profit`,
    now64(3) AS build_time,
    'derived' AS source,
    'dwd_stock_income' AS source_table,
    concat(source_batch_id, '|', coalesce(prev_source_batch_id, '')) AS source_batch_id,
    lower(hex(MD5(concat(
        source_record_hash,
        '|',
        coalesce(prev_source_record_hash, '')
    )))) AS source_record_hash
FROM quarter_candidates
