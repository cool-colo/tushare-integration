
INSERT INTO v2_scalar_rebuild_20261123.dwd_stock_top_list_rebuilt
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
        FROM v2_scalar_rebuild_20261123.trade_cal
        WHERE exchange = 'SSE'
        GROUP BY cal_date
    )
)
SELECT
    src.`trade_date`,
    src.`ts_code`,
    src.`name`,
    src.`close`,
    src.`pct_change`,
    src.`turnover_rate`,
    src.`amount`,
    src.`l_sell`,
    src.`l_buy`,
    src.`l_amount`,
    src.`net_amount`,
    src.`net_rate`,
    src.`amount_rate`,
    src.`float_values`,
    src.`reason`,
    concat('stock:', src.ts_code) AS `instrument_id`,
    'stock' AS `instrument_type`,
    arrayElement(splitByChar('.', assumeNotNull(src.ts_code)), 2) AS `exchange`,
    src.ts_code AS `source_code`,
    src.trade_date AS `event_date`,
    addDays(assumeNotNull(calendar_map.next_trade_date), throwIf(isNull(calendar_map.next_trade_date), 'Missing SSE next trading day')) AS `available_trade_date`,
    src._ingest_time AS `sys_from`,
    src._next_sys_from AS `sys_to`,
    src._source AS `source`,
    'top_list_raw' AS `source_table`,
    src._batch_id AS `source_batch_id`,
    src._record_hash AS `source_record_hash`
FROM (
    SELECT
        src.*,
        leadInFrame(_ingest_time, 1, toDateTime64('9999-12-31 00:00:00', 3)) OVER (
            PARTITION BY `ts_code`, `trade_date`
            ORDER BY _ingest_time, _batch_id, _record_hash
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS _next_sys_from
        ,
        src.trade_date AS _calendar_lookup_date
    FROM (
        SELECT
            src.*,
            lagInFrame(_record_hash) OVER (
                PARTITION BY `ts_code`, `trade_date`
                ORDER BY _ingest_time, _batch_id, _record_hash
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
            ) AS _prev_record_hash
        FROM v2_scalar_rebuild_20261123.top_list_raw src
        WHERE src.`ts_code` IS NOT NULL AND src.`trade_date` IS NOT NULL AND src.`trade_date` >= toDate32('2010-01-01')
    ) src
    WHERE src._prev_record_hash IS NULL OR src._prev_record_hash != src._record_hash
) src
LEFT JOIN calendar_map ON calendar_map.calendar_date = src._calendar_lookup_date
