
INSERT INTO default.dws_stock_main_business
WITH 

calendar_map AS (
    SELECT
        calendar_date,
        -- The frame begins on the following calendar row, preserving the
        -- project's strict "next trading day" visibility convention.  The
        -- inner GROUP BY first collapses multiple ingested calendar versions;
        -- otherwise a duplicate open-day row can be mistaken for "following".
        nullIf(
            minIf(calendar_date, is_open = 1) OVER (
                ORDER BY calendar_date
                ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING
            ),
            toDate32('1970-01-01')
        ) AS next_trade_date
    FROM (
        SELECT
            cal_date AS calendar_date,
            max(is_open) AS is_open
        FROM default.trade_cal
        WHERE exchange = 'SSE'
        GROUP BY cal_date)
),
income_candidates AS (
    SELECT f.ts_code, f.end_date, f.ann_date, f.f_ann_date, f.available_trade_date,
        f.revenue, f.oper_cost, 1 AS candidate_exists,
        toJSONString(arraySort(groupUniqArray(tuple(
            f.source_record_hash, f.source_batch_id, f.sys_from, f.sys_to,
            f.update_flag, f.source, f.source_table
        )))) AS income_records
    FROM default.dwd_stock_income f
    INNER JOIN calendar_map cal
        ON cal.calendar_date = greatest(f.ann_date, f.f_ann_date)
    WHERE f.report_type = '1'
        AND f.ann_date > toDate32('1971-01-01')
        AND f.f_ann_date > toDate32('1971-01-01')
        AND f.ann_date >= f.end_date AND f.f_ann_date >= f.end_date
        AND f.available_trade_date = cal.next_trade_date
        AND (f.ts_code, f.end_date) IN (
            SELECT DISTINCT ts_code, end_date FROM default.dwd_stock_main_business
        )
    GROUP BY f.ts_code, f.end_date, f.ann_date, f.f_ann_date,
        f.available_trade_date, f.revenue, f.oper_cost
),
main_summaries AS (
    SELECT ts_code, end_date, bz_code, curr_type, update_flag, sys_from, source_batch_id,
        uniqExact(tuple(bz_sales, bz_cost)) AS summary_variants,
        any(tuple(bz_sales, bz_cost)).1 AS summary_sales,
        any(tuple(bz_sales, bz_cost)).2 AS summary_cost,
        toJSONString(arraySort(groupUniqArray(tuple(
            source_record_hash, source_batch_id, sys_from, sys_to, bz_item
        )))) AS summary_records
    FROM default.dwd_stock_main_business
    WHERE curr_type = 'CNY'
        AND ((bz_code = 'P' AND bz_item = '产品')
            OR (bz_code = 'D' AND bz_item = '地区')
            OR (bz_code = 'I' AND bz_item = '行业'))
    GROUP BY ts_code, end_date, bz_code, curr_type, update_flag, sys_from, source_batch_id
)
,
joined AS (
    SELECT m.`ts_code` AS `ts_code`, m.`end_date` AS `end_date`, m.`bz_item` AS `bz_item`, m.`bz_code` AS `bz_code`, m.`bz_sales` AS `bz_sales`, m.`bz_profit` AS `bz_profit`, m.`bz_cost` AS `bz_cost`, m.`curr_type` AS `curr_type`, m.`update_flag` AS `update_flag`, m.`instrument_id` AS `instrument_id`, m.`instrument_type` AS `instrument_type`, m.`exchange` AS `exchange`, m.`source_code` AS `source_code`, m.`event_date` AS `event_date`, m.`available_trade_date` AS `available_trade_date`, m.`sys_from` AS `sys_from`, m.`sys_to` AS `sys_to`, m.`source` AS `source`, m.`source_table` AS `source_table`, m.`source_batch_id` AS `source_batch_id`, m.`source_record_hash` AS `source_record_hash`, m.`availability_basis` AS `availability_basis`,
        ifNull(f.candidate_exists, 0) AS _candidate_exists,
        f.ann_date AS _income_ann, f.f_ann_date AS _income_fann,
        f.available_trade_date AS _income_available,
        f.revenue AS _income_revenue, f.oper_cost AS _income_cost,
        if(f.candidate_exists = 1, f.income_records, '[]') AS _income_records,
        if(h.summary_variants = 1, h.summary_sales, CAST(NULL, 'Nullable(Float64)')) AS _summary_sales,
        if(h.summary_variants = 1, h.summary_cost, CAST(NULL, 'Nullable(Float64)')) AS _summary_cost,
        if(h.summary_variants = 1, h.summary_records, '[]') AS _summary_records
    FROM default.dwd_stock_main_business m
    LEFT JOIN main_summaries h
        ON m.ts_code = h.ts_code AND m.end_date = h.end_date AND m.bz_code = h.bz_code
        AND m.curr_type = h.curr_type AND m.update_flag = h.update_flag
        AND m.sys_from = h.sys_from AND m.source_batch_id = h.source_batch_id
    LEFT JOIN income_candidates f ON m.ts_code = f.ts_code AND m.end_date = f.end_date
),
matched AS (
    SELECT *, toUInt8(ifNull(
        _candidate_exists = 1 AND (_summary_sales IS NOT NULL OR _summary_cost IS NOT NULL)
        AND (_summary_sales IS NULL OR (isFinite(_summary_sales) AND isFinite(_income_revenue)
            AND abs(_summary_sales - _income_revenue) <= 0.01))
        AND (_summary_cost IS NULL OR (isFinite(_summary_cost) AND isFinite(_income_cost)
            AND abs(_summary_cost - _income_cost) <= 0.01)), 0)) AS _amount_match
    FROM joined
),
ranked AS (
    SELECT *,
        countIf(_candidate_exists = 1) OVER (PARTITION BY ts_code, end_date, bz_code, bz_item, curr_type, sys_from) AS _candidate_count,
        countIf(_amount_match = 1) OVER (PARTITION BY ts_code, end_date, bz_code, bz_item, curr_type, sys_from) AS _amount_count,
        row_number() OVER (
            PARTITION BY ts_code, end_date, bz_code, bz_item, curr_type, sys_from
            ORDER BY _amount_match DESC, _income_available DESC,
                greatest(_income_ann, _income_fann) DESC, _income_fann DESC,
                _income_ann DESC, _income_records DESC
        ) AS _rank,
        multiIf(_amount_match = 1, 'amount_match', _candidate_exists = 1,
            'report_period_latest', 'no_valid_report') AS _method
    FROM matched
)
SELECT
    r.`ts_code` AS `ts_code`,
    r.`end_date` AS `end_date`,
    r.`bz_item` AS `bz_item`,
    r.`bz_code` AS `bz_code`,
    r.`bz_sales` AS `bz_sales`,
    r.`bz_profit` AS `bz_profit`,
    r.`bz_cost` AS `bz_cost`,
    r.`curr_type` AS `curr_type`,
    r.`update_flag` AS `update_flag`,
    r.`instrument_id` AS `instrument_id`,
    r.`instrument_type` AS `instrument_type`,
    r.`exchange` AS `exchange`,
    r.`source_code` AS `source_code`,
    r.`event_date` AS `event_date`,
    _income_available AS `available_trade_date`,
    r.`sys_from` AS `sys_from`,
    r.`sys_to` AS `sys_to`,
    r.`source` AS `source`,
    'dwd_stock_main_business,dwd_stock_income' AS `source_table`,
    r.`source_batch_id` AS `source_batch_id`,
    lower(hex(MD5(toJSONString(tuple(r.source_record_hash, _summary_records, _income_records, _method))))) AS `source_record_hash`,
    if(_candidate_exists = 1, 'income_disclosure_proxy', 'unknown_disclosure_date') AS `availability_basis`,
    _income_ann AS `ann_date`,
    _income_fann AS `f_ann_date`,
    now64(3) AS `build_time`,
    _method AS `date_match_method`,
    toJSONString(if(_amount_match = 1, arrayFilter(x -> x != '', [if(_summary_sales IS NOT NULL, 'bz_sales:revenue', ''), if(_summary_cost IS NOT NULL, 'bz_cost:oper_cost', '')]), CAST([], 'Array(String)'))) AS `date_match_fields`,
    0 AS `is_public_date_pit_eligible`,
    _candidate_count AS `date_candidate_count`,
    _amount_count AS `amount_candidate_count`,
    _summary_sales AS `matching_sales`,
    _summary_cost AS `matching_cost`,
    _income_revenue AS `income_revenue`,
    _income_cost AS `income_oper_cost`,
    if(_amount_match = 1 AND _summary_sales IS NOT NULL, abs(_summary_sales - _income_revenue), CAST(NULL, 'Nullable(Float64)')) AS `sales_match_error`,
    if(_amount_match = 1 AND _summary_cost IS NOT NULL, abs(_summary_cost - _income_cost), CAST(NULL, 'Nullable(Float64)')) AS `cost_match_error`,
    _income_records AS `income_source_records`,
    _summary_records AS `main_business_summary_records`,
    r.`source_record_hash` AS `main_business_source_record_hash`,
    r.`source_table` AS `main_business_source_table`,
    r.`available_trade_date` AS `main_business_available_trade_date`,
    r.`availability_basis` AS `main_business_availability_basis`
FROM ranked r WHERE _rank = 1
SETTINGS join_use_nulls = 1
;
