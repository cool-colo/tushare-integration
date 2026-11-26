"""Execute the array-source DWD transforms against controlled disclosure histories."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from tushare_integration.dwd import DWDManager
from tushare_integration.quality import QualityManager
from tushare_integration.storage import build_raw_schema


class ArrayDWDSyncTest(unittest.TestCase):
    def test_validation_failure_retains_staged_evidence_and_does_not_publish(self):
        manager = DWDManager()
        manager.settings.database.db_name = "default"
        manager.db_engine = mock.Mock()
        with (
            mock.patch.object(manager, "ensure_source_tables"),
            mock.patch.object(manager, "_replace_clickhouse_table_from_tmp") as publish,
            mock.patch(
                "tushare_integration.dwd.QualityManager.validate_publish", side_effect=RuntimeError("invalid candidate")
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid candidate"):
                manager.sync_table("dwd_fund_portfolio")
        publish.assert_not_called()
        queries = [c.args[0] for c in manager.db_engine.query.call_args_list]
        stage = "default.dwd_fund_portfolio_source_tmp"
        self.assertEqual(sum(sql.startswith(f"INSERT INTO {stage} ") for sql in queries), 1)
        # Only the initial reset is allowed; failed validation must preserve the
        # staged snapshot and both candidates for diagnosis.
        self.assertEqual(queries.count(f"DROP TABLE IF EXISTS {stage}"), 1)
        builds = [sql for sql in queries if sql.startswith("\nINSERT INTO default.dwd_fund_portfolio_")]
        self.assertTrue(builds)
        self.assertTrue(all(f"FROM {stage} src" in sql for sql in builds))
        self.assertTrue(any("quarantine_tmp" in sql for sql in builds))
        self.assertTrue(all("'fund_portfolio_raw' AS `source_table`" in sql for sql in builds))


def ddl(name, schema):
    types = {
        "str": "String",
        "json": "String",
        "int": "Int64",
        "float": "Float64",
        "date": "Date32",
        "datetime": "DateTime64(3)",
    }
    columns = []
    for column in schema["columns"]:
        typ = types[column["data_type"]]
        if column.get("nullable"):
            typ = f"Nullable({typ})"
        columns.append(f"`{column['name']}` {typ}")
    return f"CREATE TABLE {name} ({','.join(columns)}) ENGINE=Memory;"


def insert(name, **values):
    def literal(value):
        if value is None:
            return "NULL"
        if isinstance(value, str):
            return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
        return str(value)

    return f"INSERT INTO {name} ({','.join(values)}) VALUES ({','.join(map(literal, values.values()))});"


@unittest.skipUnless(shutil.which("clickhouse-local"), "clickhouse-local is required")
class ArrayDWDTest(unittest.TestCase):
    def setUp(self):
        self.manager = DWDManager()
        self.manager.settings.database.db_name = "default"

    def execute(self, tables, statements, *, calendar=True, fails=False):
        sql = ["CREATE TABLE trade_cal (exchange String,cal_date Date32,is_open Int64) ENGINE=Memory;"]
        if calendar:
            sql.append(
                "INSERT INTO trade_cal VALUES ('SSE','2026-11-20',1),('SSE','2026-11-20',1),"
                "('SSE','2026-11-21',0),('SSE','2026-11-22',0),('SSE','2026-11-23',1),"
                "('SSE','2026-11-24',1),('SSE','2026-11-25',1);"
            )
        for table in tables:
            spec = self.manager.load_spec(table)
            sql.extend(
                [
                    ddl(
                        spec["source"]["table_name"],
                        build_raw_schema(self.manager.load_source_schema(spec["source"]["schema_name"])),
                    ),
                    ddl(table, self.manager.build_schema(spec)),
                ]
            )
            if spec.get("quarantine_same_time_conflicts"):
                sql.append(
                    ddl(
                        table + "_quarantine",
                        self.manager.build_quarantine_schema(spec),
                    )
                )
        sql.extend(statements)
        with tempfile.TemporaryDirectory(prefix="array-dwd-") as tmp:
            path = Path(tmp) / "test.sql"
            path.write_text("\n".join(sql))
            result = subprocess.run(
                [
                    "clickhouse-local",
                    "--multiquery",
                    "--max_threads",
                    "2",
                    "--queries-file",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        if fails:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Missing SSE next trading day", result.stderr)
            return []
        self.assertEqual(result.returncode, 0, result.stderr[:4000])
        return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]

    @staticmethod
    def holder(raw="top10_holders_raw", **changes):
        values = dict(
            ts_code="000001.SZ",
            end_date="2026-09-30",
            ann_date="2026-11-20",
            holder_name="A",
            hold_amount=100,
            hold_ratio=1.2,
            hold_float_ratio=None,
            _source="tushare",
            _batch_id="a",
            _record_hash="first",
            _ingest_time="2026-11-20 18:00:00",
        )
        values.update(changes)
        return insert(raw, **values)

    def test_holders_preserve_entities_revisions_nulls_and_weekend_visibility(self):
        table = "dwd_stock_top10_holders"
        rows = self.execute(
            [table],
            [
                self.holder(),
                self.holder(holder_name="B", hold_amount=200, _record_hash="holder-b"),
                self.holder(_batch_id="repeat", _ingest_time="2026-11-21 18:00:00"),
                self.holder(
                    hold_amount=150,
                    _record_hash="revision",
                    _batch_id="revision",
                    _ingest_time="2026-11-23 18:00:00",
                ),
                self.holder(holder_name="Weekend", ann_date="2026-11-21", _record_hash="weekend"),
                self.holder(holder_name="Invalid", ann_date="2026-09-01", _record_hash="invalid"),
                self.manager.render_sync_sql(table) + ";",
                f"SELECT holder_name,hold_amount,hold_ratio,hold_float_ratio,available_trade_date,sys_from,sys_to "
                f"FROM {table} ORDER BY holder_name,sys_from FORMAT JSONEachRow;",
                # A system-time as-of must retain the old payload, not the subsequently observed correction.
                f"SELECT hold_amount AS historical_amount FROM {table} WHERE holder_name='A' "
                "AND available_trade_date<=toDate32('2026-11-23') "
                "AND sys_from<=toDateTime64('2026-11-23 09:00:00',3) "
                "AND sys_to>toDateTime64('2026-11-23 09:00:00',3) FORMAT JSONEachRow;",
            ],
        )
        self.assertEqual(
            [(r["holder_name"], r["hold_amount"]) for r in rows[:-1]],
            [("A", 100), ("A", 150), ("B", 200), ("Weekend", 100)],
        )
        self.assertTrue(all(r["available_trade_date"] == "2026-11-23" for r in rows[:-1]))
        self.assertTrue(all(r["hold_ratio"] == 1.2 and r["hold_float_ratio"] is None for r in rows[:-1]))
        self.assertEqual(rows[0]["sys_to"], rows[1]["sys_from"])
        self.assertEqual(rows[-1]["historical_amount"], 100)

    def test_holder_source_kinds_are_not_merged(self):
        tables = ["dwd_stock_top10_holders", "dwd_stock_top10_floatholders"]
        statements = [
            self.holder(),
            self.holder("top10_floatholders_raw", hold_amount=80),
        ]
        for table in tables:
            statements.extend(
                [
                    self.manager.render_sync_sql(table) + ";",
                    f"SELECT source_kind,hold_amount FROM {table} FORMAT JSONEachRow;",
                ]
            )
        rows = self.execute(tables, statements)
        self.assertEqual(
            rows,
            [
                {"source_kind": "top10_holders", "hold_amount": 100},
                {"source_kind": "top10_floatholders", "hold_amount": 80},
            ],
        )

    def test_same_time_conflicts_quarantine_whole_identity_without_selecting_a_value(
        self,
    ):
        table = "dwd_stock_top10_holders"
        rows = self.execute(
            [table],
            [
                self.holder(),
                self.holder(hold_amount=150, _record_hash="conflict"),
                self.holder(
                    hold_amount=160,
                    _record_hash="later",
                    _ingest_time="2026-11-21 18:00:00",
                ),
                self.holder(holder_name="B", hold_amount=200, _record_hash="unambiguous"),
                self.manager.render_sync_sql(table) + ";",
                self.manager.render_quarantine_sql(table) + ";",
                f"SELECT holder_name,hold_amount FROM {table} FORMAT JSONEachRow;",
                f"SELECT holder_name,hold_amount,available_trade_date,sys_to,quarantine_reason "
                f"FROM {table}_quarantine ORDER BY hold_amount FORMAT JSONEachRow;",
            ],
        )
        self.assertEqual(rows[0], {"holder_name": "B", "hold_amount": 200})
        self.assertEqual([r["hold_amount"] for r in rows[1:]], [100, 150, 160])
        self.assertTrue(
            all(
                r["holder_name"] == "A"
                and r["available_trade_date"] is None
                and r["sys_to"] is None
                and r["quarantine_reason"] == "ambiguous_same_time_versions"
                for r in rows[1:]
            )
        )

    def test_missing_calendar_never_backdates_visibility(self):
        table = "dwd_stock_top10_holders"
        self.execute(
            [table],
            [self.holder(), self.manager.render_sync_sql(table) + ";"],
            calendar=False,
            fails=True,
        )

    def test_research_waits_for_source_update_and_fails_without_calendar(self):
        table = "dwd_stock_research_report"
        record = insert(
            "report_rc_raw",
            ts_code="000001.SZ",
            report_date="2026-11-20",
            org_name="Org",
            classify="forecast",
            create_time="2026-11-23 14:00:00",
            quarter="2027Q4",
            np=123.5,
            _source="tushare",
            _batch_id="a",
            _record_hash="r",
            _ingest_time="2026-11-23 18:00:00",
        )
        rows = self.execute(
            [table],
            [
                record,
                self.manager.render_sync_sql(table) + ";",
                f"SELECT available_trade_date,forecast_period_end,np,author_name FROM {table} FORMAT JSONEachRow;",
            ],
        )
        self.assertEqual(
            rows,
            [
                {
                    "available_trade_date": "2026-11-24",
                    "forecast_period_end": "2027-12-31",
                    "np": 123.5,
                    "author_name": None,
                }
            ],
        )
        self.execute(
            [table],
            [record, self.manager.render_sync_sql(table) + ";"],
            calendar=False,
            fails=True,
        )

    def test_fund_complete_holdings_is_unknown_and_values_preserve_source_units(self):
        table = "dwd_fund_portfolio"
        rows = self.execute(
            [table],
            [
                insert(
                    "fund_portfolio_raw",
                    ts_code="000001.OF",
                    symbol="000001.SZ",
                    end_date="2026-09-30",
                    ann_date="2026-11-21",
                    amount=12.5,
                    mkv=None,
                    stk_mkv_ratio=1.23,
                    _source="tushare",
                    _batch_id="a",
                    _record_hash="fund",
                    _ingest_time="2026-11-23 12:00:00",
                ),
                self.manager.render_sync_sql(table) + ";",
                f"SELECT instrument_id,fund_id,available_trade_date,amount,mkv,stk_mkv_ratio,is_complete_holdings "
                f"FROM {table} FORMAT JSONEachRow;",
            ],
        )
        self.assertEqual(
            rows,
            [
                {
                    "instrument_id": "stock:000001.SZ",
                    "fund_id": "fund:000001.OF",
                    "available_trade_date": "2026-11-23",
                    "amount": 12.5,
                    "mkv": None,
                    "stk_mkv_ratio": 1.23,
                    "is_complete_holdings": None,
                }
            ],
        )

    def test_ccass_preserves_participants_and_never_fabricates_disclosure_date(self):
        table = "dwd_stock_ccass_holding_detail"
        records = []
        for participant, amount, percent in [
            ("P1", "1,234,567.5", "12.5%"),
            ("P2", "--", "0.01"),
            ("P3", "1,2", None),
        ]:
            records.append(
                insert(
                    "ccass_hold_detail_raw",
                    ts_code="00001.HK",
                    trade_date="2020-01-02",
                    col_participant_id=participant,
                    col_shareholding=amount,
                    col_shareholding_percent=percent,
                    _source="tushare",
                    _batch_id="a",
                    _record_hash=participant,
                    _ingest_time="2026-11-20 18:00:00",
                )
            )
        rows = self.execute(
            [table],
            records
            + [
                self.manager.render_sync_sql(table) + ";",
                f"SELECT col_participant_id,col_shareholding,shareholding,shareholding_percent,"
                f"available_trade_date,availability_basis FROM {table} ORDER BY col_participant_id "
                "FORMAT JSONEachRow;",
                f"SELECT count() AS eligible FROM {table} WHERE available_trade_date<='2026-11-23' FORMAT JSONEachRow;",
            ],
            calendar=False,
        )
        self.assertEqual([r["shareholding"] for r in rows[:-1]], [1234567.5, None, None])
        self.assertEqual([r["shareholding_percent"] for r in rows[:-1]], [0.125, 0.0001, None])
        self.assertEqual(rows[2]["col_shareholding"], "1,2")
        self.assertTrue(
            all(
                r["available_trade_date"] is None and r["availability_basis"] == "unknown_disclosure_date"
                for r in rows[:-1]
            )
        )
        self.assertEqual(rows[-1]["eligible"], 0)

    def test_suspend_keeps_same_day_stop_resume_revisions_and_unknown_availability(self):
        table = "dwd_stock_suspend"
        records = []
        for kind, timing, observed, hash_ in [
            ("S", None, "2026-11-20", "stop"),
            ("S", None, "2026-11-21", "stop"),
            ("S", "10:00-10:30", "2026-11-22", "stop-revised"),
            ("R", None, "2026-11-20", "resume"),
        ]:
            records.append(insert("suspend_d_raw", ts_code="000001.SZ", trade_date="2026-11-20",
                suspend_type=kind, suspend_timing=timing, _source="tushare", _batch_id="a",
                _record_hash=hash_, _ingest_time=observed + " 18:00:00"))
        records.append(insert("suspend_d_raw", ts_code="000001.SZ", trade_date="2009-12-31",
            suspend_type="S", _source="tushare", _batch_id="a", _record_hash="old",
            _ingest_time="2026-11-20 18:00:00"))
        rows = self.execute([table], records + [self.manager.render_sync_sql(table) + ";",
            f"SELECT suspend_type,suspend_timing,available_trade_date FROM {table} "
            "ORDER BY suspend_type,sys_from FORMAT JSONEachRow;"], calendar=False)
        self.assertEqual(rows, [
            {"suspend_type": "R", "suspend_timing": None, "available_trade_date": None},
            {"suspend_type": "S", "suspend_timing": None, "available_trade_date": None},
            {"suspend_type": "S", "suspend_timing": "10:00-10:30", "available_trade_date": None},
        ])

    def test_suspend_same_observation_conflict_does_not_hide_resume(self):
        table = "dwd_stock_suspend"
        records = [insert("suspend_d_raw", ts_code="000001.SZ", trade_date="2026-11-20",
            suspend_type=kind, suspend_timing=timing, _source="tushare", _batch_id="a",
            _record_hash=hash_, _ingest_time="2026-11-20 18:00:00")
            for kind, timing, hash_ in [("S", None, "stop"), ("S", "10:00-10:30", "conflict"),
                                      ("R", None, "resume")]]
        rows = self.execute([table], records + [self.manager.render_sync_sql(table) + ";",
            self.manager.render_quarantine_sql(table) + ";",
            f"SELECT suspend_type,count() AS rows FROM {table} GROUP BY suspend_type FORMAT JSONEachRow;",
            f"SELECT count() AS quarantined,countIf(available_trade_date IS NOT NULL) AS visible "
            f"FROM {table}_quarantine FORMAT JSONEachRow;"], calendar=False)
        self.assertEqual(rows, [{"suspend_type": "R", "rows": 1}, {"quarantined": 2, "visible": 0}])

    def test_main_business_preserves_class_currency_and_observed_revisions(self):
        table = "dwd_stock_main_business"
        records = []
        for code, currency, flag, sales, observed, hash_ in [
            ("P", "CNY", "0", 100, "2026-11-20", "p-cny"),
            ("P", "CNY", "1", 110, "2026-11-21", "p-cny-revised"),
            ("P", "USD", "0", 20, "2026-11-20", "p-usd"),
            ("D", None, "0", None, "2026-11-20", "d-unknown"),
        ]:
            records.append(
                insert(
                    "fina_mainbz_raw",
                    ts_code="000001.SZ",
                    end_date="2026-09-30",
                    bz_code=code,
                    bz_item="Item",
                    curr_type=currency,
                    update_flag=flag,
                    bz_sales=sales,
                    _source="tushare",
                    _batch_id="a",
                    _record_hash=hash_,
                    _ingest_time=observed + " 18:00:00",
                )
            )
        rows = self.execute(
            [table],
            records
            + [
                self.manager.render_sync_sql(table) + ";",
                f"SELECT bz_code,curr_type,bz_sales,sys_from,sys_to,available_trade_date "
                f"FROM {table} ORDER BY bz_code,curr_type,sys_from FORMAT JSONEachRow;",
            ],
        )
        self.assertEqual(len(rows), 4)
        self.assertEqual(
            [(r["bz_code"], r["curr_type"], r["bz_sales"]) for r in rows],
            [("D", None, None), ("P", "CNY", 100), ("P", "CNY", 110), ("P", "USD", 20)],
        )
        self.assertEqual(rows[1]["sys_to"], rows[2]["sys_from"])
        self.assertTrue(all(r["available_trade_date"] is None for r in rows))

    def test_unknown_disclosure_quality_rejects_guessed_dates_without_relaxing_other_tables(
        self,
    ):
        table = "dwd_stock_main_business"
        rules = QualityManager(settings=self.manager.settings).build_rules("dwd", table, table)
        check = next(r.issue_count_sql for r in rules if r.rule_id == "dwd_unknown_disclosure_excluded_from_pit")
        rows = self.execute(
            [table],
            [
                insert(table, availability_basis="unknown_disclosure_date"),
                insert(
                    table,
                    availability_basis="unknown_disclosure_date",
                    available_trade_date="2026-09-30",
                ),
                check + " FORMAT JSONEachRow;",
            ],
        )
        self.assertEqual(rows, [{"issue_count": 1}])
        known = self.manager.build_schema(self.manager.load_spec("dwd_stock_top10_holders"))
        available = next(c for c in known["columns"] if c["name"] == "available_trade_date")
        self.assertFalse(available.get("nullable", False))

    def test_fund_shards_preserve_whole_revision_history_and_original_lineage(self):
        table = "dwd_fund_portfolio"
        spec = self.manager.load_spec(table)
        spec["sync_shards"] = 2
        statements = []
        for fund, amount, observed, hash_ in [
            ("000001.OF", 10, "2026-11-20", "first"),
            ("000001.OF", 10, "2026-11-21", "first"),
            ("000001.OF", 11, "2026-11-23", "correction"),
            ("000002.OF", 20, "2026-11-20", "other-fund"),
        ]:
            statements.append(
                insert(
                    "fund_portfolio_raw",
                    ts_code=fund,
                    symbol="000001.SZ",
                    end_date="2026-09-30",
                    ann_date="2026-11-20",
                    amount=amount,
                    _source="tushare",
                    _batch_id="a",
                    _record_hash=hash_,
                    _ingest_time=observed + " 18:00:00",
                )
            )
        statements.extend(
            [
                ddl("fund_source_stage", self.manager.build_sharded_source_schema(spec)),
                self.manager.render_sharded_source_sql(spec, "fund_source_stage") + ";",
            ]
        )
        for shard in range(2):
            part = self.manager.sharded_source_spec(spec, "fund_source_stage", shard)
            statements.append(self.manager._render_generic_sync_sql(part, table) + ";")
        statements.append(
            f"SELECT ts_code,amount,sys_from,sys_to,source_table FROM {table} "
            "ORDER BY ts_code,sys_from FORMAT JSONEachRow;"
        )
        rows = self.execute([table], statements)
        self.assertEqual(
            [(r["ts_code"], r["amount"]) for r in rows],
            [("000001.OF", 10), ("000001.OF", 11), ("000002.OF", 20)],
        )
        self.assertEqual(rows[0]["sys_to"], rows[1]["sys_from"])
        self.assertTrue(all(r["source_table"] == "fund_portfolio_raw" for r in rows))
