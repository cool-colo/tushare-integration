
INSERT INTO v2_array_dwd_rebuild_20261123.dwd_stock_ccass_holding_detail

SELECT
    src.`trade_date`,
    src.`ts_code`,
    src.`name`,
    src.`col_participant_id`,
    src.`col_participant_name`,
    src.`col_shareholding`,
    src.`col_shareholding_percent`,
    concat('stock:', src.ts_code) AS `instrument_id`,
    'stock' AS `instrument_type`,
    arrayElement(splitByChar('.', assumeNotNull(src.ts_code)), 2) AS `exchange`,
    src.ts_code AS `source_code`,
    src.trade_date AS `event_date`,
    CAST(NULL, 'Nullable(Date32)') AS `available_trade_date`,
    src._ingest_time AS `sys_from`,
    src._next_sys_from AS `sys_to`,
    src._source AS `source`,
    'ccass_hold_detail_raw' AS `source_table`,
    src._batch_id AS `source_batch_id`,
    src._record_hash AS `source_record_hash`,
    'unknown_disclosure_date' AS `availability_basis`,
    if(match(trimBoth(ifNull(src.col_shareholding, '')), '^([0-9]+|[0-9]{1,3}(,[0-9]{3})+)([.][0-9]+)?$'), toFloat64OrNull(replaceAll(trimBoth(src.col_shareholding), ',', '')), CAST(NULL, 'Nullable(Float64)')) AS `shareholding`,
    if(match(trimBoth(ifNull(src.col_shareholding_percent, '')), '^[0-9]+([.][0-9]+)?[ ]*%?$'), toFloat64OrNull(trimBoth(replaceAll(src.col_shareholding_percent, '%', ''))) / 100, CAST(NULL, 'Nullable(Float64)')) AS `shareholding_percent`
FROM (
    SELECT
        src.*,
        leadInFrame(_ingest_time, 1, toDateTime64('9999-12-31 00:00:00', 3)) OVER (
            PARTITION BY `ts_code`, `trade_date`, `col_participant_id`
            ORDER BY _ingest_time, _batch_id, _record_hash
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS _next_sys_from
        
    FROM (
        SELECT
            src.*,
            lagInFrame(_record_hash) OVER (
                PARTITION BY `ts_code`, `trade_date`, `col_participant_id`
                ORDER BY _ingest_time, _batch_id, _record_hash
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
            ) AS _prev_record_hash
        FROM v2_array_dwd_rebuild_20261123.ccass_hold_detail_raw src
        WHERE src.`ts_code` IS NOT NULL AND src.`trade_date` IS NOT NULL AND src.`col_participant_id` IS NOT NULL AND src.`trade_date` >= toDate32('2010-01-01') AND (src.ts_code != '' AND src.col_participant_id != '')
    ) src
    WHERE src._prev_record_hash IS NULL OR src._prev_record_hash != src._record_hash
) src

