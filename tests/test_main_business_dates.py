"""Execute disclosure proxy and suspension histories in disposable ClickHouse tables."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from tests.test_v2_array_dwd import ddl, insert
from tushare_integration.dwd import DWDManager
from tushare_integration.dws import DWSManager
from tushare_integration.quality import QualityManager


class MainBusinessPublicationTest(unittest.TestCase):
    def test_failed_validation_does_not_publish(self):
        manager = DWSManager()
        manager.db_engine = mock.Mock()
        with (
            mock.patch.object(manager, "ensure_source_tables"),
            mock.patch.object(manager, "_replace_clickhouse_table_from_tmp") as publish,
            mock.patch("tushare_integration.dws.QualityManager.validate_publish",
                       side_effect=RuntimeError("bad disclosure proxy")),
        ):
            with self.assertRaisesRegex(RuntimeError, "bad disclosure proxy"):
                manager.sync_table("dws_stock_main_business", validation_mode="strict")
        publish.assert_not_called()
        self.assertEqual(manager.get_required_source_tables(manager.load_spec("dws_stock_main_business")),
                         ["dwd_stock_main_business", "dwd_stock_income", "trade_cal"])


@unittest.skipUnless(shutil.which("clickhouse-local"), "clickhouse-local is required")
class MainBusinessDatesTest(unittest.TestCase):
    def setUp(self):
        self.dwd = DWDManager()
        self.dws = DWSManager()
        self.dwd.settings.database.db_name = self.dws.settings.database.db_name = "default"

    def execute(self, statements):
        sql = ["CREATE TABLE trade_cal (exchange String, cal_date Date32, is_open Int64) ENGINE=Memory;",
               "INSERT INTO trade_cal VALUES ('SSE','2026-11-20',1),('SSE','2026-11-20',1),"
               "('SSE','2026-11-21',0),('SSE','2026-11-22',0),('SSE','2026-11-23',1),"
               "('SSE','2026-11-24',1),('SSE','2026-11-25',1);"]
        for table in ["dwd_stock_main_business", "dwd_stock_income"]:
            sql.append(ddl(table, self.dwd.build_schema(self.dwd.load_spec(table))))
        sql.append(ddl("dws_stock_main_business", self.dws.build_schema(
            self.dws.load_spec("dws_stock_main_business"))))
        sql.extend(statements)
        with tempfile.TemporaryDirectory(prefix="main-business-dates-") as tmp:
            path = Path(tmp) / "test.sql"
            path.write_text("\n".join(sql))
            result = subprocess.run(["clickhouse-local", "--multiquery", "--max_threads", "2",
                                     "--queries-file", str(path)], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[:5000])
        return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]

    def main(self, code, sales, cost, item="产品", **changes):
        values = dict(ts_code=code, end_date="2026-06-30", bz_code="P", bz_item=item,
                      curr_type="CNY", update_flag="0", bz_sales=sales, bz_cost=cost,
                      instrument_id="stock:" + code, event_date="2026-06-30",
                      sys_from="2026-11-20 18:00:00", sys_to="2299-12-31 00:00:00",
                      source="tushare", source_table="fina_mainbz_raw", source_batch_id="main",
                      source_record_hash=code + ":" + item, availability_basis="unknown_disclosure_date")
        values.update(changes)
        return insert("dwd_stock_main_business", **values)

    def income(self, code, sales, cost, day=20, **changes):
        values = dict(ts_code=code, end_date="2026-06-30", report_type="1", update_flag=0,
                      ann_date=f"2026-11-{day}", f_ann_date=f"2026-11-{day}",
                      available_trade_date=f"2026-11-{23 if day <= 22 else day + 1}",
                      revenue=sales, oper_cost=cost, sys_from="2026-11-20 18:00:00",
                      sys_to="2299-12-31 00:00:00", source="tushare", source_table="income_raw",
                      source_batch_id="income", source_record_hash=f"{code}:{day}:{sales}:{cost}")
        values.update(changes)
        return insert("dwd_stock_income", **values)

    def test_amount_priority_latest_matches_period_fallback_and_nulls(self):
        statements = []
        for code, sales, cost in [("000001.SZ", 100, 60), ("000002.SZ", 100, 60),
                                 ("000003.SZ", 999, 600), ("000005.SZ", 100, 60),
                                 ("000006.SZ", None, 60), ("000007.SZ", 100, 60),
                                 ("000011.SZ", 100, None), ("000012.SZ", 100, 60)]:
            statements.append(self.main(code, sales, cost))
        statements.extend([
            self.main("000001.SZ", 30, 18, "Widget"),
            self.main("000004.SZ", 30, 18, "Widget"),
            self.main("000008.SZ", 100, 60),
            self.main("000008.SZ", 30, 18, "Widget", source_batch_id="different"),
            self.main("000009.SZ", 100, 60, curr_type="USD"),
        ])
        for code in ["000001.SZ", "000003.SZ", "000004.SZ", "000008.SZ", "000009.SZ"]:
            statements.extend([self.income(code, 100, 60), self.income(code, 120, 80, 23)])
        statements.extend([
            self.income("000002.SZ", 100, 60), self.income("000002.SZ", 100, 60, 23),
            self.income("000002.SZ", 100, 60, source_record_hash="observed-again"),
            self.income("000006.SZ", 100, 60), self.income("000006.SZ", 120, 80, 23),
            self.income("000007.SZ", 100, None), self.income("000007.SZ", 100, 60, 23),
            self.income("000011.SZ", 100, 60), self.income("000011.SZ", 100, 80, 23),
            self.income("000012.SZ", 100, 60, available_trade_date="2026-11-20"),
            self.income("000012.SZ", 100, 60, ann_date="1970-01-01"),
            self.income("000012.SZ", 100, 60, report_type="6"),
            self.dws.render_sync_sql("dws_stock_main_business") + ";",
            "SELECT ts_code,bz_item,date_match_method,available_trade_date,date_match_fields,"
            "date_candidate_count,amount_candidate_count,income_source_records "
            "FROM dws_stock_main_business ORDER BY ts_code,bz_item FORMAT JSONEachRow;",
        ])
        rules = QualityManager(settings=self.dws.settings).build_rules(
            "dws", "dws_stock_main_business", "dws_stock_main_business")
        statements.extend(r.issue_count_sql + " FORMAT JSONEachRow;" for r in rules)
        rows = self.execute(statements)
        records = {(r["ts_code"], r["bz_item"]): r for r in rows if "ts_code" in r}
        self.assertEqual(len(records), 13)
        expected = {
            "000001.SZ": ("amount_match", "2026-11-23"),
            "000002.SZ": ("amount_match", "2026-11-24"),
            "000003.SZ": ("report_period_latest", "2026-11-24"),
            "000005.SZ": ("no_valid_report", None),
            "000006.SZ": ("amount_match", "2026-11-23"),
            "000007.SZ": ("amount_match", "2026-11-24"),
            "000008.SZ": ("amount_match", "2026-11-23"),
            "000009.SZ": ("report_period_latest", "2026-11-24"),
            "000011.SZ": ("amount_match", "2026-11-24"),
            "000012.SZ": ("no_valid_report", None),
        }
        for code, (method, date) in expected.items():
            row = records[(code, "产品")]
            self.assertEqual((row["date_match_method"], row["available_trade_date"]), (method, date), code)
        self.assertEqual(records[("000001.SZ", "Widget")]["date_match_method"], "amount_match")
        for code in ["000004.SZ", "000008.SZ"]:
            self.assertEqual(records[(code, "Widget")]["date_match_method"], "report_period_latest")
        self.assertEqual(records[("000002.SZ", "产品")]["date_candidate_count"], 2)
        self.assertEqual(records[("000002.SZ", "产品")]["amount_candidate_count"], 2)
        self.assertEqual(json.loads(records[("000006.SZ", "产品")]["date_match_fields"]),
                         ["bz_cost:oper_cost"])
        self.assertTrue(all(r["issue_count"] == 0 for r in rows if "issue_count" in r), rows)

    def test_same_trade_day_later_disclosure_and_whole_date_tuple(self):
        rows = self.execute([
            self.main("000001.SZ", 100, 60),
            self.income("000001.SZ", 100, 60, 21),
            self.income("000001.SZ", 100, 60, 22, ann_date="2026-11-20"),
            self.dws.render_sync_sql("dws_stock_main_business") + ";",
            "SELECT ann_date,f_ann_date,available_trade_date FROM dws_stock_main_business FORMAT JSONEachRow;",
        ])
        self.assertEqual(rows, [{"ann_date": "2026-11-20", "f_ann_date": "2026-11-22",
                                 "available_trade_date": "2026-11-23"}])

    def test_null_currency_flag_and_source_categories_are_preserved(self):
        rows = self.execute([
            self.main("000001.SZ", None, None, "Item", curr_type=None, update_flag=None,
                      bz_code="455006000"),
            self.income("000001.SZ", 100, 60), self.income("000001.SZ", 120, 80, 23),
            self.dws.render_sync_sql("dws_stock_main_business") + ";",
            "SELECT curr_type,update_flag,bz_code,bz_sales,bz_cost,date_match_method,"
            "available_trade_date FROM dws_stock_main_business FORMAT JSONEachRow;",
        ])
        self.assertEqual(rows, [{"curr_type": None, "update_flag": None, "bz_code": "455006000",
                                 "bz_sales": None, "bz_cost": None,
                                 "date_match_method": "report_period_latest",
                                 "available_trade_date": "2026-11-24"}])

    def test_observed_main_versions_are_preserved(self):
        rows = self.execute([
            self.main("000001.SZ", 100, 60, sys_to="2026-11-21 18:00:00"),
            self.main("000001.SZ", 120, 80, sys_from="2026-11-21 18:00:00",
                      source_record_hash="revised-main"),
            self.income("000001.SZ", 100, 60), self.income("000001.SZ", 120, 80, 23),
            self.dws.render_sync_sql("dws_stock_main_business") + ";",
            "SELECT bz_sales,available_trade_date FROM dws_stock_main_business ORDER BY sys_from FORMAT JSONEachRow;",
        ])
        self.assertEqual(rows, [{"bz_sales": 100, "available_trade_date": "2026-11-23"},
                                {"bz_sales": 120, "available_trade_date": "2026-11-24"}])

    def test_quality_rejects_fabricated_amount_proof_and_wrong_latest_date(self):
        rules = QualityManager(settings=self.dws.settings).build_rules(
            "dws", "dws_stock_main_business", "dws_stock_main_business")
        integrity = next(r.issue_count_sql for r in rules if r.rule_id == "main_business_proxy_integrity")
        latest = next(r.issue_count_sql for r in rules if r.rule_id == "main_business_latest_eligible_date")
        rows = self.execute([
            self.main("000001.SZ", 100, 60), self.income("000001.SZ", 100, 60),
            self.dws.render_sync_sql("dws_stock_main_business") + ";",
            # Adding a later matching disclosure makes the previously selected date stale.
            self.income("000001.SZ", 100, 60, 23), latest + " FORMAT JSONEachRow;",
            "INSERT INTO dws_stock_main_business SELECT * REPLACE(1 AS sales_match_error) "
            "FROM dws_stock_main_business;",
            integrity + " FORMAT JSONEachRow;",
        ])
        self.assertEqual(rows, [{"issue_count": 1}, {"issue_count": 1}])
