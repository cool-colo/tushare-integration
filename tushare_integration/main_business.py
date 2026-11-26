"""Disclosure proxies from DWD income, without inventing main-business PIT history."""

from copy import deepcopy

from tushare_integration.dwd import DWDManager


MAIN_TABLE = "dwd_stock_main_business"
INCOME_TABLE = "dwd_stock_income"
PRESERVED_COLUMNS = {
    "source_record_hash": "main_business_source_record_hash",
    "source_table": "main_business_source_table",
    "available_trade_date": "main_business_available_trade_date",
    "availability_basis": "main_business_availability_basis",
}


def main_schema(manager):
    dwd = DWDManager()
    dwd.settings = manager.settings
    return dwd.build_schema(dwd.load_spec(MAIN_TABLE))


def build_schema(manager, spec):
    schema = deepcopy(main_schema(manager))
    schema.update(comment=spec["comment"], partition_key=spec["partition_key"], indexes=spec["indexes"])
    schema["columns"].extend(deepcopy(spec["extra_columns"]))
    return schema


def candidate_ctes(manager):
    """Keep every observed income amount version; reject fabricated calendar dates."""
    db = manager.settings.database.db_name
    dwd = DWDManager()
    dwd.settings = manager.settings
    return f"""
{dwd._calendar_map_sql()},
income_candidates AS (
    SELECT f.ts_code, f.end_date, f.ann_date, f.f_ann_date, f.available_trade_date,
        f.revenue, f.oper_cost, 1 AS candidate_exists,
        toJSONString(arraySort(groupUniqArray(tuple(
            f.source_record_hash, f.source_batch_id, f.sys_from, f.sys_to,
            f.update_flag, f.source, f.source_table
        )))) AS income_records
    FROM {db}.{INCOME_TABLE} f
    INNER JOIN calendar_map cal
        ON cal.calendar_date = greatest(f.ann_date, f.f_ann_date)
    WHERE f.report_type = '1'
        AND f.ann_date > toDate32('1971-01-01')
        AND f.f_ann_date > toDate32('1971-01-01')
        AND f.ann_date >= f.end_date AND f.f_ann_date >= f.end_date
        AND f.available_trade_date = cal.next_trade_date
        AND (f.ts_code, f.end_date) IN (
            SELECT DISTINCT ts_code, end_date FROM {db}.{MAIN_TABLE}
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
    FROM {db}.{MAIN_TABLE}
    WHERE curr_type = 'CNY'
        AND ((bz_code = 'P' AND bz_item = '产品')
            OR (bz_code = 'D' AND bz_item = '地区')
            OR (bz_code = 'I' AND bz_item = '行业'))
    GROUP BY ts_code, end_date, bz_code, curr_type, update_flag, sys_from, source_batch_id
)
"""


def render_sync_sql(manager, target):
    db = manager.settings.database.db_name
    # A normal DWD version has a unique business identity and observation time.
    identity = "ts_code, end_date, bz_code, bz_item, curr_type, sys_from"
    replacements = {
        "available_trade_date": "_income_available",
        "availability_basis": "if(_candidate_exists = 1, 'income_disclosure_proxy', 'unknown_disclosure_date')",
        "source_table": f"'{MAIN_TABLE},{INCOME_TABLE}'",
        "source_record_hash": "lower(hex(MD5(toJSONString(tuple(r.source_record_hash, _summary_records, _income_records, _method)))))",
    }
    columns = [
        f"{replacements.get(c['name'], 'r.`' + c['name'] + '`')} AS `{c['name']}`"
        for c in main_schema(manager)["columns"]
    ]
    extras = {
        "ann_date": "_income_ann", "f_ann_date": "_income_fann",
        "build_time": "now64(3)", "date_match_method": "_method",
        "date_match_fields": "toJSONString(if(_amount_match = 1, arrayFilter(x -> x != '', [if(_summary_sales IS NOT NULL, 'bz_sales:revenue', ''), if(_summary_cost IS NOT NULL, 'bz_cost:oper_cost', '')]), CAST([], 'Array(String)')))",
        "is_public_date_pit_eligible": "0", "date_candidate_count": "_candidate_count",
        "amount_candidate_count": "_amount_count", "matching_sales": "_summary_sales",
        "matching_cost": "_summary_cost", "income_revenue": "_income_revenue",
        "income_oper_cost": "_income_cost",
        "sales_match_error": "if(_amount_match = 1 AND _summary_sales IS NOT NULL, abs(_summary_sales - _income_revenue), CAST(NULL, 'Nullable(Float64)'))",
        "cost_match_error": "if(_amount_match = 1 AND _summary_cost IS NOT NULL, abs(_summary_cost - _income_cost), CAST(NULL, 'Nullable(Float64)'))",
        "income_source_records": "_income_records",
        "main_business_summary_records": "_summary_records",
        **{v: f"r.`{k}`" for k, v in PRESERVED_COLUMNS.items()},
    }
    columns.extend(f"{expr} AS `{name}`" for name, expr in extras.items())
    projection = ",\n    ".join(columns)
    main_projection = ", ".join(f"m.`{c['name']}` AS `{c['name']}`" for c in main_schema(manager)["columns"])
    return f"""
INSERT INTO {db}.{target}
WITH {candidate_ctes(manager)},
joined AS (
    SELECT {main_projection},
        ifNull(f.candidate_exists, 0) AS _candidate_exists,
        f.ann_date AS _income_ann, f.f_ann_date AS _income_fann,
        f.available_trade_date AS _income_available,
        f.revenue AS _income_revenue, f.oper_cost AS _income_cost,
        if(f.candidate_exists = 1, f.income_records, '[]') AS _income_records,
        if(h.summary_variants = 1, h.summary_sales, CAST(NULL, 'Nullable(Float64)')) AS _summary_sales,
        if(h.summary_variants = 1, h.summary_cost, CAST(NULL, 'Nullable(Float64)')) AS _summary_cost,
        if(h.summary_variants = 1, h.summary_records, '[]') AS _summary_records
    FROM {db}.{MAIN_TABLE} m
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
        countIf(_candidate_exists = 1) OVER (PARTITION BY {identity}) AS _candidate_count,
        countIf(_amount_match = 1) OVER (PARTITION BY {identity}) AS _amount_count,
        row_number() OVER (
            PARTITION BY {identity}
            ORDER BY _amount_match DESC, _income_available DESC,
                greatest(_income_ann, _income_fann) DESC, _income_fann DESC,
                _income_ann DESC, _income_records DESC
        ) AS _rank,
        multiIf(_amount_match = 1, 'amount_match', _candidate_exists = 1,
            'report_period_latest', 'no_valid_report') AS _method
    FROM matched
)
SELECT
    {projection}
FROM ranked r WHERE _rank = 1
SETTINGS join_use_nulls = 1
"""


def validation_rules(manager, target):
    """Validate preserved rows, actual selected income evidence and selection priority."""
    from tushare_integration.quality import ValidationRule

    db = manager.settings.database.db_name
    qualified = f"{db}.{target}"
    source_fields = ", ".join(f"`{c['name']}`" for c in main_schema(manager)["columns"])
    target_fields = ", ".join(
        f"`{PRESERVED_COLUMNS.get(c['name'], c['name'])}`" for c in main_schema(manager)["columns"]
    )
    # ClickHouse 25.8 permits isNotDistinctFrom only inside JOIN ON. Preserve
    # NULL (and observed NaN) equality in WHERE without substituting amounts.
    def equal_amount(left, right):
        return (f"(({left} IS NULL AND {right} IS NULL) OR ifNull({left} = {right}, 0) "
                f"OR ifNull(isNaN({left}) AND isNaN({right}), 0))")

    summary_sales_equal = equal_amount("t.matching_sales",
        "if(h.summary_variants = 1, h.summary_sales, CAST(NULL, 'Nullable(Float64)'))")
    summary_cost_equal = equal_amount("t.matching_cost",
        "if(h.summary_variants = 1, h.summary_cost, CAST(NULL, 'Nullable(Float64)'))")
    monetary = """(
        (t.matching_sales IS NOT NULL OR t.matching_cost IS NOT NULL)
        AND (t.matching_sales IS NULL OR (isFinite(t.matching_sales)
            AND isFinite(f.revenue) AND abs(t.matching_sales - f.revenue) <= 0.01))
        AND (t.matching_cost IS NULL OR (isFinite(t.matching_cost)
            AND isFinite(f.oper_cost) AND abs(t.matching_cost - f.oper_cost) <= 0.01))
    )"""
    checks = {
        "main_business_preserved_rows": f"""
            SELECT count() AS issue_count FROM (
                SELECT preserved_row, sum(delta) AS imbalance FROM (
                    SELECT tuple({source_fields}) AS preserved_row, toInt64(1) AS delta
                    FROM {db}.{MAIN_TABLE}
                    UNION ALL
                    SELECT tuple({target_fields}) AS preserved_row, toInt64(-1) AS delta
                    FROM {qualified}
                ) GROUP BY preserved_row HAVING imbalance != 0
            )
        """,
        "main_business_proxy_integrity": f"""
            SELECT count() AS issue_count FROM {qualified}
            WHERE is_public_date_pit_eligible != 0
                OR date_match_method NOT IN ('amount_match','report_period_latest','no_valid_report')
                OR source_table != '{MAIN_TABLE},{INCOME_TABLE}'
                OR source_record_hash != lower(hex(MD5(toJSONString(tuple(
                    main_business_source_record_hash, main_business_summary_records,
                    income_source_records, date_match_method)))))
                OR NOT isValidJSON(income_source_records)
                OR NOT isValidJSON(main_business_summary_records)
                OR NOT isValidJSON(date_match_fields)
                OR (date_match_method = 'no_valid_report' AND (
                    ann_date IS NOT NULL OR f_ann_date IS NOT NULL OR available_trade_date IS NOT NULL
                    OR date_candidate_count != 0 OR income_source_records != '[]'
                    OR availability_basis != 'unknown_disclosure_date'))
                OR (date_match_method != 'no_valid_report' AND (
                    ann_date IS NULL OR f_ann_date IS NULL OR available_trade_date IS NULL
                    OR ann_date < end_date OR f_ann_date < end_date
                    OR available_trade_date <= greatest(ann_date, f_ann_date)
                    OR date_candidate_count <= 0 OR income_source_records = '[]'
                    OR availability_basis != 'income_disclosure_proxy'))
                OR (date_match_method = 'amount_match' AND (
                    amount_candidate_count <= 0 OR date_match_fields = '[]'
                    OR main_business_summary_records = '[]'
                    OR (matching_sales IS NULL AND matching_cost IS NULL)
                    OR (matching_sales IS NOT NULL AND (income_revenue IS NULL
                        OR sales_match_error IS NULL OR NOT isFinite(sales_match_error)
                        OR sales_match_error > 0.01 OR sales_match_error != abs(matching_sales-income_revenue)))
                    OR (matching_cost IS NOT NULL AND (income_oper_cost IS NULL
                        OR cost_match_error IS NULL OR NOT isFinite(cost_match_error)
                        OR cost_match_error > 0.01 OR cost_match_error != abs(matching_cost-income_oper_cost)))))
                OR (date_match_method != 'amount_match' AND (
                    amount_candidate_count != 0 OR date_match_fields != '[]'
                    OR sales_match_error IS NOT NULL OR cost_match_error IS NOT NULL))
        """,
        "main_business_selected_income_evidence": f"""
            WITH {candidate_ctes(manager)}
            SELECT count() AS issue_count FROM {qualified} t
            LEFT JOIN income_candidates f ON t.ts_code = f.ts_code AND t.end_date = f.end_date
                AND t.ann_date = f.ann_date AND t.f_ann_date = f.f_ann_date
                AND t.available_trade_date = f.available_trade_date
                AND isNotDistinctFrom(t.income_revenue, f.revenue)
                AND isNotDistinctFrom(t.income_oper_cost, f.oper_cost)
                AND t.income_source_records = f.income_records
            WHERE t.date_match_method != 'no_valid_report' AND f.candidate_exists IS NULL
            SETTINGS join_use_nulls = 1
        """,
        "main_business_summary_evidence": f"""
            WITH {candidate_ctes(manager)}
            SELECT count() AS issue_count FROM {qualified} t
            LEFT JOIN main_summaries h ON t.ts_code = h.ts_code AND t.end_date = h.end_date
                AND t.bz_code = h.bz_code AND t.curr_type = h.curr_type
                AND t.update_flag = h.update_flag AND t.sys_from = h.sys_from
                AND t.source_batch_id = h.source_batch_id
            WHERE NOT {summary_sales_equal} OR NOT {summary_cost_equal}
                OR t.main_business_summary_records != if(h.summary_variants = 1, h.summary_records, '[]')
            SETTINGS join_use_nulls = 1
        """,
        "main_business_latest_eligible_date": f"""
            WITH {candidate_ctes(manager)}
            SELECT count() AS issue_count FROM {qualified} t
            INNER JOIN income_candidates f ON t.ts_code = f.ts_code AND t.end_date = f.end_date
            WHERE t.date_match_method = 'no_valid_report'
                OR (t.date_match_method != 'amount_match' AND ifNull({monetary}, 0))
                OR ((t.date_match_method = 'report_period_latest' OR ifNull({monetary}, 0))
                    AND tuple(f.available_trade_date, greatest(f.ann_date, f.f_ann_date),
                        f.f_ann_date, f.ann_date, f.income_records)
                    > tuple(t.available_trade_date, greatest(t.ann_date, t.f_ann_date),
                        t.f_ann_date, t.ann_date, t.income_source_records))
        """,
    }
    return [ValidationRule(rule_id=name, description=name.replace('_', ' '),
        severity="BLOCKER", issue_count_sql=sql) for name, sql in checks.items()]
