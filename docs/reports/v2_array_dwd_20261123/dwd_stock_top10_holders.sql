
INSERT INTO v2_array_dwd_rebuild_20261123.dwd_stock_top10_holders
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
        FROM v2_array_dwd_rebuild_20261123.trade_cal
        WHERE exchange = 'SSE'
        GROUP BY cal_date
    )
)
SELECT
    src.`ts_code`,
    src.`ann_date`,
    src.`end_date`,
    src.`holder_name`,
    src.`hold_amount`,
    src.`hold_ratio`,
    src.`hold_float_ratio`,
    src.`hold_change`,
    src.`holder_type`,
    concat('stock:', src.ts_code) AS `instrument_id`,
    'stock' AS `instrument_type`,
    arrayElement(splitByChar('.', assumeNotNull(src.ts_code)), 2) AS `exchange`,
    src.ts_code AS `source_code`,
    src.end_date AS `event_date`,
    addDays(assumeNotNull(calendar_map.next_trade_date), throwIf(isNull(calendar_map.next_trade_date), 'Missing SSE next trading day for top holder announcement')) AS `available_trade_date`,
    src._ingest_time AS `sys_from`,
    src._next_sys_from AS `sys_to`,
    src._source AS `source`,
    'top10_holders_raw' AS `source_table`,
    src._batch_id AS `source_batch_id`,
    src._record_hash AS `source_record_hash`,
    'top10_holders' AS `source_kind`
FROM (
    SELECT
        src.*,
        leadInFrame(_ingest_time, 1, toDateTime64('9999-12-31 00:00:00', 3)) OVER (
            PARTITION BY `ts_code`, `end_date`, `ann_date`, `holder_name`
            ORDER BY _ingest_time, _batch_id, _record_hash
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS _next_sys_from
        ,
        src.ann_date AS _calendar_lookup_date
    FROM (
        SELECT
            src.*,
            lagInFrame(_record_hash) OVER (
                PARTITION BY `ts_code`, `end_date`, `ann_date`, `holder_name`
                ORDER BY _ingest_time, _batch_id, _record_hash
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
            ) AS _prev_record_hash
        FROM v2_array_dwd_rebuild_20261123.top10_holders_raw src
        WHERE src.`ts_code` IS NOT NULL AND src.`end_date` IS NOT NULL AND src.`ann_date` IS NOT NULL AND src.`holder_name` IS NOT NULL AND (src.ts_code != '' AND src.holder_name != '') AND (src.end_date > toDate32('1971-01-01') AND src.ann_date >= src.end_date)
    ) src
    WHERE src._prev_record_hash IS NULL OR src._prev_record_hash != src._record_hash
) src
LEFT JOIN calendar_map ON calendar_map.calendar_date = src._calendar_lookup_date
