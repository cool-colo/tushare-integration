-- dws_stock_factor_wide_v2 手工验收 SQL
-- ClickHouse / default database. 每段查询均可单独执行。

-- 1. 表规模、唯一性及原始 Tushare TTM 字段。
SELECT
    count() AS rows,
    uniqExact(instrument_id, trade_date) AS unique_keys,
    min(trade_date) AS min_trade_date,
    max(trade_date) AS max_trade_date
FROM default.dws_stock_factor_wide_v2;

SELECT name, type, position
FROM system.columns
WHERE database = 'default'
  AND table = 'dws_stock_factor_wide_v2'
  AND name IN ('pe_ttm', 'ps_ttm', 'dv_ttm')
ORDER BY position;

-- 2. 扩展范围和同前缀相邻顺序。预期缺失列数全部为 0；
-- interestdebt 的 23 列应连续排列为 mrq_0..8, ttm_0..8, lyr_0..4。
WITH
    arrayConcat(
        arrayMap(i -> concat('interestdebt_mrq_', toString(i)), range(9)),
        arrayMap(i -> concat('interestdebt_ttm_', toString(i)), range(9)),
        arrayMap(i -> concat('interestdebt_lyr_', toString(i)), range(5))
    ) AS expected
SELECT
    arrayFilter(x -> NOT has(actual, x), expected) AS missing_columns,
    arrayMap(x -> indexOf(actual, x), expected) AS positions,
    arraySort(arrayMap(x -> indexOf(actual, x), expected)) =
        range(arrayMin(arrayMap(x -> indexOf(actual, x), expected)),
              arrayMax(arrayMap(x -> indexOf(actual, x), expected)) + 1) AS positions_are_contiguous
FROM
(
    SELECT groupArray(name) AS actual
    FROM
    (
        SELECT name
        FROM system.columns
        WHERE database = 'default' AND table = 'dws_stock_factor_wide_v2'
        ORDER BY position
    )
);

-- 3. _lf/_ttm 派生列迁移检查。预期 old_derived_names_remaining = []，
-- 新列 MRQ/TTM 均有 0..8；pe_ttm/ps_ttm/dv_ttm 是保留的原始字段。
SELECT
    arraySort(groupArrayIf(name,
        (endsWith(name, '_lf') OR endsWith(name, '_ttm'))
        AND name NOT IN ('pe_ttm', 'ps_ttm', 'dv_ttm')
    )) AS old_derived_names_remaining,
    countIf(match(name, '_mrq_[0-8]$')) AS mrq_columns,
    countIf(match(name, '_ttm_[0-8]$')) AS ttm_columns,
    countIf(match(name, '_lyr_[0-4]$')) AS lyr_columns
FROM system.columns
WHERE database = 'default' AND table = 'dws_stock_factor_wide_v2';

-- 4. 固定报告期索引：2026-04-10 对应的可用日为 2026-04-13，
-- MRQ0 固定指向 2026-03-31。该报告当时尚未披露，所以 v2 MRQ0 必须为 NULL；
-- v2 MRQ1 指向 2025-12-31，并应与旧表“首个已披露报告”MRQ0 相等。
SELECT
    v2.instrument_id,
    v2.trade_date,
    v2.available_trade_date,
    addDays(toStartOfQuarter(addDays(v2.available_trade_date, 1)), -1) AS mrq_0_period,
    v2.total_assets_mrq_0 AS v2_expected_missing,
    v2.total_assets_mrq_1,
    old.total_assets_mrq_0 AS old_first_visible,
    v2.total_assets_mrq_1 = old.total_assets_mrq_0 AS shifted_value_matches
FROM default.dws_stock_factor_wide_v2 v2
LEFT JOIN default.dws_stock_factor_wide old
    USING (instrument_id, trade_date)
WHERE v2.source_code = '000001.SZ' AND v2.trade_date = '2026-04-10';

-- 5. 报告已经披露后的 index 0：2026-05-08 时 MRQ0 与旧表首个已披露报告一致。
SELECT
    v2.instrument_id,
    v2.trade_date,
    v2.available_trade_date,
    addDays(toStartOfQuarter(addDays(v2.available_trade_date, 1)), -1) AS mrq_0_period,
    v2.total_assets_mrq_0,
    old.total_assets_mrq_0 AS old_first_visible,
    v2.total_assets_mrq_0 = old.total_assets_mrq_0 AS same_value
FROM default.dws_stock_factor_wide_v2 v2
LEFT JOIN default.dws_stock_factor_wide old
    USING (instrument_id, trade_date)
WHERE v2.source_code = '000001.SZ' AND v2.trade_date = '2026-05-08';

-- 6. 年报固定索引：2026-01-09 的 LYR0 必须固定指向 2025-12-31；未披露则为 NULL。
SELECT
    instrument_id,
    trade_date,
    available_trade_date,
    toDate(concat(toString(toYear(addDays(available_trade_date, 1)) - 1), '-12-31')) AS lyr_0_period,
    total_assets_lyr_0,
    total_assets_lyr_1,
    total_assets_lyr_2,
    total_assets_lyr_3,
    total_assets_lyr_4
FROM default.dws_stock_factor_wide_v2
WHERE source_code = '000001.SZ' AND trade_date = '2026-01-09';

-- 7. TTM 加和缺字段策略：先找四个报告期都存在、但 fin_exp_int_inc 有 1~3 个 NULL 的样本。
-- expected_ttm = 非空值之和 / 非空数 * 4；actual_ttm 应与 expected_ttm 一致。
WITH
reports AS
(
    SELECT * EXCEPT report_rank
    FROM
    (
        SELECT
            src.*,
            row_number() OVER
            (
                PARTITION BY instrument_id, event_date, available_trade_date
                ORDER BY build_time DESC, source_record_hash DESC
            ) AS report_rank
        FROM default.dws_stock_income_quarter src
    )
    WHERE report_rank = 1
),
periods AS
(
    SELECT
        v.instrument_id,
        v.trade_date,
        v.available_trade_date,
        v.fin_exp_int_inc_ttm_0 AS actual_ttm,
        report_offset,
        addDays(addMonths(toStartOfQuarter(addDays(v.available_trade_date, 1)),
                          -3 * toInt32(report_offset)), -1) AS report_period
    FROM default.dws_stock_factor_wide_v2 v
    ARRAY JOIN range(4) AS report_offset
    WHERE v.trade_date = (SELECT max(trade_date) FROM default.dws_stock_factor_wide_v2)
),
selected AS
(
    SELECT
        p.*,
        if(r.source_record_hash != '', 1, 0) AS report_exists,
        r.fin_exp_int_inc
    FROM periods p
    ASOF LEFT JOIN reports r
        ON p.instrument_id = r.instrument_id
       AND p.report_period = r.event_date
       AND p.available_trade_date >= r.available_trade_date
)
SELECT
    instrument_id,
    any(trade_date) AS trade_date,
    groupArray((report_period, fin_exp_int_inc)) AS four_period_values,
    countIf(report_exists = 1) AS existing_reports,
    countIf(fin_exp_int_inc IS NOT NULL) AS nonnull_values,
    any(actual_ttm) AS actual_ttm,
    sum(ifNull(fin_exp_int_inc, 0.0)) / countIf(fin_exp_int_inc IS NOT NULL) * 4 AS expected_ttm,
    abs(actual_ttm - expected_ttm) <= greatest(1e-8, abs(expected_ttm) * 1e-10) AS matches
FROM selected
GROUP BY instrument_id
HAVING existing_reports = 4 AND nonnull_values BETWEEN 1 AND 3
LIMIT 10;

-- 8. TTM 平均缺字段策略：具体样本 603083.SH / 2019-04-23 / index 3。
-- 四期报告都存在，acc_exp 只有 2017-09-30 的 10806949.98 非空，
-- 所以 expected_ttm = 10806949.98 / 1，且应与 actual_ttm 相等。
WITH
reports AS
(
    SELECT * EXCEPT report_rank
    FROM
    (
        SELECT
            src.*,
            row_number() OVER
            (
                PARTITION BY instrument_id, event_date, available_trade_date
                ORDER BY
                    multiIf(report_type = '4', 2, report_type = '1', 1, 0) DESC,
                    f_ann_date DESC, update_flag DESC, sys_from DESC, source_record_hash DESC
            ) AS report_rank
        FROM default.dwd_stock_balance_sheet src
        WHERE sys_to = toDateTime64('9999-12-31 00:00:00', 3)
          AND report_type IN ('1', '4')
          AND ann_date >= event_date
    )
    WHERE report_rank = 1
),
periods AS
(
    SELECT
        v.instrument_id,
        v.trade_date,
        v.available_trade_date,
        v.acc_exp_ttm_3 AS actual_ttm,
        report_offset,
        addDays(addMonths(toStartOfQuarter(addDays(v.available_trade_date, 1)),
                          -3 * toInt32(report_offset)), -1) AS report_period
    FROM default.dws_stock_factor_wide_v2 v
    ARRAY JOIN range(3, 7) AS report_offset
    WHERE v.source_code = '603083.SH' AND v.trade_date = '2019-04-23'
),
selected AS
(
    SELECT
        p.*,
        if(r.source_record_hash != '', 1, 0) AS report_exists,
        r.acc_exp
    FROM periods p
    ASOF LEFT JOIN reports r
        ON p.instrument_id = r.instrument_id
       AND p.report_period = r.event_date
       AND p.available_trade_date >= r.available_trade_date
)
SELECT
    instrument_id,
    any(trade_date) AS trade_date,
    groupArray((report_period, acc_exp)) AS four_period_values,
    countIf(report_exists = 1) AS existing_reports,
    countIf(acc_exp IS NOT NULL) AS nonnull_values,
    any(actual_ttm) AS actual_ttm,
    sum(ifNull(acc_exp, 0.0)) / countIf(acc_exp IS NOT NULL) AS expected_ttm,
    abs(actual_ttm - expected_ttm) <= greatest(1e-8, abs(expected_ttm) * 1e-10) AS matches
FROM selected
GROUP BY instrument_id
HAVING existing_reports = 4 AND nonnull_values BETWEEN 1 AND 3
;

-- 9. TTM 缺报告期策略：只要四个固定期间中少一个报告，整体必须为 NULL。
-- 该查询应返回实际值为 NULL 的样本，bad_nonnull 必须为 0。
WITH latest_date AS
(
    SELECT max(trade_date) AS trade_date FROM default.dws_stock_factor_wide_v2
),
report_periods AS
(
    SELECT
        v.instrument_id,
        v.trade_date,
        v.available_trade_date,
        v.revenue_ttm_0,
        addDays(addMonths(toStartOfQuarter(addDays(v.available_trade_date, 1)),
                          -3 * toInt32(report_offset)), -1) AS report_period
    FROM default.dws_stock_factor_wide_v2 v
    ARRAY JOIN range(4) AS report_offset
    WHERE v.trade_date = (SELECT trade_date FROM latest_date)
),
visible_reports AS
(
    SELECT
        p.instrument_id,
        p.trade_date,
        p.revenue_ttm_0,
        p.report_period,
        r.source_record_hash
    FROM report_periods p
    ASOF LEFT JOIN
    (
        SELECT instrument_id, event_date, available_trade_date, source_record_hash
        FROM default.dws_stock_income_quarter
        ORDER BY instrument_id, event_date, available_trade_date
    ) r
        ON p.instrument_id = r.instrument_id
       AND p.report_period = r.event_date
       AND p.available_trade_date >= r.available_trade_date
)
SELECT
    instrument_id,
    any(trade_date) AS trade_date,
    countIf(source_record_hash != '') AS existing_reports,
    any(revenue_ttm_0) AS actual_ttm,
    isNotNull(actual_ttm) AS bad_nonnull
FROM visible_reports
GROUP BY instrument_id
HAVING existing_reports < 4
ORDER BY bad_nonnull DESC, instrument_id
LIMIT 10;

-- 10. 全量新旧 index 对齐统计：v2 MRQ0 非空时应对应旧 MRQ0；
-- v2 MRQ0 为空而 MRQ1 非空时，旧 MRQ0 应对应 v2 MRQ1。
-- not_in_first_two 还包含连续缺两期以上、旧值落入 v2 index 2..8 的正常场景。
SELECT
    count() AS compared_rows,
    countIf(isNotNull(v2.total_assets_mrq_0)
            AND v2.total_assets_mrq_0 = old.total_assets_mrq_0) AS same_index_0,
    countIf(isNull(v2.total_assets_mrq_0)
            AND isNotNull(v2.total_assets_mrq_1)
            AND v2.total_assets_mrq_1 = old.total_assets_mrq_0) AS old_0_matches_v2_1,
    countIf(isNotNull(old.total_assets_mrq_0)
            AND NOT (
                (isNotNull(v2.total_assets_mrq_0) AND v2.total_assets_mrq_0 = old.total_assets_mrq_0)
                OR
                (isNull(v2.total_assets_mrq_0) AND isNotNull(v2.total_assets_mrq_1)
                 AND v2.total_assets_mrq_1 = old.total_assets_mrq_0)
            )) AS not_in_first_two
FROM default.dws_stock_factor_wide_v2 v2
INNER JOIN default.dws_stock_factor_wide old USING (instrument_id, trade_date);

-- 原版 MRQ0 在 v2 固定槽位 0..8 的首次匹配位置；-2 表示原版值为空，
-- -1 表示在 v2 前九个固定季度内未找到相同值。
SELECT match_index, count() AS rows
FROM
(
    SELECT
        if(
            isNull(old.total_assets_mrq_0),
            -2,
            toInt32(arrayFirstIndex(
                x -> isNotNull(x) AND x = old.total_assets_mrq_0,
                [
                    v2.total_assets_mrq_0, v2.total_assets_mrq_1, v2.total_assets_mrq_2,
                    v2.total_assets_mrq_3, v2.total_assets_mrq_4, v2.total_assets_mrq_5,
                    v2.total_assets_mrq_6, v2.total_assets_mrq_7, v2.total_assets_mrq_8
                ]
            )) - 1
        ) AS match_index
    FROM default.dws_stock_factor_wide_v2 v2
    INNER JOIN default.dws_stock_factor_wide old USING (instrument_id, trade_date)
)
GROUP BY match_index
ORDER BY match_index;
