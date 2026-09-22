import unittest

from tushare_integration.dws import (
    DWSManager,
    STOCK_FACTOR_WIDE_V2_BASE_SQL,
    V2_CALCULATED_FACTOR_COLUMNS,
    V2_FINANCIAL_FEATURE_COLUMNS,
)


class StockFactorWideV2Test(unittest.TestCase):
    def setUp(self):
        self.manager = DWSManager()

    def test_v2_catalog_expands_only_existing_families(self):
        columns = {column for _, _, _, column in V2_FINANCIAL_FEATURE_COLUMNS}
        self.assertEqual(len(columns), 1595)
        self.assertEqual(len(V2_CALCULATED_FACTOR_COLUMNS), 28)
        self.assertTrue({f"interestdebt_mrq_{i}" for i in range(9)} <= columns)
        self.assertTrue({f"interestdebt_ttm_{i}" for i in range(9)} <= columns)
        self.assertTrue({f"interestdebt_lyr_{i}" for i in range(5)} <= columns)
        self.assertNotIn("interestdebt_lf", columns)
        self.assertNotIn("non_cur_liab_due_1y_mrq_0", columns)

    def test_v2_schema_keeps_raw_tushare_ttm_fields_and_groups_prefixes(self):
        spec = self.manager.load_spec("dws_stock_factor_wide_v2")
        names = [column["name"] for column in spec["schema"]["columns"]]
        for raw_column in ("pe_ttm", "ps_ttm", "dv_ttm"):
            self.assertIn(raw_column, names)
        self.assertNotIn("ebit_ttm", names)
        self.assertNotIn("working_capital_lf", names)

        expected = (
            [f"interestdebt_mrq_{i}" for i in range(9)]
            + [f"interestdebt_ttm_{i}" for i in range(9)]
            + [f"interestdebt_lyr_{i}" for i in range(5)]
        )
        start = names.index("interestdebt_mrq_0")
        self.assertEqual(names[start : start + len(expected)], expected)

    def test_v2_sql_uses_fixed_slots_and_distinguishes_period_and_field_missingness(self):
        sql = self.manager.render_sync_sql("dws_stock_factor_wide_v2")
        self.assertIn("FROM default.dwd_stock_eod_price", sql)
        self.assertNotIn("FROM default.dws_stock_factor_wide\n", sql)
        self.assertIn("toStartOfQuarter(addDays(available_trade_date, 1))", sql)
        self.assertIn(
            "addDays(addMonths(toStartOfQuarter(addDays(available_trade_date, 1)), "
            "-3 * toInt32(report_offset)), -1)",
            sql,
        )
        self.assertNotIn(
            "addMonths(addDays(toStartOfQuarter(addDays(available_trade_date, 1)), -1)",
            sql,
        )
        self.assertIn("ARRAY JOIN range(12) AS report_offset", sql)
        self.assertIn("countIf(report_offset >= 0 AND report_offset < 4 AND report_exists = 1) = 4", sql)
        self.assertIn("countIf(report_offset >= 0 AND report_offset < 4 AND `revenue` IS NOT NULL)", sql)
        self.assertIn("/ countIf(report_offset >= 0 AND report_offset < 4 AND `revenue` IS NOT NULL) * 4", sql)
        self.assertIn("/ countIf(report_offset >= 0 AND report_offset < 4 AND `total_assets` IS NOT NULL)", sql)

    def test_v1_rendering_remains_on_visible_report_ordering(self):
        sql = self.manager.render_sync_sql("dws_stock_factor_wide")
        self.assertIn("ORDER BY report_period DESC", sql)
        self.assertIn("countIf(report_offset >= 0 AND report_offset < 4 AND `revenue` IS NOT NULL) = 4", sql)
        self.assertNotIn("stock_factor_wide_v2", sql)

    def test_v2_dependencies_are_independent_from_old_wide(self):
        spec = self.manager.load_spec("dws_stock_factor_wide_v2")
        sources = self.manager.get_required_source_tables(spec)
        self.assertNotIn("dws_stock_factor_wide", sources)
        self.assertIn("dwd_stock_eod_price", sources)
        self.assertIn("dwd_stock_balance_sheet", sources)
        self.assertIn("dws_stock_income_quarter", sources)

    def test_v2_base_sql_projects_only_columns_used_downstream(self):
        base_sql = STOCK_FACTOR_WIDE_V2_BASE_SQL.read_text(encoding="utf-8")
        rendered_sql = self.manager.render_sync_sql("dws_stock_factor_wide_v2")
        for sql in (base_sql, rendered_sql):
            self.assertNotIn("SELECT *", sql)
            self.assertNotIn("src.*", sql)
        self.assertIn("src.source_record_hash", base_sql)
        self.assertIn("price.source_batch_id", base_sql)

    def test_v2_uses_daily_sources_for_replaced_quote_metrics(self):
        sql = self.manager.render_sync_sql("dws_stock_factor_wide_v2")

        self.assertIn("daily_basic.volume_ratio AS vol_ratio", sql)
        self.assertIn("daily_basic.turnover_rate AS turn_over", sql)
        self.assertIn("(price.high - price.low) / nullIf(price.pre_close, 0) * 100 AS swing", sql)
        self.assertIn("price.amount * 10 / nullIf(price.vol, 0) AS avg_price", sql)
        self.assertNotIn("quote_metrics.vol_ratio AS vol_ratio", sql)
        self.assertNotIn("quote_metrics.turn_over AS turn_over", sql)
        self.assertNotIn("quote_metrics.swing AS swing", sql)
        self.assertNotIn("quote_metrics.avg_price AS avg_price", sql)

    def test_v2_fills_missing_ocf_to_profit_from_same_report_period(self):
        sql = self.manager.render_sync_sql("dws_stock_factor_wide_v2")

        self.assertIn("src.operate_profit", sql)
        self.assertIn("src.n_cashflow_act", sql)
        self.assertIn("financial_indicator.ocf_to_profit,", sql)
        self.assertIn("financial_indicator.event_date = income.event_date", sql)
        self.assertIn("financial_indicator.event_date = cashflow.event_date", sql)
        self.assertIn(
            "100.0 * cashflow.n_cashflow_act / nullIf(income.operate_profit, 0)",
            sql,
        )

    def test_v2_calculates_only_on_financial_and_calendar_change_dates(self):
        sql = self.manager.render_sync_sql("dws_stock_factor_wide_v2")
        self.assertIn("FROM balance_sheet_quarter_reports\n    UNION DISTINCT", sql)
        self.assertIn("min(p.available_trade_date) AS available_trade_date", sql)
        self.assertIn("FROM default.dwd_stock_eod_price", sql)
        self.assertIn("SETTINGS max_insert_threads = 4", sql)


if __name__ == "__main__":
    unittest.main()
