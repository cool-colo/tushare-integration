
INSERT INTO v2_array_dwd_rebuild_20261123.dwd_fund_portfolio_quarantine
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
    src.`symbol`,
    src.`mkv`,
    src.`amount`,
    src.`stk_mkv_ratio`,
    src.`stk_float_ratio`,
    concat('stock:', src.symbol) AS `instrument_id`,
    'stock' AS `instrument_type`,
    arrayElement(splitByChar('.', assumeNotNull(src.symbol)), 2) AS `exchange`,
    src.symbol AS `source_code`,
    src.end_date AS `event_date`,
    CAST(NULL, 'Nullable(Date32)') AS `available_trade_date`,
    src._ingest_time AS `sys_from`,
    CAST(NULL, 'Nullable(DateTime64(3))') AS `sys_to`,
    src._source AS `source`,
    'fund_portfolio_raw' AS `source_table`,
    src._batch_id AS `source_batch_id`,
    src._record_hash AS `source_record_hash`,
    concat('fund:', src.ts_code) AS `fund_id`,
    CAST(NULL, 'Nullable(Int64)') AS `is_complete_holdings`,
    'ambiguous_same_time_versions' AS `quarantine_reason`
FROM (
    SELECT
        src.*,
        leadInFrame(_ingest_time, 1, toDateTime64('9999-12-31 00:00:00', 3)) OVER (
            PARTITION BY `ts_code`, `ann_date`, `end_date`, `symbol`
            ORDER BY _ingest_time, _batch_id, _record_hash
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS _next_sys_from
        , max(toUInt8(ifNull(
                _prev_ingest_time = _ingest_time AND _prev_record_hash != _record_hash, 0
            ))) OVER (PARTITION BY `ts_code`, `ann_date`, `end_date`, `symbol`
                ORDER BY _ingest_time, _batch_id, _record_hash
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS _key_conflict
        ,
        src.ann_date AS _calendar_lookup_date
    FROM (
        SELECT
            src.*,
            lagInFrame(_record_hash) OVER (
                PARTITION BY `ts_code`, `ann_date`, `end_date`, `symbol`
                ORDER BY _ingest_time, _batch_id, _record_hash
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
            ) AS _prev_record_hash
            , lagInFrame(_ingest_time) OVER (PARTITION BY `ts_code`, `ann_date`, `end_date`, `symbol`
                ORDER BY _ingest_time, _batch_id, _record_hash
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS _prev_ingest_time
        FROM v2_array_dwd_rebuild_20261123.fund_portfolio_source_sharded src
        WHERE src.`ts_code` IS NOT NULL AND src.`ann_date` IS NOT NULL AND src.`end_date` IS NOT NULL AND src.`symbol` IS NOT NULL AND (cityHash64(src.`ts_code`) % 16 = 15)
    ) src
    WHERE src._prev_record_hash IS NULL OR src._prev_record_hash != src._record_hash
) src
LEFT JOIN calendar_map ON calendar_map.calendar_date = src._calendar_lookup_date
WHERE src._key_conflict = 1
