WITH
price AS (
    SELECT
        instrument_id,
        instrument_type,
        exchange,
        source_code,
        event_date,
        available_trade_date,
        open,
        high,
        low,
        close,
        pre_close,
        pct_chg,
        vol,
        amount,
        source_batch_id,
        source_record_hash
    FROM {db_name}.dwd_stock_eod_price
    WHERE sys_to = toDateTime64('9999-12-31 00:00:00', 3)
      AND event_date >= toDate32('2010-01-01')
),
daily_basic AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        pe_ttm,
        pb,
        ps_ttm,
        dv_ttm,
        turnover_rate,
        turnover_rate_f,
        volume_ratio,
        circ_mv,
        total_mv,
        total_share,
        float_share,
        free_share,
        source_batch_id,
        source_record_hash
    FROM {db_name}.dwd_stock_daily_basic
    WHERE sys_to = toDateTime64('9999-12-31 00:00:00', 3)
      AND event_date >= toDate32('2010-01-01')
),
adj_factor AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        adj_factor,
        source_batch_id,
        source_record_hash
    FROM {db_name}.dwd_stock_adj_factor
    WHERE sys_to = toDateTime64('9999-12-31 00:00:00', 3)
      AND event_date >= toDate32('2010-01-01')
),
quote_metrics AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        buying,
        selling,
        strength,
        activity,
        avg_turnover,
        attack,
        source_batch_id,
        source_record_hash
    FROM {db_name}.dwd_stock_eod_quote_metrics
    WHERE sys_to = toDateTime64('9999-12-31 00:00:00', 3)
      AND event_date >= toDate32('2010-01-01')
),
financial_indicator_report_versions AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        update_flag,
        sys_from,
        source_batch_id,
        source_record_hash,
        roe,
        roa,
        roic,
        grossprofit_margin,
        netprofit_margin,
        or_yoy,
        netprofit_yoy,
        op_yoy,
        basic_eps_yoy,
        q_roe,
        q_gsprofit_margin,
        q_netprofit_yoy,
        q_sales_yoy,
        ocf_to_or,
        ocf_to_profit,
        debt_to_assets,
        current_ratio,
        eps,
        bps,
        ocfps,
        rd_exp,
        assets_turn,
        inv_turn,
        ar_turn,
        ebit,
        ebitda
    FROM (
        SELECT
            src.instrument_id,
            src.event_date,
            src.available_trade_date,
            src.update_flag,
            src.sys_from,
            src.source_batch_id,
            src.source_record_hash,
            src.roe,
            src.roa,
            src.roic,
            src.grossprofit_margin,
            src.netprofit_margin,
            src.or_yoy,
            src.netprofit_yoy,
            src.op_yoy,
            src.basic_eps_yoy,
            src.q_roe,
            src.q_gsprofit_margin,
            src.q_netprofit_yoy,
            src.q_sales_yoy,
            src.ocf_to_or,
            src.ocf_to_profit,
            src.debt_to_assets,
            src.current_ratio,
            src.eps,
            src.bps,
            src.ocfps,
            src.rd_exp,
            src.assets_turn,
            src.inv_turn,
            src.ar_turn,
            src.ebit,
            src.ebitda,
            row_number() OVER (
                PARTITION BY src.instrument_id, src.event_date, src.available_trade_date
                ORDER BY
                    src.update_flag DESC,
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS version_rank
        FROM {db_name}.dwd_stock_financial_indicator src
        WHERE src.sys_to = toDateTime64('9999-12-31 00:00:00', 3)
    ) src
    WHERE version_rank = 1
),
financial_indicator_state_dates AS (
    SELECT DISTINCT
        instrument_id,
        available_trade_date
    FROM financial_indicator_report_versions
),
financial_indicator AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        source_batch_id,
        source_record_hash,
        roe,
        roa,
        roic,
        grossprofit_margin,
        netprofit_margin,
        or_yoy,
        netprofit_yoy,
        op_yoy,
        basic_eps_yoy,
        q_roe,
        q_gsprofit_margin,
        q_netprofit_yoy,
        q_sales_yoy,
        ocf_to_or,
        ocf_to_profit,
        debt_to_assets,
        current_ratio,
        eps,
        bps,
        ocfps,
        rd_exp,
        assets_turn,
        inv_turn,
        ar_turn,
        ebit,
        ebitda
    FROM (
        SELECT
            d.instrument_id AS instrument_id,
            src.event_date AS event_date,
            d.available_trade_date AS available_trade_date,
            src.source_batch_id AS source_batch_id,
            src.source_record_hash AS source_record_hash,
            src.roe AS roe,
            src.roa AS roa,
            src.roic AS roic,
            src.grossprofit_margin AS grossprofit_margin,
            src.netprofit_margin AS netprofit_margin,
            src.or_yoy AS or_yoy,
            src.netprofit_yoy AS netprofit_yoy,
            src.op_yoy AS op_yoy,
            src.basic_eps_yoy AS basic_eps_yoy,
            src.q_roe AS q_roe,
            src.q_gsprofit_margin AS q_gsprofit_margin,
            src.q_netprofit_yoy AS q_netprofit_yoy,
            src.q_sales_yoy AS q_sales_yoy,
            src.ocf_to_or AS ocf_to_or,
            src.ocf_to_profit AS ocf_to_profit,
            src.debt_to_assets AS debt_to_assets,
            src.current_ratio AS current_ratio,
            src.eps AS eps,
            src.bps AS bps,
            src.ocfps AS ocfps,
            src.rd_exp AS rd_exp,
            src.assets_turn AS assets_turn,
            src.inv_turn AS inv_turn,
            src.ar_turn AS ar_turn,
            src.ebit AS ebit,
            src.ebitda AS ebitda,
            row_number() OVER (
                PARTITION BY d.instrument_id, d.available_trade_date
                ORDER BY
                    src.event_date DESC,
                    src.available_trade_date DESC,
                    src.update_flag DESC,
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS financial_rank
        FROM financial_indicator_state_dates d
        INNER JOIN financial_indicator_report_versions src
            ON src.instrument_id = d.instrument_id
        WHERE src.available_trade_date <= d.available_trade_date
    ) src
    WHERE financial_rank = 1
),

income_report_versions AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        f_ann_date,
        update_flag,
        sys_from,
        source_batch_id,
        source_record_hash,
        total_revenue,
        revenue,
        n_income,
        n_income_attr_p,
        compr_inc_attr_p,
        compr_inc_attr_m_s,
        oper_cost,
        operate_profit,
        total_profit,
        ebit,
        ebitda,
        admin_exp,
        sell_exp,
        fin_exp,
        income_tax,
        total_opcost,
        assets_impair_loss,
        int_exp
    FROM (
        SELECT
            src.instrument_id,
            src.event_date,
            src.available_trade_date,
            src.f_ann_date,
            src.update_flag,
            src.sys_from,
            src.source_batch_id,
            src.source_record_hash,
            src.total_revenue,
            src.revenue,
            src.n_income,
            src.n_income_attr_p,
            src.compr_inc_attr_p,
            src.compr_inc_attr_m_s,
            src.oper_cost,
            src.operate_profit,
            src.total_profit,
            src.ebit,
            src.ebitda,
            src.admin_exp,
            src.sell_exp,
            src.fin_exp,
            src.income_tax,
            src.total_opcost,
            src.assets_impair_loss,
            src.int_exp,
            row_number() OVER (
                PARTITION BY src.instrument_id, src.event_date, src.available_trade_date
                ORDER BY
                    src.f_ann_date DESC,
                    src.update_flag DESC,
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS version_rank
        FROM {db_name}.dwd_stock_income src
        WHERE src.sys_to = toDateTime64('9999-12-31 00:00:00', 3)
          AND src.report_type = '1'
          -- Preserve malformed source rows in DWD for audit, while excluding
          -- impossible announcement dates from the canonical direct join.
          AND src.ann_date >= src.event_date
    ) src
    WHERE version_rank = 1
),
income_state_dates AS (
    SELECT DISTINCT
        instrument_id,
        available_trade_date
    FROM income_report_versions
),
income AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        source_batch_id,
        source_record_hash,
        `total_revenue`,
        `revenue`,
        `n_income`,
        `n_income_attr_p`,
        `compr_inc_attr_p`,
        `compr_inc_attr_m_s`,
        `oper_cost`,
        `operate_profit`,
        `total_profit`,
        `ebit`,
        `ebitda`,
        `admin_exp`,
        `sell_exp`,
        `fin_exp`,
        `income_tax`,
        `total_opcost`,
        `assets_impair_loss`,
        `int_exp`
    FROM (
        SELECT
            d.instrument_id AS instrument_id,
            r.event_date AS event_date,
            d.available_trade_date AS available_trade_date,
            r.source_batch_id AS source_batch_id,
            r.source_record_hash AS source_record_hash,
            r.`total_revenue` AS `total_revenue`,
        r.`revenue` AS `revenue`,
        r.`n_income` AS `n_income`,
        r.`n_income_attr_p` AS `n_income_attr_p`,
        r.`compr_inc_attr_p` AS `compr_inc_attr_p`,
        r.`compr_inc_attr_m_s` AS `compr_inc_attr_m_s`,
        r.`oper_cost` AS `oper_cost`,
        r.`operate_profit` AS `operate_profit`,
        r.`total_profit` AS `total_profit`,
        r.`ebit` AS `ebit`,
        r.`ebitda` AS `ebitda`,
        r.`admin_exp` AS `admin_exp`,
        r.`sell_exp` AS `sell_exp`,
        r.`fin_exp` AS `fin_exp`,
        r.`income_tax` AS `income_tax`,
        r.`total_opcost` AS `total_opcost`,
        r.`assets_impair_loss` AS `assets_impair_loss`,
        r.`int_exp` AS `int_exp`,
            row_number() OVER (
                PARTITION BY d.instrument_id, d.available_trade_date
                ORDER BY
                    r.event_date DESC,
                    r.available_trade_date DESC,
                    r.f_ann_date DESC,
                    r.update_flag DESC,
                    r.sys_from DESC,
                    r.source_record_hash DESC
            ) AS state_rank
        FROM income_state_dates d
        INNER JOIN income_report_versions r
            ON r.instrument_id = d.instrument_id
        -- ClickHouse only permits the range predicate in ASOF JOIN ON clauses.
        -- Keep this as an equi-join and apply PIT visibility as a row filter.
        WHERE r.available_trade_date <= d.available_trade_date
    ) ranked
    WHERE state_rank = 1
),

balance_sheet_report_versions AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        f_ann_date,
        update_flag,
        sys_from,
        source_batch_id,
        source_record_hash,
        total_assets,
        total_liab,
        total_cur_liab,
        total_cur_assets,
        money_cap,
        total_hldr_eqy_exc_min_int,
        div_receiv,
        fa_avail_for_sale,
        htm_invest,
        int_receiv,
        intan_assets,
        r_and_d
    FROM (
        SELECT
            src.instrument_id,
            src.event_date,
            src.available_trade_date,
            src.f_ann_date,
            src.update_flag,
            src.sys_from,
            src.source_batch_id,
            src.source_record_hash,
            src.total_assets,
            src.total_liab,
            src.total_cur_liab,
            src.total_cur_assets,
            src.money_cap,
            src.total_hldr_eqy_exc_min_int,
            src.div_receiv,
            src.fa_avail_for_sale,
            src.htm_invest,
            src.int_receiv,
            src.intan_assets,
            src.r_and_d,
            row_number() OVER (
                PARTITION BY src.instrument_id, src.event_date, src.available_trade_date
                ORDER BY
                    src.f_ann_date DESC,
                    src.update_flag DESC,
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS version_rank
        FROM {db_name}.dwd_stock_balance_sheet src
        WHERE src.sys_to = toDateTime64('9999-12-31 00:00:00', 3)
          AND src.report_type = '1'
          -- Preserve malformed source rows in DWD for audit, while excluding
          -- impossible announcement dates from the canonical direct join.
          AND src.ann_date >= src.event_date
    ) src
    WHERE version_rank = 1
),
balance_sheet_state_dates AS (
    SELECT DISTINCT
        instrument_id,
        available_trade_date
    FROM balance_sheet_report_versions
),
balance_sheet AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        source_batch_id,
        source_record_hash,
        `total_assets`,
        `total_liab`,
        `total_cur_liab`,
        `total_cur_assets`,
        `money_cap`,
        `total_hldr_eqy_exc_min_int`,
        `div_receiv`,
        `fa_avail_for_sale`,
        `htm_invest`,
        `int_receiv`,
        `intan_assets`,
        `r_and_d`
    FROM (
        SELECT
            d.instrument_id AS instrument_id,
            r.event_date AS event_date,
            d.available_trade_date AS available_trade_date,
            r.source_batch_id AS source_batch_id,
            r.source_record_hash AS source_record_hash,
            r.`total_assets` AS `total_assets`,
        r.`total_liab` AS `total_liab`,
        r.`total_cur_liab` AS `total_cur_liab`,
        r.`total_cur_assets` AS `total_cur_assets`,
        r.`money_cap` AS `money_cap`,
        r.`total_hldr_eqy_exc_min_int` AS `total_hldr_eqy_exc_min_int`,
        r.`div_receiv` AS `div_receiv`,
        r.`fa_avail_for_sale` AS `fa_avail_for_sale`,
        r.`htm_invest` AS `htm_invest`,
        r.`int_receiv` AS `int_receiv`,
        r.`intan_assets` AS `intan_assets`,
        r.`r_and_d` AS `r_and_d`,
            row_number() OVER (
                PARTITION BY d.instrument_id, d.available_trade_date
                ORDER BY
                    r.event_date DESC,
                    r.available_trade_date DESC,
                    r.f_ann_date DESC,
                    r.update_flag DESC,
                    r.sys_from DESC,
                    r.source_record_hash DESC
            ) AS state_rank
        FROM balance_sheet_state_dates d
        INNER JOIN balance_sheet_report_versions r
            ON r.instrument_id = d.instrument_id
        -- ClickHouse only permits the range predicate in ASOF JOIN ON clauses.
        -- Keep this as an equi-join and apply PIT visibility as a row filter.
        WHERE r.available_trade_date <= d.available_trade_date
    ) ranked
    WHERE state_rank = 1
),

cashflow_report_versions AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        f_ann_date,
        update_flag,
        sys_from,
        source_batch_id,
        source_record_hash,
        c_inf_fr_operate_a,
        n_cashflow_act,
        st_cash_out_act,
        stot_out_inv_act,
        stot_inflows_inv_act,
        stot_cash_in_fnc_act,
        stot_cashout_fnc_act,
        c_cash_equ_end_period,
        c_fr_sale_sg,
        c_pay_acq_const_fiolta
    FROM (
        SELECT
            src.instrument_id,
            src.event_date,
            src.available_trade_date,
            src.f_ann_date,
            src.update_flag,
            src.sys_from,
            src.source_batch_id,
            src.source_record_hash,
            src.c_inf_fr_operate_a,
            src.n_cashflow_act,
            src.st_cash_out_act,
            src.stot_out_inv_act,
            src.stot_inflows_inv_act,
            src.stot_cash_in_fnc_act,
            src.stot_cashout_fnc_act,
            src.c_cash_equ_end_period,
            src.c_fr_sale_sg,
            src.c_pay_acq_const_fiolta,
            row_number() OVER (
                PARTITION BY src.instrument_id, src.event_date, src.available_trade_date
                ORDER BY
                    src.f_ann_date DESC,
                    src.update_flag DESC,
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS version_rank
        FROM {db_name}.dwd_stock_cashflow src
        WHERE src.sys_to = toDateTime64('9999-12-31 00:00:00', 3)
          AND src.report_type = '1'
          -- Preserve malformed source rows in DWD for audit, while excluding
          -- impossible announcement dates from the canonical direct join.
          AND src.ann_date >= src.event_date
    ) src
    WHERE version_rank = 1
),
cashflow_state_dates AS (
    SELECT DISTINCT
        instrument_id,
        available_trade_date
    FROM cashflow_report_versions
),
cashflow AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        source_batch_id,
        source_record_hash,
        `c_inf_fr_operate_a`,
        `n_cashflow_act`,
        `st_cash_out_act`,
        `stot_out_inv_act`,
        `stot_inflows_inv_act`,
        `stot_cash_in_fnc_act`,
        `stot_cashout_fnc_act`,
        `c_cash_equ_end_period`,
        `c_fr_sale_sg`,
        `c_pay_acq_const_fiolta`
    FROM (
        SELECT
            d.instrument_id AS instrument_id,
            r.event_date AS event_date,
            d.available_trade_date AS available_trade_date,
            r.source_batch_id AS source_batch_id,
            r.source_record_hash AS source_record_hash,
            r.`c_inf_fr_operate_a` AS `c_inf_fr_operate_a`,
        r.`n_cashflow_act` AS `n_cashflow_act`,
        r.`st_cash_out_act` AS `st_cash_out_act`,
        r.`stot_out_inv_act` AS `stot_out_inv_act`,
        r.`stot_inflows_inv_act` AS `stot_inflows_inv_act`,
        r.`stot_cash_in_fnc_act` AS `stot_cash_in_fnc_act`,
        r.`stot_cashout_fnc_act` AS `stot_cashout_fnc_act`,
        r.`c_cash_equ_end_period` AS `c_cash_equ_end_period`,
        r.`c_fr_sale_sg` AS `c_fr_sale_sg`,
        r.`c_pay_acq_const_fiolta` AS `c_pay_acq_const_fiolta`,
            row_number() OVER (
                PARTITION BY d.instrument_id, d.available_trade_date
                ORDER BY
                    r.event_date DESC,
                    r.available_trade_date DESC,
                    r.f_ann_date DESC,
                    r.update_flag DESC,
                    r.sys_from DESC,
                    r.source_record_hash DESC
            ) AS state_rank
        FROM cashflow_state_dates d
        INNER JOIN cashflow_report_versions r
            ON r.instrument_id = d.instrument_id
        -- ClickHouse only permits the range predicate in ASOF JOIN ON clauses.
        -- Keep this as an equi-join and apply PIT visibility as a row filter.
        WHERE r.available_trade_date <= d.available_trade_date
    ) ranked
    WHERE state_rank = 1
),

northbound_holding AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        vol,
        ratio,
        source_batch_id,
        source_record_hash
    FROM {db_name}.dwd_stock_northbound_holding
    WHERE sys_to = toDateTime64('9999-12-31 00:00:00', 3)
      AND event_date >= toDate32('2010-01-01')
),
margin_trading AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        rzye,
        rzmre,
        rzche,
        rqye,
        rqyl,
        rqmcl,
        source_batch_id,
        source_record_hash
    FROM {db_name}.dwd_stock_margin_trading
    WHERE sys_to = toDateTime64('9999-12-31 00:00:00', 3)
      AND event_date >= toDate32('2010-01-01')
),
chip_distribution AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        winner_rate,
        cost_5pct,
        cost_50pct,
        cost_95pct,
        weight_avg,
        source_batch_id,
        source_record_hash
    FROM {db_name}.dwd_stock_chip_distribution
    WHERE sys_to = toDateTime64('9999-12-31 00:00:00', 3)
      AND event_date >= toDate32('2010-01-01')
),
wide_candidates AS (
    SELECT
        price.instrument_id AS instrument_id,
        price.instrument_type AS instrument_type,
        price.exchange AS exchange,
        price.source_code AS source_code,
        price.event_date AS event_date,
        price.event_date AS trade_date,
        greatest(
            price.available_trade_date,
            coalesce(adj_factor.available_trade_date, price.available_trade_date),
            coalesce(daily_basic.available_trade_date, price.available_trade_date),
            coalesce(quote_metrics.available_trade_date, price.available_trade_date),
            coalesce(financial_indicator.available_trade_date, price.available_trade_date),
            coalesce(income.available_trade_date, price.available_trade_date),
            coalesce(balance_sheet.available_trade_date, price.available_trade_date),
            coalesce(cashflow.available_trade_date, price.available_trade_date),
            coalesce(northbound_holding.available_trade_date, price.available_trade_date),
            coalesce(margin_trading.available_trade_date, price.available_trade_date),
            coalesce(chip_distribution.available_trade_date, price.available_trade_date)
        ) AS available_trade_date,
        price.open AS open,
        price.high AS high,
        price.low AS low,
        price.close AS close,
        price.pre_close AS pre_close,
        price.pct_chg AS pct_chg,
        price.vol AS vol,
        price.amount AS amount,
        adj_factor.adj_factor AS adj_factor,
        quote_metrics.buying AS buying,
        quote_metrics.selling AS selling,
        daily_basic.volume_ratio AS vol_ratio,
        daily_basic.turnover_rate AS turn_over,
        (price.high - price.low) / nullIf(price.pre_close, 0) * 100 AS swing,
        price.amount * 10 / nullIf(price.vol, 0) AS avg_price,
        quote_metrics.strength AS strength,
        quote_metrics.activity AS activity,
        quote_metrics.avg_turnover AS avg_turnover,
        quote_metrics.attack AS attack,
        daily_basic.pe_ttm AS pe_ttm,
        daily_basic.pb AS pb,
        daily_basic.ps_ttm AS ps_ttm,
        daily_basic.dv_ttm AS dv_ttm,
        daily_basic.turnover_rate_f AS turnover_rate_f,
        daily_basic.volume_ratio AS volume_ratio_db,
        daily_basic.circ_mv AS circ_mv,
        daily_basic.total_mv AS total_mv,
        daily_basic.total_share AS total_share,
        daily_basic.float_share AS float_share,
        daily_basic.free_share AS free_share,
        financial_indicator.roe AS roe,
        financial_indicator.roa AS roa,
        financial_indicator.roic AS roic,
        financial_indicator.grossprofit_margin AS grossprofit_margin,
        financial_indicator.netprofit_margin AS netprofit_margin,
        financial_indicator.or_yoy AS or_yoy,
        financial_indicator.netprofit_yoy AS netprofit_yoy,
        financial_indicator.op_yoy AS op_yoy,
        financial_indicator.basic_eps_yoy AS basic_eps_yoy,
        financial_indicator.q_roe AS q_roe,
        financial_indicator.q_gsprofit_margin AS q_gsprofit_margin,
        financial_indicator.q_netprofit_yoy AS q_netprofit_yoy,
        financial_indicator.q_sales_yoy AS q_sales_yoy,
        financial_indicator.ocf_to_or AS ocf_to_or,
        coalesce(
            financial_indicator.ocf_to_profit,
            if(
                financial_indicator.event_date = income.event_date
                AND financial_indicator.event_date = cashflow.event_date,
                100.0 * cashflow.n_cashflow_act / nullIf(income.operate_profit, 0),
                CAST(NULL AS Nullable(Float64))
            )
        ) AS ocf_to_profit,
        financial_indicator.debt_to_assets AS debt_to_assets,
        financial_indicator.current_ratio AS current_ratio,
        financial_indicator.eps AS eps,
        financial_indicator.bps AS bps,
        financial_indicator.ocfps AS ocfps,
        financial_indicator.rd_exp AS rd_exp,
        financial_indicator.assets_turn AS assets_turn,
        financial_indicator.inv_turn AS inv_turn,
        financial_indicator.ar_turn AS ar_turn,
        income.total_revenue AS total_revenue,
        income.revenue AS revenue,
        income.n_income AS n_income,
        income.n_income_attr_p AS n_income_attr_p,
        income.compr_inc_attr_p AS compr_inc_attr_p,
        income.compr_inc_attr_m_s AS compr_inc_attr_m_s,
        income.oper_cost AS oper_cost,
        income.total_profit AS total_profit,
        financial_indicator.ebit AS ebit,
        financial_indicator.ebitda AS ebitda,
        income.admin_exp AS admin_exp,
        income.sell_exp AS sell_exp,
        income.fin_exp AS fin_exp,
        income.income_tax AS income_tax,
        income.total_opcost AS total_opcost,
        balance_sheet.total_assets AS total_assets,
        balance_sheet.total_liab AS total_liab,
        balance_sheet.total_cur_liab AS total_cur_liab,
        balance_sheet.total_cur_assets AS total_cur_assets,
        balance_sheet.money_cap AS money_cap,
        balance_sheet.total_hldr_eqy_exc_min_int AS total_hldr_eqy_exc_min_int,
        cashflow.c_inf_fr_operate_a AS c_inf_fr_operate_a,
        cashflow.st_cash_out_act AS st_cash_out_act,
        cashflow.stot_out_inv_act AS stot_out_inv_act,
        cashflow.stot_inflows_inv_act AS stot_inflows_inv_act,
        cashflow.stot_cash_in_fnc_act AS stot_cash_in_fnc_act,
        cashflow.stot_cashout_fnc_act AS stot_cashout_fnc_act,
        daily_basic.`volume_ratio` AS `volume_ratio`,
        income.`assets_impair_loss` AS `assets_impair_loss`,
        income.`int_exp` AS `int_exp`,
        balance_sheet.`div_receiv` AS `div_receiv`,
        balance_sheet.`fa_avail_for_sale` AS `fa_avail_for_sale`,
        balance_sheet.`htm_invest` AS `htm_invest`,
        balance_sheet.`int_receiv` AS `int_receiv`,
        balance_sheet.`intan_assets` AS `intan_assets`,
        balance_sheet.`r_and_d` AS `r_and_d`,
        cashflow.`c_cash_equ_end_period` AS `c_cash_equ_end_period`,
        cashflow.`c_fr_sale_sg` AS `c_fr_sale_sg`,
        cashflow.`c_pay_acq_const_fiolta` AS `c_pay_acq_const_fiolta`,
        northbound_holding.vol AS hk_hold_vol,
        northbound_holding.ratio AS hk_hold_ratio,
        margin_trading.rzye AS rzye,
        margin_trading.rzmre AS rzmre,
        margin_trading.rzche AS rzche,
        margin_trading.rqye AS rqye,
        margin_trading.rqyl AS rqyl,
        margin_trading.rqmcl AS rqmcl,
        chip_distribution.winner_rate AS winner_rate,
        chip_distribution.cost_5pct AS cost_5pct,
        chip_distribution.cost_50pct AS cost_50pct,
        chip_distribution.cost_95pct AS cost_95pct,
        chip_distribution.weight_avg AS weight_avg_cost,
        now64(3) AS build_time,
        'derived' AS source,
        'dwd_stock_eod_price,dwd_stock_adj_factor,dwd_stock_daily_basic,dwd_stock_eod_quote_metrics,dwd_stock_financial_indicator,dws_stock_financial_indicator_quarter,dws_stock_income_quarter,dws_stock_cashflow_quarter,dwd_stock_income,dwd_stock_balance_sheet,dwd_stock_cashflow,dwd_stock_northbound_holding,dwd_stock_margin_trading,dwd_stock_chip_distribution' AS source_table,
        concat(
            price.source_batch_id,
            '|', coalesce(adj_factor.source_batch_id, ''),
            '|', coalesce(daily_basic.source_batch_id, ''),
            '|', coalesce(quote_metrics.source_batch_id, ''),
            '|', coalesce(financial_indicator.source_batch_id, ''),
            '|', coalesce(income.source_batch_id, ''),
            '|', coalesce(balance_sheet.source_batch_id, ''),
            '|', coalesce(cashflow.source_batch_id, ''),
            '|', coalesce(northbound_holding.source_batch_id, ''),
            '|', coalesce(margin_trading.source_batch_id, ''),
            '|', coalesce(chip_distribution.source_batch_id, '')
        ) AS source_batch_id,
        lower(hex(MD5(concat(
            price.source_record_hash,
            '|', coalesce(adj_factor.source_record_hash, ''),
            '|', coalesce(daily_basic.source_record_hash, ''),
            '|', coalesce(quote_metrics.source_record_hash, ''),
            '|', coalesce(financial_indicator.source_record_hash, ''),
            '|', coalesce(income.source_record_hash, ''),
            '|', coalesce(balance_sheet.source_record_hash, ''),
            '|', coalesce(cashflow.source_record_hash, ''),
            '|', coalesce(northbound_holding.source_record_hash, ''),
            '|', coalesce(margin_trading.source_record_hash, ''),
            '|', coalesce(chip_distribution.source_record_hash, '')
        )))) AS source_record_hash
    FROM price
    LEFT JOIN adj_factor
        ON adj_factor.instrument_id = price.instrument_id
       AND adj_factor.event_date = price.event_date
    LEFT JOIN daily_basic
        ON daily_basic.instrument_id = price.instrument_id
       AND daily_basic.event_date = price.event_date
    LEFT JOIN quote_metrics
        ON quote_metrics.instrument_id = price.instrument_id
       AND quote_metrics.event_date = price.event_date
    ASOF LEFT JOIN financial_indicator
        ON price.instrument_id = financial_indicator.instrument_id
       AND price.available_trade_date >= financial_indicator.available_trade_date
    ASOF LEFT JOIN income
        ON price.instrument_id = income.instrument_id
       AND price.available_trade_date >= income.available_trade_date
    ASOF LEFT JOIN balance_sheet
        ON price.instrument_id = balance_sheet.instrument_id
       AND price.available_trade_date >= balance_sheet.available_trade_date
    ASOF LEFT JOIN cashflow
        ON price.instrument_id = cashflow.instrument_id
       AND price.available_trade_date >= cashflow.available_trade_date
    LEFT JOIN northbound_holding
        ON northbound_holding.instrument_id = price.instrument_id
       AND northbound_holding.event_date = price.event_date
    LEFT JOIN margin_trading
        ON margin_trading.instrument_id = price.instrument_id
       AND margin_trading.event_date = price.event_date
    LEFT JOIN chip_distribution
        ON chip_distribution.instrument_id = price.instrument_id
       AND chip_distribution.event_date = price.event_date
)
SELECT
    instrument_id,
    instrument_type,
    exchange,
    source_code,
    event_date,
    trade_date,
    available_trade_date,
    open,
    high,
    low,
    close,
    pre_close,
    pct_chg,
    vol,
    amount,
    adj_factor,
    buying,
    selling,
    vol_ratio,
    turn_over,
    swing,
    avg_price,
    strength,
    activity,
    avg_turnover,
    attack,
    pe_ttm,
    pb,
    ps_ttm,
    dv_ttm,
    turnover_rate_f,
    volume_ratio_db,
    circ_mv,
    total_mv,
    total_share,
    float_share,
    free_share,
    roe,
    roa,
    roic,
    grossprofit_margin,
    netprofit_margin,
    or_yoy,
    netprofit_yoy,
    op_yoy,
    basic_eps_yoy,
    q_roe,
    q_gsprofit_margin,
    q_netprofit_yoy,
    q_sales_yoy,
    ocf_to_or,
    ocf_to_profit,
    debt_to_assets,
    current_ratio,
    eps,
    bps,
    ocfps,
    rd_exp,
    assets_turn,
    inv_turn,
    ar_turn,
    total_revenue,
    revenue,
    n_income,
    n_income_attr_p,
    compr_inc_attr_p,
    compr_inc_attr_m_s,
    oper_cost,
    total_profit,
    ebit,
    ebitda,
    admin_exp,
    sell_exp,
    fin_exp,
    income_tax,
    total_opcost,
    total_assets,
    total_liab,
    total_cur_liab,
    total_cur_assets,
    money_cap,
    total_hldr_eqy_exc_min_int,
    c_inf_fr_operate_a,
    st_cash_out_act,
    stot_out_inv_act,
    stot_inflows_inv_act,
    stot_cash_in_fnc_act,
    stot_cashout_fnc_act,
    `volume_ratio`,
    `assets_impair_loss`,
    `int_exp`,
    `div_receiv`,
    `fa_avail_for_sale`,
    `htm_invest`,
    `int_receiv`,
    `intan_assets`,
    `r_and_d`,
    `c_cash_equ_end_period`,
    `c_fr_sale_sg`,
    `c_pay_acq_const_fiolta`,
    hk_hold_vol,
    hk_hold_ratio,
    rzye,
    rzmre,
    rzche,
    rqye,
    rqyl,
    rqmcl,
    winner_rate,
    cost_5pct,
    cost_50pct,
    cost_95pct,
    weight_avg_cost,
    build_time,
    source,
    source_table,
    source_batch_id,
    source_record_hash
FROM wide_candidates
