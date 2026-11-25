"""Single-query V2 candidates. Construction and failure never remove tables."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

from urllib3.util import Timeout

from tushare_integration.db_engine import ClickhouseEngine
from tushare_integration.quality import QualityManager, QualityValidationError

V2_TABLE = "dws_stock_factor_wide_v2"
READ_SETTINGS = " SETTINGS max_local_read_bandwidth=104857600"


def save_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _records(engine, sql: str) -> list[dict]:
    return engine.query_df(sql + READ_SETTINGS).to_dict("records")


def source_inventory(engine, database: str, source_tables: list[str]) -> dict:
    names = ",".join(ClickhouseEngine.quote_string(n) for n in sorted(set(source_tables)))
    db = ClickhouseEngine.quote_string(database)
    # Record physical parts for diagnostics, including background merges.
    return {
        "tables": _records(engine, f"SELECT name,uuid,engine FROM system.tables WHERE database={db} AND name IN ({names}) ORDER BY name"),
        "columns": _records(engine, f"SELECT table,name,type,default_kind,default_expression FROM system.columns WHERE database={db} AND table IN ({names}) ORDER BY table,position"),
        "parts": _records(engine, f"SELECT table,name,rows,bytes_on_disk,data_version FROM system.parts WHERE active AND database={db} AND table IN ({names}) ORDER BY table,name"),
    }


def collect_query_metrics(engine, run_id: str) -> list[dict]:
    comment = ClickhouseEngine.quote_string(f"v2_single:{run_id}")
    return _records(engine, f"""SELECT query_id,type,query_duration_ms,memory_usage,
        read_rows,read_bytes,written_rows,written_bytes,ProfileEvents,exception_code,exception
        FROM system.query_log WHERE log_comment={comment}
        AND type IN ('QueryFinish','ExceptionBeforeStart','ExceptionWhileProcessing')
        ORDER BY event_time_microseconds,query_id""")


@contextmanager
def _build_timeout(engine):
    """Allow long V2 requests without changing other queries or server limits."""
    if not isinstance(engine, ClickhouseEngine):
        yield
        return
    original = engine.client.timeout
    engine.client.timeout = Timeout(connect=original.connect_timeout, read=12 * 3600)
    try:
        yield
    finally:
        engine.client.timeout = original


def execute_build(manager, target_table: str | None = None, *, instrument_ids: list[str] | None = None,
                  report_path: Path | None = None, validation_mode: str = "warn_only") -> dict:
    if manager.settings.database.db_type != "clickhouse":
        raise ValueError("Single-query V2 candidates require ClickHouse")
    if validation_mode not in {"strict", "warn_only"}:
        raise ValueError("V2 build requires validation in strict or warn_only mode")
    run_id = uuid.uuid4().hex
    target = target_table or f"{V2_TABLE}_tmp_{run_id}"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", target) or target in {V2_TABLE, f"{V2_TABLE}_tmp"} or target.startswith("v2_stage_"):
        raise ValueError("Expected a new isolated candidate table")
    engine = manager.get_db_engine()
    if manager._clickhouse_table_exists(target):
        raise ValueError(f"Candidate already exists; retained unchanged: {target}")
    spec = manager.load_spec(V2_TABLE)
    manager.ensure_source_tables(spec)
    db = manager.settings.database.db_name
    path = Path(report_path) if report_path else Path("logs") / f"v2-single-{run_id}.json"
    report = {"run_id": run_id, "database": db, "target": target, "instrument_ids": instrument_ids,
              "execution": "single_insert_select", "status": "preparing", "report_path": str(path),
              "validation_mode": validation_mode, "publication": None}
    started = time.monotonic()
    q = ClickhouseEngine.quote_identifier
    try:
        report["disks_before"] = _records(engine, "SELECT name,free_space,unreserved_space FROM system.disks")
        report["sources_before"] = source_inventory(engine, db, manager.get_required_source_tables(spec))
        schema = manager.build_schema(spec)
        sql = manager.render_sync_sql(V2_TABLE, target_table_name=target, instrument_ids=instrument_ids)
        report["sql_sha256"] = hashlib.sha256(sql.encode()).hexdigest()
        save_report(path, report)
        path.with_suffix(".sql").write_text(sql + ";\n", encoding="utf-8")
        create = engine.templates["create"].render(db_name=db, table_name=target, **schema,
                                                   template_params=manager.settings.database.template_params)
        # Fail atomically on an existing name, even if created after the check above.
        engine.query(create.replace("CREATE TABLE IF NOT EXISTS", "CREATE TABLE", 1))
        report["status"] = "building"
        save_report(path, report)
        print(f"V2 single {run_id}: INSERT started; candidate={target}", flush=True)
        build_started = time.monotonic()
        with _build_timeout(engine):
            result = engine.query(sql, settings={"log_comment": f"v2_single:{run_id}"})
        report["build_seconds"] = time.monotonic() - build_started
        report["query_id"] = getattr(result, "query_id", None)
        report["status"] = "validating"
        save_report(path, report)
        validation_started = time.monotonic()
        try:
            validation = QualityManager(settings=manager.settings, db_engine=engine).validate_publish(
                layer="dws", table_name=V2_TABLE, target_table_name=target,
                stage="pre_dws_publish", mode=validation_mode, skip_validation=False,
            )
        except QualityValidationError as exc:
            report["validation"] = asdict(exc.run)
            raise
        finally:
            report["validation_seconds"] = time.monotonic() - validation_started
        report["validation"] = asdict(validation)
        report["panel"] = _records(engine, f"SELECT count() AS rows,uniqExact(instrument_id,trade_date) AS keys,min(trade_date) AS min_date,max(trade_date) AS max_date FROM {q(db)}.{q(target)}")[0]
        scope = ""
        if instrument_ids is not None:
            scope = " AND instrument_id IN (" + ",".join(ClickhouseEngine.quote_string(i) for i in sorted(set(instrument_ids))) + ")"
        price_where = "sys_to=toDateTime64('9999-12-31 00:00:00',3) AND event_date>=toDate32('2010-01-01')" + scope
        report["expected_panel"] = _records(engine, f"SELECT count() AS rows,uniqExact(instrument_id,event_date) AS keys,min(event_date) AS min_date,max(event_date) AS max_date FROM {q(db)}.dwd_stock_eod_price WHERE {price_where}")[0]
        if report["panel"] != report["expected_panel"] or report["panel"]["rows"] != report["panel"]["keys"]:
            raise RuntimeError("Candidate row count, uniqueness or date bounds differ from the price panel")
        report["key_difference"] = _records(engine, f"""SELECT countIf(p.has_price=0) AS only_candidate,
            countIf(c.has_candidate=0) AS only_price
            FROM (SELECT instrument_id,event_date AS trade_date,toUInt8(1) AS has_price
                  FROM {q(db)}.dwd_stock_eod_price WHERE {price_where}) p
            FULL OUTER JOIN (SELECT instrument_id,trade_date,toUInt8(1) AS has_candidate FROM {q(db)}.{q(target)}) c
              ON p.instrument_id=c.instrument_id AND p.trade_date=c.trade_date""")[0]
        if any(report["key_difference"].values()):
            raise RuntimeError("Candidate keys differ from the price panel")
        report["parts"] = _records(engine, f"SELECT sum(rows) AS rows,sum(bytes_on_disk) AS bytes_on_disk,count() AS parts FROM system.parts WHERE active AND database={ClickhouseEngine.quote_string(db)} AND table={ClickhouseEngine.quote_string(target)}")[0]
        report["sources_after"] = source_inventory(engine, db, manager.get_required_source_tables(spec))
        report["sources_unchanged"] = report["sources_before"] == report["sources_after"]
        report["status"] = "validated"
        return report
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = repr(exc)
        raise
    finally:
        report["wall_seconds"] = time.monotonic() - started
        try:
            report["query_metrics"] = collect_query_metrics(engine, run_id)
        except Exception as exc:
            report["query_metrics_error"] = repr(exc)
        save_report(path, report)
        print(f"V2 single report: {path}; status={report['status']}; candidate retained", flush=True)
