"""Execute generated ClickHouse SQL against disposable local Memory tables.

No configured database or network is used. Numeric expectations below are
independent examples of the public PIT contract, not a second SQL renderer.
"""

import datetime as dt
import json
import math
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from tushare_integration.dwd import DWDManager
from tushare_integration.dws import DWSManager, STOCK_FACTOR_WIDE_V2_SOURCES
from tushare_integration import v2_scalar_extensions as ext
from tests.fixtures import v2_scalar_extensions_reference as reference
from tushare_integration.quality import DqcManager


def literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    return str(value)


def insert(table, **values):
    return f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join(literal(v) for v in values.values())});"


@unittest.skipUnless(shutil.which("clickhouse-local"), "clickhouse-local is required for SQL numeric tests")
class V2ScalarSQLTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = DWSManager()
        cls.manager.settings.database.db_name = "default"
        dwd = DWDManager()
        cls.ddl = []
        types = {
            "str": "String",
            "int": "Int64",
            "float": "Float64",
            "number": "Float64",
            "date": "Date32",
            "datetime": "DateTime64(3)",
        }
        for table in STOCK_FACTOR_WIDE_V2_SOURCES + ["dws_stock_factor_wide_v2"]:
            manager = dwd if table.startswith("dwd_") else cls.manager
            schema = manager.build_schema(manager.load_spec(table))
            columns = []
            for c in schema["columns"]:
                typ = types[c["data_type"]]
                if c.get("nullable"):
                    typ = f"Nullable({typ})"
                default = " DEFAULT toDateTime64('9999-12-31 00:00:00',3)" if c["name"] == "sys_to" else ""
                columns.append(f"`{c['name']}` {typ}{default}")
            cls.ddl.append(f"CREATE TABLE {table} ({','.join(columns)}) ENGINE=Memory;")

    def execute(self, statements, timeout=120):
        with tempfile.TemporaryDirectory(prefix="v2-scalar-test-") as tmp:
            path = Path(tmp) / "test.sql"
            path.write_text("\n".join(self.ddl + statements))
            result = subprocess.run(
                [
                    "clickhouse-local",
                    "--multiquery",
                    "--max_threads",
                    "2",
                    "--max_query_size",
                    "2097152",
                    "--max_ast_elements",
                    "500000",
                    "--max_expanded_ast_elements",
                    "500000",
                    "--queries-file",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            self.assertEqual(result.returncode, 0, result.stderr[:4000])
            return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]

    def price(self, day, available):
        return insert(
            "dwd_stock_eod_price",
            instrument_id="stock:000001.SZ",
            instrument_type="stock",
            source_code="000001.SZ",
            event_date=day,
            available_trade_date=available,
            source_batch_id="price",
            source_record_hash="price-" + day,
        )

    def extension_query(self, renderer=ext):
        projections = ",".join(f"{expr} AS `{name}`" for name, expr in renderer.supplemental_expressions().items())
        return (
            "WITH price AS (SELECT instrument_id,event_date AS trade_date,available_trade_date,"
            "toNullable(100.) AS total_mv FROM dwd_stock_eod_price),"
            + renderer.render_ctes("default")
            + " SELECT price.trade_date AS trade_date,"
            + projections
            + " FROM price "
            + renderer.render_joins()
            + " ORDER BY price.trade_date FORMAT JSONEachRow;"
        )

    def report(self, table, period, available, **values):
        return insert(
            table,
            instrument_id="stock:000001.SZ",
            event_date=period,
            available_trade_date=available,
            ann_date=available,
            f_ann_date=available,
            report_type="1",
            update_flag="0",
            source_batch_id="report",
            source_record_hash=table + period + available,
            **values,
        )

    def research(self, org, year, np, eps, **changes):
        values = dict(
            instrument_id="stock:000001.SZ",
            report_date="2026-04-01",
            available_trade_date="2026-04-02",
            create_time="2026-04-01 12:00:00",
            forecast_period_end=f"{year}-12-31",
            quarter=f"{year}Q4",
            org_name=org,
            report_title="Forecast",
            report_type="report",
            classify="forecast",
            author_name="author",
            source_batch_id="research",
            source_record_hash=org + str(year),
            np=np,
            eps=eps,
            min_price=10.0,
            max_price=20.0,
        )
        values.update(changes)
        return insert("dwd_stock_research_report", **values)

    def test_acceptance_detects_null_and_value_changes(self):
        renderer = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/validate_v2_scalar_extensions.py"))
        sql = renderer["render"]("default", "old_panel", "dws_stock_factor_wide_v2")
        comparison = sql.split("-- Exact NULL-safe comparison", 1)[1].split("-- Review non-null", 1)[0]
        comparison = comparison[comparison.index("SELECT"):].strip().removesuffix(";")
        comparison = comparison.replace(";", " FORMAT JSONEachRow;")
        statements = ["CREATE TABLE old_panel AS dws_stock_factor_wide_v2 ENGINE=Memory;"]
        for index, (old, new) in enumerate([(None, 0), (1, None), (None, None), (2, 3)]):
            for table, value in [("old_panel", old), ("dws_stock_factor_wide_v2", new)]:
                statements.append(insert(table, instrument_id=f"stock:{index}", trade_date="2026-11-19", close=value))
        rows = self.execute([*statements, comparison + " FORMAT JSONEachRow;"])
        self.assertEqual(rows, [{"column_name": "close", "mismatches": 3}])

    def test_all_missing_is_null_and_full_wide_sql_executes(self):
        rows = self.execute([self.price("2026-05-06", "2026-05-07"), self.extension_query()])
        self.assertEqual(len(rows), 1)
        self.assertTrue(all(value is None for key, value in rows[0].items() if key != "trade_date"))
        rows = self.execute(
            [
                self.price("2026-05-06", "2026-05-07"),
                self.report(
                    "dwd_stock_balance_sheet",
                    "2026-03-31",
                    "2026-04-30",
                    total_share=1000,
                    accounts_pay=123,
                    fix_assets_total=888,
                ),
                self.report("dwd_stock_income", "2025-12-31", "2026-04-20", n_income_attr_p=100),
                insert(
                    "dws_stock_income_quarter",
                    instrument_id="stock:000001.SZ",
                    event_date="2026-03-31",
                    available_trade_date="2026-04-30",
                    rd_exp=4,
                    basic_eps=0.5,
                    revenue=70,
                    source_record_hash="income-quarter",
                ),
                insert(
                    "dws_stock_cashflow_quarter",
                    instrument_id="stock:000001.SZ",
                    event_date="2026-03-31",
                    available_trade_date="2026-04-30",
                    c_fr_sale_sg=37,
                    source_record_hash="cashflow-quarter",
                ),
                self.manager.render_sync_sql("dws_stock_factor_wide_v2") + ";",
                "SELECT count() AS n, any(revenue_mrq_0) AS revenue, any(rd_exp_mrq_0) AS rd, "
                "any(basic_eps_mrq_0) AS eps, any(c_fr_sale_sg_mrq_0) AS cash, "
                "any(accounts_pay_mrq_0) AS pay, any(fix_assets_total_mrq_0) AS fixed_assets, "
                "any(diluted_weighted_share_mrq_0) AS shares, any(analyst_np_consensus_fy0) AS actual_np "
                "FROM dws_stock_factor_wide_v2 FORMAT JSONEachRow;",
            ],
            timeout=300,
        )
        self.assertEqual(
            rows,
            [
                {
                    "n": 1,
                    "revenue": 70,
                    "rd": 4,
                    "eps": 0.5,
                    "cash": 37,
                    "pay": 123,
                    "fixed_assets": 888,
                    "shares": 1000,
                    "actual_np": 100,
                }
            ],
        )

    def test_single_query_matches_original_all_business_fields(self):
        statements = [
            "CREATE TABLE v2_baseline AS dws_stock_factor_wide_v2 ENGINE=Memory;",
            "CREATE TABLE v2_batched AS dws_stock_factor_wide_v2 ENGINE=Memory;",
        ]
        for instrument, value in [("stock:000001.SZ", 10), ("stock:600519.SH", 20)]:
            for day, available in [("2026-05-06", "2026-05-07"), ("2026-05-08", "2026-05-11")]:
                statements.append(insert(
                    "dwd_stock_eod_price", instrument_id=instrument, instrument_type="stock",
                    source_code=instrument.removeprefix("stock:"), event_date=day,
                    available_trade_date=available, close=value,
                    source_batch_id=instrument, source_record_hash=instrument + day,
                ))
            # An older report and a later revision must remain independently visible.
            for available, revenue in [("2026-04-30", value), ("2026-05-08", value + 1)]:
                statements.append(insert(
                    "dws_stock_income_quarter", instrument_id=instrument,
                    event_date="2026-03-31", available_trade_date=available,
                    revenue=revenue, source_batch_id=instrument,
                    source_record_hash=instrument + available,
                ))
            statements.append(insert(
                "dwd_index_weight", instrument_id=instrument, index_code="000906.SH",
                event_date="2026-04-30", available_trade_date="2026-05-06", weight=1,
                source_batch_id="index", source_record_hash=instrument + "index",
            ))
        # A newer complete index snapshot omits both stocks. Filtering index
        # inputs to the stock batch would incorrectly revive older membership.
        statements.append(insert(
            "dwd_index_weight", instrument_id="stock:000002.SZ", index_code="000906.SH",
            event_date="2026-05-07", available_trade_date="2026-05-08", weight=1,
            source_batch_id="index-new", source_record_hash="index-new",
        ))
        with mock.patch("tushare_integration.dws.v2_ext", reference):
            statements.append(self.manager.render_sync_sql("dws_stock_factor_wide_v2", "v2_baseline") + ";")
        statements.append(self.manager.render_sync_sql("dws_stock_factor_wide_v2", "v2_batched") + ";")
        statements.extend([
            "SELECT * FROM v2_baseline ORDER BY instrument_id, trade_date FORMAT JSONEachRow;",
            "SELECT * FROM v2_batched ORDER BY instrument_id, trade_date FORMAT JSONEachRow;",
        ])
        rows = self.execute(statements, timeout=900)
        self.assertEqual(len(rows), 8)
        baseline, batched = rows[:4], rows[4:]
        for row in rows:
            for audit in ("build_time", "source_batch_id", "source_record_hash"):
                row.pop(audit)
        self.assertEqual(baseline, batched)
        self.assertEqual([row["revenue_mrq_0"] for row in batched], [10, 11, 20, 21])
        self.assertEqual([row["csi800_member"] for row in batched], [1, None, 1, None])

    def test_visibility_fixed_holder_slots_and_no_stale_index_membership(self):
        statements = [
            self.price("2026-04-09", "2026-04-10"),
            self.price("2026-04-13", "2026-04-14"),
            self.price("2026-05-06", "2026-05-07"),
        ]
        for period, available, value in [
            ("2025-12-31", "2026-03-02", 120),
            ("2026-03-31", "2026-04-14", 100),
            ("2026-03-31", "2026-04-20", 90),
        ]:
            statements.append(
                insert(
                    "dwd_stock_holder_number",
                    instrument_id="stock:000001.SZ",
                    event_date=period,
                    ann_date=available,
                    available_trade_date=available,
                    holder_num=value,
                )
            )
        statements += [
            insert(
                "dwd_stock_northbound_holding",
                instrument_id="stock:000001.SZ",
                event_date="2026-04-01",
                available_trade_date="2026-04-02",
                vol=1000,
            ),
            insert(
                "dwd_stock_northbound_holding",
                instrument_id="stock:000001.SZ",
                event_date="2026-05-07",
                available_trade_date="2026-05-08",
                vol=9999,
            ),
            insert(
                "dwd_stock_northbound_holding",
                instrument_id="stock:000001.SZ",
                event_date="2026-03-01",
                available_trade_date="2026-05-06",
                vol=7,
            ),
            insert(
                "dwd_stock_top_list",
                instrument_id="stock:000001.SZ",
                event_date="2026-04-09",
                available_trade_date="2026-04-10",
            ),
            insert(
                "dwd_stock_limit",
                instrument_id="stock:000001.SZ",
                event_date="2026-04-09",
                available_trade_date="2026-04-10",
                up_limit=11,
                down_limit=9,
            ),
            insert(
                "dwd_index_eod_price",
                source_code="000985.CSI",
                event_date="2026-04-09",
                available_trade_date="2026-04-10",
                pct_chg=2,
            ),
            insert(
                "dwd_index_weight",
                instrument_id="stock:000001.SZ",
                index_code="000906.SH",
                event_date="2026-04-01",
                available_trade_date="2026-04-02",
                weight=1,
            ),
            insert(
                "dwd_index_weight",
                instrument_id="stock:000002.SZ",
                index_code="000906.SH",
                event_date="2026-05-01",
                available_trade_date="2026-05-06",
                weight=1,
            ),
            insert(
                "dwd_index_weight",
                instrument_id="stock:000001.SZ",
                index_code="000906.SH",
                event_date="2026-04-01",
                available_trade_date="2026-05-07",
                weight=1,
            ),
            insert(
                "dwd_sw_industry_member",
                ts_code="000001.SZ",
                l1_code="old",
                available_date="2020-01-01",
                end_date="2026-04-14",
            ),
            insert(
                "dwd_sw_industry_member",
                ts_code="000001.SZ",
                l1_code="new",
                available_date="2026-04-14",
                end_date="2299-12-31",
            ),
            self.extension_query(),
        ]
        before, after, later = self.execute(statements)
        self.assertIsNone(before["holder_num_mrq_0"])
        self.assertEqual(before["holder_num_mrq_1"], 120)
        self.assertEqual(after["holder_num_mrq_0"], 100)
        self.assertEqual(later["holder_num_mrq_0"], 90)
        self.assertEqual([r["northbound_hold_shares"] for r in (before, after, later)], [1000] * 3)
        self.assertEqual(before["bench_ret"], 0.02)
        self.assertEqual((before["up_limit"], before["down_limit"]), (11, 9))
        self.assertEqual(before["top_list_flag"], 1)
        self.assertIsNone(after["top_list_flag"])
        self.assertEqual([r["sw_l1_code"] for r in (before, after, later)], ["old", "new", "new"])
        self.assertEqual(before["csi800_member"], 1)
        self.assertIsNone(later["csi800_member"])

    def test_research_annual_actual_switch_forecast_windows_and_book_proxy(self):
        statements = [
            self.price("2026-04-09", "2026-04-10"),
            self.price("2026-04-13", "2026-04-14"),
            self.price("2026-05-06", "2026-05-07"),
        ]
        for year in range(2022, 2026):
            statements.append(
                self.report("dwd_stock_income", f"{year}-12-31", f"{year + 1}-04-14", n_income_attr_p=100.0)
            )
        statements += [
            self.report("dwd_stock_income", "2025-09-30", "2025-10-30", n_income_attr_p=70),
            self.report("dwd_stock_income", "2026-03-31", "2026-04-30", n_income_attr_p=20),
            self.report("dwd_stock_balance_sheet", "2025-12-31", "2026-04-14", total_hldr_eqy_exc_min_int=1200),
            self.report("dwd_stock_balance_sheet", "2026-03-31", "2026-04-30", total_hldr_eqy_exc_min_int=1250),
            self.report("dwd_stock_cashflow", "2025-06-30", "2025-08-20", depr_fa_coga_dpba=20),
            self.report("dwd_stock_cashflow", "2025-12-31", "2026-04-14", depr_fa_coga_dpba=55),
        ]
        for i, org in enumerate("ABCDE", 1):
            for year in range(2025, 2030):
                statements.append(self.research(org, year, 10 * i * (year - 2024), i))
        statements.append(self.research("A", 2026, 99999, 999, forecast_period_end="2026-03-31", quarter="2026Q1"))
        statements.append(
            self.research(
                "A",
                2026,
                99999,
                999,
                available_trade_date="2026-05-08",
                create_time="2026-05-07 12:00:00",
                source_record_hash="future-revision",
            )
        )
        for year in range(2023, 2027):
            statements.append(
                insert(
                    "dwd_stock_dividend",
                    instrument_id="stock:000001.SZ",
                    end_date=f"{year - 1}-12-31",
                    ex_date=f"{year}-04-08",
                    imp_ann_date=f"{year}-04-01",
                    available_trade_date=f"{year}-04-02",
                    div_proc="实施",
                    cash_div_tax=0.1,
                    base_share=0.01,
                    source_record_hash=str(year),
                )
            )
        statements.append(self.extension_query())
        before, annual, q1 = self.execute(statements)
        self.assertEqual(before["analyst_np_consensus_fy0"], 300000)
        self.assertEqual(annual["analyst_np_consensus_fy0"], 100)
        self.assertEqual(q1["analyst_np_consensus_fy0"], 600000)
        self.assertEqual(q1["analyst_np_consensus_fy3"], 1500000)
        self.assertEqual(before["analyst_np_mean_active_180d_cny"], 300000)
        self.assertEqual(annual["analyst_np_mean_active_180d_cny"], 600000)
        self.assertEqual(q1["analyst_eps_mean_active_90d"], 3)
        self.assertAlmostEqual(q1["analyst_eps_dispersion_active_90d"], math.sqrt(2.5) / 3)
        self.assertEqual(q1["analyst_org_coverage_90d"], 5)
        self.assertEqual(q1["analyst_org_year_pair_count_90d"], 25)
        self.assertEqual(q1["analyst_target_price_mean_90d"], 15)
        self.assertEqual(before["halfyear_depreciation"], 20)
        self.assertEqual(annual["halfyear_depreciation"], 35)
        self.assertEqual(q1["halfyear_depreciation"], 35)
        self.assertEqual(q1["implemented_cash_dividend_12m_cny"], 10)
        remaining = (dt.date(2027, 1, 1) - dt.date(2026, 4, 1)).days / 365
        self.assertAlmostEqual(q1["analyst_bv_consensus_fy1"], 1250 + 0.9 * (600000 * remaining + 900000))
        weight = (dt.date(2026, 5, 7) - dt.date(2026, 1, 1)).days / 365
        self.assertAlmostEqual(q1["analyst_forward_pe_12m"], 1000000 / ((1 - weight) * 600000 + weight * 900000))

    def test_cumulative_revision_propagates_and_deferred_tax_requires_both_terms(self):
        statements = []
        for period, available, sales, tax_assets, tax_liab in [
            ("2025-03-31", "2025-04-30", 10, 1, 2),
            ("2025-06-30", "2025-08-30", 30, 4, 5),
            ("2025-03-31", "2025-09-10", 12, 2, 3),
            ("2025-09-30", "2025-10-30", 60, None, 8),
        ]:
            statements.append(
                self.report(
                    "dwd_stock_cashflow",
                    period,
                    available,
                    c_fr_sale_sg=sales,
                    decr_def_inc_tax_assets=tax_assets,
                    incr_def_inc_tax_liab=tax_liab,
                )
            )
        statements += [
            self.manager.render_sync_sql("dws_stock_cashflow_quarter") + ";",
            "SELECT event_date,available_trade_date,c_fr_sale_sg,deferred_income_tax FROM dws_stock_cashflow_quarter "
            "ORDER BY available_trade_date,event_date FORMAT JSONEachRow;",
        ]
        rows = self.execute(statements)
        q2 = [r for r in rows if r["event_date"] == "2025-06-30"]
        self.assertEqual(
            [(r["available_trade_date"], r["c_fr_sale_sg"], r["deferred_income_tax"]) for r in q2],
            [("2025-08-30", 20, 6), ("2025-09-10", 18, 4)],
        )
        self.assertIsNone(rows[-1]["deferred_income_tax"])

    def test_cashflow_quarter_dqc_derives_tax_and_detects_incorrect_null(self):
        dqc = DqcManager(settings=self.manager.settings)
        fields = [
            column["name"]
            for column in self.manager.build_schema(self.manager.load_spec("dws_stock_cashflow_quarter"))["columns"]
            if column["data_type"] == "float"
        ]
        with mock.patch.object(dqc, "_query_issue_result", side_effect=lambda sql, *args: sql):
            check_sql = dqc._dws_financial_quarter_value_result(
                "factor", "stock_factor_panel", "dwd_stock_cashflow", "dws_stock_cashflow_quarter", fields
            ) + " FORMAT JSONEachRow;"

        statements = []
        for period, available, sales, tax_assets, tax_liab in [
            ("2025-03-31", "2025-04-30", 10, 1, 2),
            ("2025-06-30", "2025-08-30", 30, 4, 5),
            ("2025-03-31", "2025-09-10", 12, 2, 3),
            ("2025-09-30", "2025-10-30", 60, None, 8),
        ]:
            statements.append(self.report(
                "dwd_stock_cashflow", period, available,
                c_fr_sale_sg=sales,
                decr_def_inc_tax_assets=tax_assets,
                incr_def_inc_tax_liab=tax_liab,
            ))
        statements.extend([
            self.manager.render_sync_sql("dws_stock_cashflow_quarter") + ";",
            check_sql,
            insert(
                "dws_stock_cashflow_quarter",
                instrument_id="stock:000001.SZ",
                event_date="2025-09-30",
                available_trade_date="2025-10-30",
                c_fr_sale_sg=30,
                incr_def_inc_tax_liab=3,
                deferred_income_tax=0,
            ),
            check_sql,
        ])
        correct, incorrect = self.execute(statements)
        self.assertEqual(correct, {"issue_count": 0, "checked_count": 5})
        self.assertEqual(incorrect, {"issue_count": 1, "checked_count": 6})

    def test_fixed_period_ttm_partial_fields_and_long_annual_offset(self):
        from tushare_integration.dws import V2_FINANCIAL_FEATURE_SOURCE_CONFIG

        entries = [
            ("cashflow", "c_fr_sale_sg", "mrq_0", "c_fr_sale_sg_mrq_0"),
            ("cashflow", "c_fr_sale_sg", "ttm_0", "c_fr_sale_sg_ttm_0"),
            ("cashflow", "c_fr_sale_sg", "ttm_12", "c_fr_sale_sg_ttm_12"),
        ]
        statements = [self.price("2026-01-02", "2026-01-05"), self.price("2026-04-01", "2026-04-02")]
        for period, value in [("2025-03-31", 10), ("2025-06-30", 20), ("2025-09-30", None), ("2025-12-31", 40)]:
            statements.append(
                insert(
                    "dws_stock_cashflow_quarter",
                    instrument_id="stock:000001.SZ",
                    event_date=period,
                    available_trade_date="2026-01-05",
                    c_fr_sale_sg=value,
                    source_record_hash=period,
                )
            )
        reports = self.manager._render_financial_report_cte(
            "default", "cashflow", "quarter", ["c_fr_sale_sg"], source_configs=V2_FINANCIAL_FEATURE_SOURCE_CONFIG
        )
        features = self.manager._render_financial_feature_cte_v2("default", "cashflow", "quarter", entries)
        rows = self.execute(
            statements
            + [
                "WITH "
                + reports
                + ","
                + features
                + " SELECT available_trade_date,c_fr_sale_sg_mrq_0,c_fr_sale_sg_ttm_0,c_fr_sale_sg_ttm_12 "
                "FROM cashflow_quarter_features ORDER BY available_trade_date FORMAT JSONEachRow;"
            ]
        )
        self.assertEqual(rows[0]["c_fr_sale_sg_mrq_0"], 40)
        self.assertAlmostEqual(rows[0]["c_fr_sale_sg_ttm_0"], 70 / 3 * 4)
        self.assertIsNone(rows[0]["c_fr_sale_sg_ttm_12"])
        self.assertIsNone(rows[1]["c_fr_sale_sg_mrq_0"])
        self.assertIsNone(rows[1]["c_fr_sale_sg_ttm_0"])
        annual_entries = [("income", "basic_eps", "lyr_10", "basic_eps_lyr_10")]
        reports = self.manager._render_financial_report_cte(
            "default", "income", "annual", ["basic_eps"], source_configs=V2_FINANCIAL_FEATURE_SOURCE_CONFIG
        )
        features = self.manager._render_financial_feature_cte_v2("default", "income", "annual", annual_entries)
        rows = self.execute(
            [
                self.price("2026-01-02", "2026-01-05"),
                self.report("dwd_stock_income", "2015-12-31", "2016-04-20", basic_eps=0.75),
                "WITH " + reports + "," + features + " SELECT basic_eps_lyr_10 FROM income_annual_features "
                "WHERE available_trade_date='2026-01-05' FORMAT JSONEachRow;",
            ]
        )
        self.assertEqual(rows, [{"basic_eps_lyr_10": 0.75}])

    def test_interest_ttm_uses_own_disclosure_dates_and_visible_ytd_revisions(self):
        statements = []
        for year, amounts in [(2024, [10, 30, 60, 100]), (2025, [20, 60, 120, 200])]:
            for quarter, (month_day, amount) in enumerate(zip(
                ["03-31", "06-30", "09-30", "12-31"], amounts, strict=True
            ), 1):
                available = (
                    f"{year}-{[4, 8, 10][quarter - 1]:02d}-30" if quarter < 4 else f"{year + 1}-03-20"
                )
                statements += [
                    self.report("dwd_stock_income", f"{year}-{month_day}", available, fin_exp_int_exp=amount),
                    self.report("dwd_stock_cashflow", f"{year}-{month_day}", available,
                                depr_fa_coga_dpba=amount * 10),
                ]
        statements += [
            self.report("dwd_stock_income", "2026-03-31", "2026-04-21", fin_exp_int_exp=30),
            self.report("dwd_stock_cashflow", "2026-03-31", "2026-04-27", depr_fa_coga_dpba=300),
            # Revising last year's Q1 changes both that quarter and Q2's delta,
            # starting on the income revision's own availability date.
            self.report("dwd_stock_income", "2025-03-31", "2026-05-04", fin_exp_int_exp=25),
            self.report("dwd_stock_income", "2026-03-31", "2026-05-06", fin_exp_int_exp=None, int_exp=999),
            self.report("dwd_stock_income", "2026-03-31", "2026-05-20", fin_exp_int_exp=9999),
            # Native single-quarter reports must not enter the YTD difference path.
            insert("dwd_stock_income", instrument_id="stock:000001.SZ", event_date="2026-03-31",
                   ann_date="2026-04-21", f_ann_date="2026-04-21", available_trade_date="2026-04-21",
                   report_type="2", fin_exp_int_exp=99999, source_record_hash="native-quarter"),
        ]
        for trade, available in [
            ("2026-04-17", "2026-04-20"),
            ("2026-04-20", "2026-04-21"),
            ("2026-04-23", "2026-04-24"),
            ("2026-04-24", "2026-04-27"),
            ("2026-04-30", "2026-05-04"),
            ("2026-05-05", "2026-05-06"),
        ]:
            statements.append(self.price(trade, available))
        statements += [
            self.manager.render_sync_sql("dws_stock_income_quarter") + ";",
            self.manager.render_sync_sql("dws_stock_cashflow_quarter") + ";",
            self.manager.render_sync_sql("dws_stock_factor_wide_v2") + ";",
            "SELECT available_trade_date,fin_exp_int_exp_mrq_0,fin_exp_int_exp_mrq_4,"
            "hf_std_5m,hf_5m_return_count,hf_5m_return_sum,hf_5m_return_sum_sq,"
            "fin_exp_int_exp_ttm_0,fin_exp_int_exp_ttm_4,"
            "depr_fa_coga_dpba_ttm_0,depr_fa_coga_dpba_ttm_4 FROM dws_stock_factor_wide_v2 "
            "ORDER BY available_trade_date FORMAT JSONEachRow;",
        ]
        rows = self.execute(statements, timeout=360)
        self.assertEqual(len(rows), 6)
        expected = [
            (None, 20, None, 110, None, 1100),
            (30, 20, 210, 110, None, 1100),
            (30, 20, 210, 110, None, 1100),
            (30, 20, 210, 110, 2100, 1100),
            (30, 25, 205, 115, 2100, 1100),
            # Preserve v2's existing partial-field rule: all four reports exist,
            # so the three non-null quarters are annualized; no old Q1 or int_exp.
            (None, 25, 175 / 3 * 4, 115, 2100, 1100),
        ]
        columns = ["fin_exp_int_exp_mrq_0", "fin_exp_int_exp_mrq_4",
                   "fin_exp_int_exp_ttm_0", "fin_exp_int_exp_ttm_4",
                   "depr_fa_coga_dpba_ttm_0", "depr_fa_coga_dpba_ttm_4"]
        for row, values in zip(rows, expected, strict=True):
            for field in ("hf_std_5m", "hf_5m_return_count", "hf_5m_return_sum", "hf_5m_return_sum_sq"):
                self.assertIsNone(row[field])
            for column, value in zip(columns, values, strict=True):
                with self.subTest(date=row["available_trade_date"], column=column):
                    if value is None:
                        self.assertIsNone(row[column])
                    else:
                        self.assertAlmostEqual(row[column], value)

    def test_interest_mrq_uses_single_quarter_fixed_slots_and_pit_revisions(self):
        from tushare_integration.dws import V2_FINANCIAL_FEATURE_SOURCE_CONFIG

        entries = [("income", "fin_exp_int_exp", f"mrq_{i}", f"fin_exp_int_exp_mrq_{i}") for i in (0, 4)]
        reports = self.manager._render_financial_report_cte(
            "default", "income", "quarter", ["fin_exp_int_exp"],
            source_configs=V2_FINANCIAL_FEATURE_SOURCE_CONFIG,
        )
        features = self.manager._render_financial_feature_cte_v2("default", "income", "quarter", entries)
        statements = []
        for symbol, current_q1, current_q2, prior_q1, prior_q2 in [
            ("stock:000001.SZ", 30, 110, 20, 60),
            ("stock:000002.SZ", None, 110, 20, 60),
            ("stock:000003.SZ", 30, None, 20, None),
            ("stock:000004.SZ", 100, 90, -20, -25),
        ]:
            statements.append(self.price("2026-08-19", "2026-08-20").replace("stock:000001.SZ", symbol))
            for period, available, value in [
                ("2025-03-31", "2025-04-21", prior_q1),
                ("2025-06-30", "2025-08-01", prior_q2),
                ("2026-03-31", "2026-04-21", current_q1),
                ("2026-06-30", "2026-08-01", current_q2),
            ]:
                if value is not None:
                    statements.append(self.report("dwd_stock_income", period, available,
                                                  fin_exp_int_exp=value).replace("stock:000001.SZ", symbol))
        statements += [
            self.price("2026-08-20", "2026-08-21"),
            self.price("2026-08-21", "2026-08-24"),
            self.report("dwd_stock_income", "2026-03-31", "2026-08-21", fin_exp_int_exp=35),
            self.report("dwd_stock_income", "2026-06-30", "2026-08-24", fin_exp_int_exp=None, int_exp=999),
            self.report("dwd_stock_income", "2026-06-30", "2026-08-30", fin_exp_int_exp=9999),
            insert("dwd_stock_income", instrument_id="stock:000001.SZ", event_date="2026-06-30",
                   ann_date="2026-08-01", f_ann_date="2026-08-01", available_trade_date="2026-08-01",
                   report_type="2", fin_exp_int_exp=99999, source_record_hash="native-quarter"),
            self.manager.render_sync_sql("dws_stock_income_quarter") + ";",
            "WITH " + reports + "," + features
            + " SELECT instrument_id,available_trade_date,fin_exp_int_exp_mrq_0,fin_exp_int_exp_mrq_4 "
            "FROM income_quarter_features WHERE available_trade_date IN ('2026-08-20','2026-08-21','2026-08-24') "
            "ORDER BY instrument_id,available_trade_date FORMAT JSONEachRow;",
        ]
        rows = self.execute(statements)
        self.assertEqual(len(rows), 6)
        self.assertEqual(
            [(r["fin_exp_int_exp_mrq_0"], r["fin_exp_int_exp_mrq_4"]) for r in rows],
            [(80, 40), (75, 40), (None, 40), (None, 40), (None, None), (-10, -5)],
        )

    def test_interest_ttm_missing_period_never_shifts_current_or_prior_year_slots(self):
        from tushare_integration.dws import V2_FINANCIAL_FEATURE_SOURCE_CONFIG

        entries = [("income", "fin_exp_int_exp", f"ttm_{offset}", f"fin_exp_int_exp_ttm_{offset}")
                   for offset in (0, 4)]
        reports = self.manager._render_financial_report_cte(
            "default", "income", "quarter", ["fin_exp_int_exp"],
            source_configs=V2_FINANCIAL_FEATURE_SOURCE_CONFIG,
        )
        features = self.manager._render_financial_feature_cte_v2("default", "income", "quarter", entries)
        statements = []
        for symbol, missing in [("stock:000001.SZ", "2025-06-30"), ("stock:000002.SZ", "2024-06-30")]:
            statements.append(self.price("2026-05-06", "2026-05-07").replace("stock:000001.SZ", symbol))
            for period, value in [
                ("2023-12-31", 1000),
                ("2024-03-31", 10), ("2024-06-30", 30), ("2024-09-30", 60), ("2024-12-31", 100),
                ("2025-03-31", 20), ("2025-06-30", 60), ("2025-09-30", 120), ("2025-12-31", 200),
                ("2026-03-31", 30),
            ]:
                if period != missing:
                    statements.append(self.report("dwd_stock_income", period, "2026-05-07",
                                                  fin_exp_int_exp=value).replace("stock:000001.SZ", symbol))
        rows = self.execute(statements + [
            self.manager.render_sync_sql("dws_stock_income_quarter") + ";",
            "WITH " + reports + "," + features
            + " SELECT instrument_id,fin_exp_int_exp_ttm_0,fin_exp_int_exp_ttm_4 FROM income_quarter_features "
            "WHERE available_trade_date='2026-05-07' ORDER BY instrument_id FORMAT JSONEachRow;",
            "SELECT instrument_id,event_date,fin_exp_int_exp FROM dws_stock_income_quarter "
            "WHERE (instrument_id='stock:000001.SZ' AND event_date='2025-09-30') "
            "OR (instrument_id='stock:000002.SZ' AND event_date='2024-09-30') "
            "ORDER BY instrument_id FORMAT JSONEachRow;",
        ])
        self.assertEqual(rows[:2], [
            {"instrument_id": "stock:000001.SZ", "fin_exp_int_exp_ttm_0": None, "fin_exp_int_exp_ttm_4": 110},
            {"instrument_id": "stock:000002.SZ", "fin_exp_int_exp_ttm_0": 210, "fin_exp_int_exp_ttm_4": None},
        ])
        # Q3 cannot subtract Q1 when the exact preceding Q2 is absent.
        self.assertEqual(len(rows[2:]), 2)
        self.assertTrue(all(row["fin_exp_int_exp"] is None for row in rows[2:]))

    def test_analyst_minimum_orgs_window_boundary_and_null_latest_version(self):
        statements = [
            self.price("2026-05-06", "2026-05-07"),
            self.report("dwd_stock_income", "2025-12-31", "2026-04-14", n_income_attr_p=100),
            self.report("dwd_stock_income", "2026-03-31", "2026-04-30", n_income_attr_p=20),
        ]
        for i, org in enumerate("ABCDE", 1):
            changes = (
                dict(report_date="2026-02-06", available_trade_date="2026-02-09", create_time="2026-02-06 12:00:00")
                if org == "E"
                else {}
            )
            statements.append(self.research(org, 2026, 10 if org in "ABC" else None, i, **changes))
        # A visible correction with an empty NP must not resurrect its old NP.
        statements.append(
            self.research(
                "C",
                2026,
                None,
                3,
                available_trade_date="2026-05-06",
                create_time="2026-05-05 12:00:00",
                source_record_hash="null-revision",
            )
        )
        rows = self.execute(statements + [self.extension_query()])
        r = rows[0]
        self.assertIsNone(r["analyst_np_mean_active_180d_cny"])
        self.assertIsNone(r["analyst_eps_dispersion_active_90d"])
        self.assertAlmostEqual(r["analyst_eps_dispersion_active_91d"], math.sqrt(2.5) / 3)
        self.assertEqual(r["analyst_eps_mean_active_90d"], 2.5)
        self.assertEqual(r["analyst_np_consensus_fy0"], 100000)

    def test_eps_dispersion_threshold_matches_reference(self):
        for eps, expected in [(0.05, 0),(-0.05,0),(0.0499,None)]:
            statements = [self.price("2026-05-06","2026-05-07"),
                self.report("dwd_stock_income","2025-12-31","2026-04-20",n_income_attr_p=100),
                self.report("dwd_stock_income","2026-03-31","2026-04-30",n_income_attr_p=20)]
            statements += [self.research(org,2026,10,eps) for org in "ABCDE"]
            old,new = self.execute(statements+[self.extension_query(reference),self.extension_query()])
            with self.subTest(eps=eps):
                old_value = old["analyst_eps_dispersion_active_90d"]
                new_value = new["analyst_eps_dispersion_active_90d"]
                if expected is None:
                    self.assertIsNone(old_value)
                    self.assertIsNone(new_value)
                else:
                    # stddevSamp can leave tiny roundoff for identical inputs.
                    self.assertIsNotNone(old_value)
                    self.assertIsNotNone(new_value)
                    self.assertAlmostEqual(old_value, expected, delta=1e-7)
                    self.assertAlmostEqual(new_value, expected, delta=1e-7)
                    self.assertAlmostEqual(old_value, new_value, delta=1e-7)

    def test_target_lineage_and_zero_weight_book_dependency(self):
        statements = [self.price("2026-05-06","2026-05-07")]
        for year in range(2023,2026):
            statements.append(self.report("dwd_stock_income",f"{year}-12-31",f"{year+1}-04-20",n_income_attr_p=100))
            statements.append(insert("dwd_stock_dividend",instrument_id="stock:000001.SZ",
                end_date=f"{year-1}-12-31",ex_date=f"{year}-05-01",imp_ann_date=f"{year}-04-20",
                available_trade_date=f"{year}-04-21",div_proc="实施",cash_div_tax=0.1,base_share=0.01,
                source_record_hash=f"div{year}"))
        statements += [
            self.report("dwd_stock_balance_sheet","2025-12-31","2026-04-20",total_hldr_eqy_exc_min_int=1200),
            self.research("A",2025,100,1,source_batch_id="zero_weight_year",source_record_hash="zero"),
            self.research("A",2026,200,2,source_batch_id="positive_weight_year",source_record_hash="positive"),
        ]
        sql = "WITH "+ext.render_ctes("default")+" SELECT source_batch_id,analyst_bv_consensus_fy1 FROM v2_book_forecast FORMAT JSONEachRow;"
        sql2 = "WITH "+ext.render_ctes("default")+" SELECT source_batch_id,source_record_hash FROM v2_target_prices FORMAT JSONEachRow;"
        book,target = self.execute(statements+[sql,sql2])
        self.assertEqual(book["source_batch_id"],"positive_weight_year")
        self.assertEqual(book["analyst_bv_consensus_fy1"],1801200)
        self.assertTrue(target["source_batch_id"])
        self.assertNotEqual(target["source_record_hash"],"")

    def test_early_filters_match_reference_at_business_boundaries(self):
        statements = []
        for day in ("2025-12-30", "2025-12-31", "2026-01-02", "2026-03-31", "2026-04-30", "2026-05-07", "2026-07-01"):
            statements.append(self.price(day, day))
        for year in range(2022, 2026):
            statements.append(self.report("dwd_stock_income", f"{year}-12-31", f"{year+1}-04-20", n_income_attr_p=100))
        statements += [
            self.report("dwd_stock_income", "2025-09-30", "2025-10-30", n_income_attr_p=70),
            self.report("dwd_stock_income", "2026-03-31", "2026-04-30", n_income_attr_p=20),
            self.report("dwd_stock_income", "2024-12-31", "2026-05-06", n_income_attr_p=None),
            self.report("dwd_stock_balance_sheet", "2025-12-31", "2026-04-20", total_hldr_eqy_exc_min_int=1200),
            self.report("dwd_stock_balance_sheet", "2026-03-31", "2026-04-30", total_hldr_eqy_exc_min_int=1250),
            self.report("dwd_stock_balance_sheet", "2024-12-31", "2026-05-06", total_hldr_eqy_exc_min_int=9999),
            self.report("dwd_stock_cashflow", "2025-12-31", "2026-04-20", depr_fa_coga_dpba=55),
            self.report("dwd_stock_cashflow", "2026-03-31", "2026-04-30", depr_fa_coga_dpba=999),
            self.report("dwd_stock_cashflow", "2025-06-30", "2026-05-06", depr_fa_coga_dpba=20),
        ]
        for org in "ABCDE":
            for year in range(2024, 2031):
                statements.append(self.research(org, year, 10*(year-2023), 2,
                    report_date="2021-12-31", available_trade_date="2022-01-04",
                    create_time="2021-12-31 12:00:00", report_title="Old still needed"))
            for day in ("2025-12-01", "2026-02-06", "2026-02-07", "2026-04-01"):
                statements.append(self.research(org, 2026, 30, 3, report_date=day,
                    available_trade_date=day, create_time=day+" 12:00:00", report_title=day,
                    source_record_hash=org+day))
        # A late correction of an old report cannot replace a newer report for the org/year.
        statements += [self.research("A", 2026, 999, 999, report_date="2021-12-31",
                        available_trade_date="2026-05-06", create_time="2026-05-05 12:00:00",
                        report_title="Old still needed", source_record_hash="late-old"),
                       self.research("B", 2026, None, None, report_date="2026-04-01",
                        available_trade_date="2026-05-06", create_time="2026-05-05 12:00:00",
                        report_title="2026-04-01", source_record_hash="latest-null")]
        for ex in ("2023-05-07", "2024-05-07", "2025-05-07", "2025-12-31", "2026-01-01"):
            statements.append(insert("dwd_stock_dividend", instrument_id="stock:000001.SZ",
                end_date=ex[:4]+"-12-31", ex_date=ex, imp_ann_date=ex,
                available_trade_date=ex, div_proc="实施", cash_div_tax=0.1, base_share=0.01,
                source_record_hash=ex))
        rows = self.execute(statements+[self.extension_query(reference), self.extension_query()], timeout=300)
        self.assertEqual(len(rows),14)
        for old, new in zip(rows[:7], rows[7:]):
            self.assertEqual(old.keys(), new.keys())
            for field in old:
                with self.subTest(date=old["trade_date"], field=field):
                    if isinstance(old[field], float):
                        self.assertAlmostEqual(old[field], new[field], places=8)
                    else:
                        self.assertEqual(old[field], new[field])
        self.assertIsNone(rows[11]["halfyear_depreciation"])
        self.assertEqual(rows[12]["halfyear_depreciation"],35)
        self.assertEqual(rows[9]["analyst_np_consensus_fy3"],500000)


class V2ManifestTest(unittest.TestCase):
    def test_manifest_schema_and_upstream_contract(self):
        manager = DWSManager()
        schema = manager.load_spec("dws_stock_factor_wide_v2")["schema"]["columns"]
        names = [c["name"] for c in schema]
        self.assertEqual(len(ext.MANIFEST), 238)
        self.assertEqual(len(ext.SCALAR_SPECS), 233)
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue({i["name"] for i in ext.SCALAR_SPECS} <= set(names))
        self.assertFalse({i["name"] for i in ext.MANIFEST if i["status"] == "excluded"} & set(names))
        self.assertEqual(sum(i["status"] == "placeholder" for i in ext.MANIFEST), 17)
        for table in ["dwd_stock_holder_number", "dwd_stock_top_list"]:
            dwd = DWDManager()
            sql = dwd.render_sync_sql(table)
            self.assertIn("Missing SSE next trading day", sql)
            self.assertIn("ROWS BETWEEN 1 FOLLOWING", sql)
        self.assertNotIn("ricequant", ",".join(STOCK_FACTOR_WIDE_V2_SOURCES))


if __name__ == "__main__":
    unittest.main()
