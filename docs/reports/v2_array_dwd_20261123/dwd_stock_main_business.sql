
INSERT INTO v2_array_dwd_rebuild_20261123.dwd_stock_main_business

SELECT
    src.`ts_code`,
    src.`end_date`,
    src.`bz_item`,
    src.`bz_code`,
    src.`bz_sales`,
    src.`bz_profit`,
    src.`bz_cost`,
    src.`curr_type`,
    src.`update_flag`,
    concat('stock:', src.ts_code) AS `instrument_id`,
    'stock' AS `instrument_type`,
    arrayElement(splitByChar('.', assumeNotNull(src.ts_code)), 2) AS `exchange`,
    src.ts_code AS `source_code`,
    src.end_date AS `event_date`,
    CAST(NULL, 'Nullable(Date32)') AS `available_trade_date`,
    src._ingest_time AS `sys_from`,
    src._next_sys_from AS `sys_to`,
    src._source AS `source`,
    'fina_mainbz_raw' AS `source_table`,
    src._batch_id AS `source_batch_id`,
    src._record_hash AS `source_record_hash`,
    'unknown_disclosure_date' AS `availability_basis`
FROM (
    SELECT
        src.*,
        leadInFrame(_ingest_time, 1, toDateTime64('9999-12-31 00:00:00', 3)) OVER (
            PARTITION BY `ts_code`, `end_date`, `bz_code`, `bz_item`, `curr_type`
            ORDER BY _ingest_time, _batch_id, _record_hash
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS _next_sys_from
        
    FROM (
        SELECT
            src.*,
            lagInFrame(_record_hash) OVER (
                PARTITION BY `ts_code`, `end_date`, `bz_code`, `bz_item`, `curr_type`
                ORDER BY _ingest_time, _batch_id, _record_hash
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
            ) AS _prev_record_hash
        FROM v2_array_dwd_rebuild_20261123.fina_mainbz_raw src
        WHERE src.`ts_code` IS NOT NULL AND src.`end_date` IS NOT NULL AND src.`bz_code` IS NOT NULL AND src.`bz_item` IS NOT NULL AND (src.ts_code != '' AND src.bz_item != '') AND (src.end_date > toDate32('1971-01-01'))
    ) src
    WHERE src._prev_record_hash IS NULL OR src._prev_record_hash != src._record_hash
) src

