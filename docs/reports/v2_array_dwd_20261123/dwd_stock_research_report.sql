
INSERT INTO v2_array_dwd_rebuild_20261123.dwd_stock_research_report
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
    src.`name`,
    src.`report_date`,
    src.`report_title`,
    src.`report_type`,
    src.`classify`,
    src.`org_name`,
    src.`author_name`,
    src.`quarter`,
    src.`op_rt`,
    src.`op_pr`,
    src.`tp`,
    src.`np`,
    src.`eps`,
    src.`pe`,
    src.`rd`,
    src.`roe`,
    src.`ev_ebitda`,
    src.`rating`,
    src.`max_price`,
    src.`min_price`,
    src.`imp_dg`,
    src.`create_time`,
    concat('stock:', src.ts_code) AS `instrument_id`,
    'stock' AS `instrument_type`,
    arrayElement(splitByChar('.', assumeNotNull(src.ts_code)), 2) AS `exchange`,
    src.ts_code AS `source_code`,
    src.report_date AS `event_date`,
    addDays(assumeNotNull(calendar_map.next_trade_date), throwIf(isNull(calendar_map.next_trade_date), 'Missing SSE next trading day for research report')) AS `available_trade_date`,
    src._ingest_time AS `sys_from`,
    src._next_sys_from AS `sys_to`,
    src._source AS `source`,
    'report_rc_raw' AS `source_table`,
    src._batch_id AS `source_batch_id`,
    src._record_hash AS `source_record_hash`,
    if(match(ifNull(src.quarter, ''), '^[0-9]{4}Q[1-4]$'), toDate32(concat(substring(assumeNotNull(src.quarter), 1, 4), arrayElement(['-03-31', '-06-30', '-09-30', '-12-31'], toUInt8(substring(assumeNotNull(src.quarter), 6, 1))))), CAST(NULL, 'Nullable(Date32)')) AS `forecast_period_end`
FROM (
    SELECT
        src.*,
        leadInFrame(_ingest_time, 1, toDateTime64('9999-12-31 00:00:00', 3)) OVER (
            PARTITION BY `ts_code`, `report_date`, `org_name`, `report_title`, `author_name`, `quarter`, `report_type`, `classify`, `create_time`
            ORDER BY _ingest_time, _batch_id, _record_hash
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS _next_sys_from
        ,
        greatest(src.report_date, toDate(src.create_time)) AS _calendar_lookup_date
    FROM (
        SELECT
            src.*,
            lagInFrame(_record_hash) OVER (
                PARTITION BY `ts_code`, `report_date`, `org_name`, `report_title`, `author_name`, `quarter`, `report_type`, `classify`, `create_time`
                ORDER BY _ingest_time, _batch_id, _record_hash
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
            ) AS _prev_record_hash
        FROM v2_array_dwd_rebuild_20261123.report_rc_raw src
        WHERE src.`ts_code` IS NOT NULL AND src.`report_date` IS NOT NULL AND src.`org_name` IS NOT NULL AND src.`classify` IS NOT NULL AND src.`create_time` IS NOT NULL
    ) src
    WHERE src._prev_record_hash IS NULL OR src._prev_record_hash != src._record_hash
) src
LEFT JOIN calendar_map ON calendar_map.calendar_date = src._calendar_lookup_date
