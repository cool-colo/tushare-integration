
INSERT INTO default.dwd_stock_suspend

SELECT
    src.`ts_code`,
    src.`trade_date`,
    src.`suspend_timing`,
    src.`suspend_type`,
    concat('stock:', src.ts_code) AS `instrument_id`,
    'stock' AS `instrument_type`,
    arrayElement(splitByChar('.', assumeNotNull(src.ts_code)), 2) AS `exchange`,
    src.ts_code AS `source_code`,
    src.trade_date AS `event_date`,
    CAST(NULL, 'Nullable(Date32)') AS `available_trade_date`,
    src._ingest_time AS `sys_from`,
    src._next_sys_from AS `sys_to`,
    src._source AS `source`,
    'suspend_d_raw' AS `source_table`,
    src._batch_id AS `source_batch_id`,
    src._record_hash AS `source_record_hash`,
    'unknown_disclosure_date' AS `availability_basis`
FROM (
    SELECT
        src.*,
        leadInFrame(_ingest_time, 1, toDateTime64('9999-12-31 00:00:00', 3)) OVER (
            PARTITION BY `ts_code`, `trade_date`, `suspend_type`
            ORDER BY _ingest_time, _batch_id, _record_hash
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS _next_sys_from
        , max(toUInt8(ifNull(
                _prev_ingest_time = _ingest_time AND _prev_record_hash != _record_hash, 0
            ))) OVER (PARTITION BY `ts_code`, `trade_date`, `suspend_type`
                ORDER BY _ingest_time, _batch_id, _record_hash
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS _key_conflict
        
    FROM (
        SELECT
            src.*,
            lagInFrame(_record_hash) OVER (
                PARTITION BY `ts_code`, `trade_date`, `suspend_type`
                ORDER BY _ingest_time, _batch_id, _record_hash
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
            ) AS _prev_record_hash
            , lagInFrame(_ingest_time) OVER (PARTITION BY `ts_code`, `trade_date`, `suspend_type`
                ORDER BY _ingest_time, _batch_id, _record_hash
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS _prev_ingest_time
        FROM default.suspend_d_raw src
        WHERE src.`ts_code` IS NOT NULL AND src.`trade_date` IS NOT NULL AND src.`suspend_type` IS NOT NULL AND src.`trade_date` >= toDate32('2010-01-01') AND (src.ts_code != '' AND src.suspend_type != '')
    ) src
    WHERE src._prev_record_hash IS NULL OR src._prev_record_hash != src._record_hash
) src

WHERE src._key_conflict = 0
;
