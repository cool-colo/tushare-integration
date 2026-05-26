from __future__ import annotations

import datetime
import csv
import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yaml

from tushare_integration.db_engine import DatabaseEngineFactory, DBEngine
from tushare_integration.settings import TushareIntegrationSettings


ValidationMode = Literal["strict", "warn_only", "skip"]
ValidationSeverity = Literal["BLOCKER", "WARN", "MONITOR"]

FAR_FUTURE_TS = "toDateTime64('9999-12-31 00:00:00', 3)"
VALIDATION_SYSTEM_ERROR = "VALIDATION_SYSTEM_ERROR"
TRADE_VALIDATION_MIN_DATE_SQL = "toDate32('2010-01-01')"
ROOT_DIR = Path(__file__).resolve().parent.parent
DWD_SCHEMA_DIR = ROOT_DIR / "tushare_integration" / "schema" / "dwd"
DWS_SCHEMA_DIR = ROOT_DIR / "tushare_integration" / "schema" / "dws"
ODS_SCHEMA_DIR = ROOT_DIR / "tushare_integration" / "schema"
FACTOR_MAPPING_CSV = ROOT_DIR / "docs" / "prd" / "factor_mapping_readable.csv"

DWD_TRADE_RELEVANT_TABLES = {
    "dwd_trade_calendar",
    "dwd_stock_eod_price",
    "dwd_index_eod_price",
    "dwd_future_eod_price",
    "dwd_stock_daily_basic",
    "dwd_stock_eod_quote_metrics",
    "dwd_stock_adj_factor",
    "dwd_stock_margin_trading",
    "dwd_stock_northbound_holding",
    "dwd_stock_chip_distribution",
    "dwd_index_weight",
    "dwd_dc_index",
    "dwd_dc_member",
    "dwd_dc_concept",
    "dwd_dc_concept_cons",
}

DWS_TRADE_DATE_COLUMNS = {
    "dws_stock_factor_wide": "trade_date",
    "dws_stock_factor_wide_matrix": "trade_date",
}

DQC_DEFAULT_SUITE_BY_LAYER = {
    "dws": "stock_factor_panel",
}

DQC_SUITE_TABLES = {
    ("dws", "stock_factor_panel"): ["dws_stock_factor_wide", "dws_stock_factor_wide_matrix"],
}

DQC_SUITE_DOMAIN = {
    ("dws", "stock_factor_panel"): "factor",
}

DQC_FLOAT_TYPES = {"float", "number", "int"}


@dataclass(frozen=True)
class ValidationRule:
    rule_id: str
    description: str
    severity: ValidationSeverity
    issue_count_sql: str
    sample_sql: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    rule_id: str
    severity: ValidationSeverity
    status: str
    issue_count: int
    description: str
    message: str = ""


@dataclass(frozen=True)
class ValidationRun:
    run_id: str
    layer: str
    stage: str
    table_name: str
    target_table_name: str
    mode: ValidationMode
    status: str
    started_at: datetime.datetime
    finished_at: datetime.datetime
    results: list[ValidationResult]

    @property
    def should_block(self) -> bool:
        return self.mode == "strict" and any(
            result.severity == "BLOCKER" and result.status == "FAIL" for result in self.results
        )


@dataclass(frozen=True)
class DqcResult:
    rule_id: str
    layer: str
    domain: str
    suite_name: str
    table_name: str
    check_layer: str
    check_type: str
    severity: ValidationSeverity
    status: str
    checked_count: int = 0
    issue_count: int = 0
    issue_rate: float | None = None
    observed_value: float | None = None
    expected_min: float | None = None
    expected_max: float | None = None
    baseline_mean: float | None = None
    baseline_std: float | None = None
    z_score: float | None = None
    message: str = ""


@dataclass(frozen=True)
class DqcMetric:
    layer: str
    domain: str
    suite_name: str
    table_name: str
    as_of_date: datetime.date
    trade_date: datetime.date | str
    metric_scope: str
    entity_name: str
    metric_name: str
    metric_value: float


@dataclass(frozen=True)
class DqcConsistency:
    layer: str
    domain: str
    suite_name: str
    left_table: str
    right_table: str
    as_of_date: datetime.date
    trade_date: datetime.date | str
    check_name: str
    left_value: float
    right_value: float
    ratio: float | None
    status: str


@dataclass(frozen=True)
class DqcSample:
    layer: str
    domain: str
    suite_name: str
    table_name: str
    rule_id: str
    as_of_date: datetime.date
    trade_date: datetime.date | str
    instrument_id: str
    entity_name: str
    sample_type: str
    sample_json: str


@dataclass(frozen=True)
class DqcRun:
    run_id: str
    layer: str
    domain: str
    suite_name: str
    table_name: str
    as_of_date: datetime.date
    mode: ValidationMode
    status: str
    started_at: datetime.datetime
    finished_at: datetime.datetime
    baseline_window_days: int
    results: list[DqcResult]
    metrics: list[DqcMetric]
    consistencies: list[DqcConsistency]
    samples: list[DqcSample]

    @property
    def should_block(self) -> bool:
        return self.mode == "strict" and any(
            result.severity == "BLOCKER" and result.status == "FAIL" for result in self.results
        )


class QualityValidationError(RuntimeError):
    def __init__(self, run: ValidationRun):
        failed_rules = [
            f"{result.rule_id}({result.issue_count})"
            for result in run.results
            if result.severity == "BLOCKER" and result.status == "FAIL"
        ]
        super().__init__(
            f"Validation failed for {run.layer}.{run.table_name} in strict mode: {', '.join(failed_rules)}"
        )
        self.run = run


class DqcValidationError(RuntimeError):
    def __init__(self, run: DqcRun):
        failed_rules = [
            f"{result.rule_id}({result.issue_count})"
            for result in run.results
            if result.severity == "BLOCKER" and result.status == "FAIL"
        ]
        super().__init__(
            f"DQC failed for {run.layer}.{run.suite_name} table={run.table_name} in strict mode: "
            f"{', '.join(failed_rules)}"
        )
        self.run = run


class QualityManager:
    def __init__(self, settings: TushareIntegrationSettings | None = None, db_engine: DBEngine | None = None):
        self.settings = settings or TushareIntegrationSettings.model_validate(
            yaml.safe_load(open("config.yaml", "r", encoding="utf-8").read())
        )
        self.db_engine = db_engine

    def get_db_engine(self) -> DBEngine:
        if self.db_engine is None:
            self.db_engine = DatabaseEngineFactory.create(self.settings)
        return self.db_engine

    @staticmethod
    def _quote_table(db_name: str, table_name: str) -> str:
        return f"{db_name}.{table_name}"

    @staticmethod
    def _first_int(data: pd.DataFrame, default: int = 0) -> int:
        if data.empty:
            return default
        value = data.iloc[0, 0]
        if pd.isna(value):
            return default
        return int(value)

    def resolve_mode(
        self,
        layer: str,
        table_name: str,
        override_mode: ValidationMode | None = None,
        skip_validation: bool = False,
    ) -> ValidationMode:
        if skip_validation:
            return "skip"
        if override_mode is not None:
            return override_mode

        quality = self.settings.quality
        table_mode = quality.table_modes.get(table_name)
        stage_mode = getattr(quality, f"{layer}_mode", None)
        mode: ValidationMode = table_mode or stage_mode or quality.mode

        if mode == "skip" and quality.skip_until:
            try:
                skip_until = datetime.datetime.fromisoformat(quality.skip_until)
            except ValueError:
                logging.warning("Invalid quality.skip_until value %s; using skip mode", quality.skip_until)
                return mode
            if datetime.datetime.now(skip_until.tzinfo) > skip_until:
                fallback_mode = stage_mode or quality.mode
                return fallback_mode if fallback_mode != "skip" else "warn_only"
        return mode

    def validate_publish(
        self,
        layer: str,
        table_name: str,
        target_table_name: str,
        stage: str,
        mode: ValidationMode | None = None,
        skip_validation: bool = False,
    ) -> ValidationRun:
        resolved_mode = self.resolve_mode(
            layer=layer,
            table_name=table_name,
            override_mode=mode,
            skip_validation=skip_validation,
        )
        started_at = datetime.datetime.now()
        run_id = uuid.uuid4().hex

        if resolved_mode == "skip":
            run = ValidationRun(
                run_id=run_id,
                layer=layer,
                stage=stage,
                table_name=table_name,
                target_table_name=target_table_name,
                mode=resolved_mode,
                status="SKIPPED",
                started_at=started_at,
                finished_at=datetime.datetime.now(),
                results=[],
            )
            self._record_run(run)
            logging.warning("Validation skipped for %s.%s target=%s", layer, table_name, target_table_name)
            return run

        try:
            results = self.run_rules(layer=layer, table_name=table_name, target_table_name=target_table_name)
        except Exception as exc:
            logging.exception("Validation system error for %s.%s target=%s", layer, table_name, target_table_name)
            results = [
                ValidationResult(
                    rule_id=VALIDATION_SYSTEM_ERROR,
                    severity="BLOCKER",
                    status="FAIL",
                    issue_count=1,
                    description="Validation engine raised an internal error",
                    message=repr(exc),
                )
            ]
            if resolved_mode == "warn_only":
                logging.warning("Continuing because validation mode is warn_only")

        status = "PASS"
        if any(result.status == "FAIL" for result in results):
            status = "FAIL"
        run = ValidationRun(
            run_id=run_id,
            layer=layer,
            stage=stage,
            table_name=table_name,
            target_table_name=target_table_name,
            mode=resolved_mode,
            status=status,
            started_at=started_at,
            finished_at=datetime.datetime.now(),
            results=results,
        )
        self._record_run(run)
        if run.should_block:
            raise QualityValidationError(run)
        return run

    def run_rules(self, layer: str, table_name: str, target_table_name: str | None = None) -> list[ValidationResult]:
        target_table_name = target_table_name or table_name
        rules = self.build_rules(layer=layer, table_name=table_name, target_table_name=target_table_name)
        results = []
        db_engine = self.get_db_engine()
        for rule in rules:
            issue_count = self._first_int(db_engine.query_df(rule.issue_count_sql))
            results.append(
                ValidationResult(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    status="FAIL" if issue_count > 0 else "PASS",
                    issue_count=issue_count,
                    description=rule.description,
                )
            )
        return results

    def list_rules(self, layer: str, table_name: str, target_table_name: str | None = None) -> list[ValidationRule]:
        return self.build_rules(layer=layer, table_name=table_name, target_table_name=target_table_name or table_name)

    def checked_count_sql(self, layer: str, table_name: str, target_table_name: str | None = None) -> str:
        target_table_name = target_table_name or table_name
        db_name = self.settings.database.db_name
        qualified = self._quote_table(db_name, target_table_name)
        validation_filter = None
        if layer == "dwd":
            validation_filter = self._dwd_validation_filter(table_name)
        elif layer == "dws":
            validation_filter = self._dws_validation_filter(table_name)
        elif layer != "ods":
            raise ValueError(f"Unsupported validation layer: {layer}")
        return f"""
            SELECT count() AS checked_count
            FROM {qualified}
            {self._where_sql(validation_filter=validation_filter)}
        """

    def checked_count(self, layer: str, table_name: str, target_table_name: str | None = None) -> int:
        return self._first_int(
            self.get_db_engine().query_df(
                self.checked_count_sql(layer=layer, table_name=table_name, target_table_name=target_table_name)
            )
        )

    def build_rules(self, layer: str, table_name: str, target_table_name: str) -> list[ValidationRule]:
        if self.settings.database.db_type != "clickhouse":
            raise NotImplementedError("Quality validation currently supports ClickHouse SQL only")
        if layer == "dwd":
            return self._build_dwd_rules(table_name, target_table_name)
        if layer == "dws":
            return self._build_dws_rules(table_name, target_table_name)
        if layer == "ods":
            return self._build_ods_rules(table_name, target_table_name)
        raise ValueError(f"Unsupported validation layer: {layer}")

    def _build_ods_rules(self, table_name: str, target_table_name: str) -> list[ValidationRule]:
        db_name = self.settings.database.db_name
        qualified = self._quote_table(db_name, target_table_name)
        metadata_columns = ["_source", "_api_name", "_batch_id", "_ingest_time", "_record_hash"]
        if target_table_name.endswith("_raw"):
            metadata_columns.append("_raw_json")
        return [
            self._row_count_rule(qualified),
            self._required_columns_rule(db_name, target_table_name, metadata_columns),
            ValidationRule(
                rule_id="ods_metadata_not_empty",
                description="ODS metadata fields must be populated",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    WHERE _source = '' OR _api_name = '' OR _batch_id = '' OR _record_hash = ''
                """,
            ),
        ]

    def _build_dwd_rules(self, table_name: str, target_table_name: str) -> list[ValidationRule]:
        db_name = self.settings.database.db_name
        qualified = self._quote_table(db_name, target_table_name)
        validation_filter = self._dwd_validation_filter(table_name)
        rules = [
            self._row_count_rule(qualified, validation_filter),
            self._required_columns_rule(
                db_name,
                target_table_name,
                [
                    "event_date",
                    "available_trade_date",
                    "sys_from",
                    "sys_to",
                    "source",
                    "source_table",
                    "source_batch_id",
                    "source_record_hash",
                ],
            ),
            ValidationRule(
                rule_id="dwd_pit_dates_not_null",
                description="DWD PIT dates must be populated",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("event_date IS NULL OR available_trade_date IS NULL OR sys_from IS NULL OR sys_to IS NULL", validation_filter)}
                """,
            ),
            ValidationRule(
                rule_id="dwd_sys_window_order",
                description="DWD version windows must satisfy sys_from < sys_to",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("sys_from >= sys_to", validation_filter)}
                """,
            ),
            ValidationRule(
                rule_id="dwd_lineage_not_empty",
                description="DWD rows must keep source lineage",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("source = '' OR source_table = '' OR source_batch_id = '' OR source_record_hash = ''", validation_filter)}
                """,
            ),
        ]
        rules.extend(self._dwd_open_version_rules(table_name, qualified, validation_filter))
        rules.extend(self._dwd_business_rules(table_name, qualified, validation_filter))
        return rules

    def _build_dws_rules(self, table_name: str, target_table_name: str) -> list[ValidationRule]:
        db_name = self.settings.database.db_name
        qualified = self._quote_table(db_name, target_table_name)
        validation_filter = self._dws_validation_filter(table_name)
        rules = [self._row_count_rule(qualified, validation_filter)]
        if table_name == "dws_stock_factor_wide":
            rules.extend(
                [
                    ValidationRule(
                        rule_id="dws_factor_wide_unique_key",
                        description="DWS factor wide must have one row per instrument and trade date",
                        severity="BLOCKER",
                        issue_count_sql=f"""
                            SELECT count() AS issue_count
                            FROM (
                                SELECT instrument_id, trade_date
                                FROM {qualified}
                                {self._where_sql(validation_filter=validation_filter)}
                                GROUP BY instrument_id, trade_date
                                HAVING count() > 1
                            )
                        """,
                    ),
                    ValidationRule(
                        rule_id="dws_factor_wide_required_prices",
                        description="DWS factor wide must keep required OHLCV fields",
                        severity="BLOCKER",
                        issue_count_sql=f"""
                            SELECT count() AS issue_count
                            FROM {qualified}
                            {self._where_sql("open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL OR vol IS NULL", validation_filter)}
                        """,
                    ),
                    ValidationRule(
                        rule_id="dws_factor_wide_ohlc",
                        description="DWS factor wide OHLC fields must be internally consistent",
                        severity="BLOCKER",
                        issue_count_sql=self._ohlc_issue_sql(
                            qualified,
                            validation_filter,
                            "vol > 0 OR open > 0 OR high > 0 OR low > 0",
                        ),
                    ),
                    ValidationRule(
                        rule_id="dws_factor_wide_no_future_trade_visibility",
                        description="DWS factor rows must not be available before their trade date",
                        severity="BLOCKER",
                        issue_count_sql=f"""
                            SELECT count() AS issue_count
                            FROM {qualified}
                            {self._where_sql("available_trade_date < trade_date", validation_filter)}
                        """,
                    ),
                ]
            )
        if table_name == "dws_stock_factor_wide_matrix":
            rules.extend(
                [
                    self._required_columns_rule(
                        db_name,
                        target_table_name,
                        [
                            "instrument_id",
                            "trade_date",
                            "available_trade_date",
                            "factor_count",
                            "source_record_hash",
                        ],
                    ),
                    ValidationRule(
                        rule_id="dws_factor_wide_matrix_unique_key",
                        description="DWS factor matrix must have one row per instrument and trade date",
                        severity="BLOCKER",
                        issue_count_sql=f"""
                            SELECT count() AS issue_count
                            FROM (
                                SELECT instrument_id, trade_date
                                FROM {qualified}
                                {self._where_sql(validation_filter=validation_filter)}
                                GROUP BY instrument_id, trade_date
                                HAVING count() > 1
                            )
                        """,
                    ),
                    ValidationRule(
                        rule_id="dws_factor_wide_matrix_factor_count_positive",
                        description="DWS factor matrix must include mapped factor columns",
                        severity="BLOCKER",
                        issue_count_sql=f"""
                            SELECT count() AS issue_count
                            FROM {qualified}
                            {self._where_sql("factor_count <= 0", validation_filter)}
                        """,
                    ),
                    ValidationRule(
                        rule_id="dws_factor_wide_matrix_no_future_trade_visibility",
                        description="DWS factor matrix rows must not be available before their trade date",
                        severity="BLOCKER",
                        issue_count_sql=f"""
                            SELECT count() AS issue_count
                            FROM {qualified}
                            {self._where_sql("available_trade_date < trade_date", validation_filter)}
                        """,
                    ),
                ]
            )
        return rules

    @staticmethod
    def _where_sql(condition: str | None = None, validation_filter: str | None = None) -> str:
        predicates = [predicate for predicate in [validation_filter, condition] if predicate]
        if not predicates:
            return ""
        return "WHERE " + "\n                      AND ".join(f"({predicate})" for predicate in predicates)

    @classmethod
    def _row_count_rule(cls, qualified_table_name: str, validation_filter: str | None = None) -> ValidationRule:
        return ValidationRule(
            rule_id="row_count_nonzero",
            description="Validated table must not be empty",
            severity="BLOCKER",
            issue_count_sql=f"""
                SELECT if(count() = 0, 1, 0) AS issue_count
                FROM {qualified_table_name}
                {cls._where_sql(validation_filter=validation_filter)}
            """,
        )

    @staticmethod
    def _required_columns_rule(db_name: str, table_name: str, columns: list[str]) -> ValidationRule:
        columns_sql = ", ".join([f"'{column}'" for column in columns])
        return ValidationRule(
            rule_id="required_columns_exist",
            description="Required validation columns must exist",
            severity="BLOCKER",
            issue_count_sql=f"""
                SELECT {len(columns)} - count() AS issue_count
                FROM system.columns
                WHERE database = '{db_name}'
                  AND table = '{table_name}'
                  AND name IN ({columns_sql})
            """,
        )

    @staticmethod
    def _ohlc_issue_sql(
        qualified_table_name: str,
        validation_filter: str | None = None,
        activity_condition: str | None = None,
    ) -> str:
        ohlc_condition = "high < low OR high < open OR high < close OR low > open OR low > close"
        if activity_condition:
            ohlc_condition = f"({activity_condition}) AND ({ohlc_condition})"
        return f"""
            SELECT count() AS issue_count
            FROM {qualified_table_name}
            {QualityManager._where_sql(ohlc_condition, validation_filter)}
        """

    @staticmethod
    def _dwd_validation_filter(table_name: str) -> str | None:
        if table_name in DWD_TRADE_RELEVANT_TABLES:
            return f"event_date >= {TRADE_VALIDATION_MIN_DATE_SQL}"
        return None

    @staticmethod
    def _dws_validation_filter(table_name: str) -> str | None:
        date_column = DWS_TRADE_DATE_COLUMNS.get(table_name)
        if date_column:
            return f"{date_column} >= {TRADE_VALIDATION_MIN_DATE_SQL}"
        return None

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f.read())

    def _load_dwd_spec(self, table_name: str) -> dict[str, Any]:
        for path in DWD_SCHEMA_DIR.glob("*.yaml"):
            spec = self._load_yaml(path)
            if spec["name"] == table_name:
                return spec
        raise ValueError(f"DWD table {table_name} not found")

    def _load_ods_schema(self, schema_name: str) -> dict[str, Any]:
        return self._load_yaml(ODS_SCHEMA_DIR / f"{schema_name}.yaml")

    def _dwd_business_key_columns(self, table_name: str) -> list[str]:
        spec = self._load_dwd_spec(table_name)
        if spec.get("builder", "raw_versioned") == "security_master":
            return ["instrument_id"]

        source_schema = self._load_ods_schema(spec["source"]["schema_name"])
        key_columns = spec.get("business_key") or source_schema.get("primary_key", [])
        if not key_columns:
            if table_name == "dwd_trade_calendar":
                return ["event_date"]
            return ["instrument_id", "event_date"]
        return key_columns

    def _dwd_open_version_rules(
        self,
        table_name: str,
        qualified: str,
        validation_filter: str | None = None,
    ) -> list[ValidationRule]:
        key_columns = self._dwd_business_key_columns(table_name)

        key_select = ", ".join(key_columns)
        partition = ", ".join(key_columns)
        return [
            ValidationRule(
                rule_id="dwd_single_open_version",
                description="DWD tables must have at most one open PIT version per business key",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM (
                        SELECT {key_select}
                        FROM {qualified}
                        {self._where_sql(f"sys_to = {FAR_FUTURE_TS}", validation_filter)}
                        GROUP BY {key_select}
                        HAVING count() > 1
                    )
                """,
            ),
            ValidationRule(
                rule_id="dwd_no_overlapping_versions",
                description="DWD version windows must not overlap for the same business key",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM (
                        SELECT
                            {key_select},
                            sys_from,
                            sys_to,
                            leadInFrame(sys_from, 1, {FAR_FUTURE_TS}) OVER (
                                PARTITION BY {partition}
                                ORDER BY sys_from, source_batch_id, source_record_hash
                                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                            ) AS next_sys_from
                        FROM {qualified}
                        {self._where_sql(validation_filter=validation_filter)}
                    )
                    WHERE sys_to > next_sys_from
                """,
            ),
        ]

    def _dwd_business_rules(
        self,
        table_name: str,
        qualified: str,
        validation_filter: str | None = None,
    ) -> list[ValidationRule]:
        rules: list[ValidationRule] = []
        if table_name in {"dwd_stock_eod_price", "dwd_index_eod_price", "dwd_future_eod_price"}:
            rules.extend(self._market_price_rules(table_name, qualified, validation_filter))
        if table_name == "dwd_stock_daily_basic":
            rules.extend(self._daily_basic_rules(qualified, validation_filter))
        if table_name == "dwd_stock_eod_quote_metrics":
            rules.extend(self._quote_metric_rules(qualified, validation_filter))
        if table_name == "dwd_stock_adj_factor":
            rules.append(
                ValidationRule(
                    rule_id="adj_factor_positive",
                    description="Adjustment factor must be positive",
                    severity="BLOCKER",
                    issue_count_sql=f"""
                        SELECT count() AS issue_count
                        FROM {qualified}
                        {self._where_sql("adj_factor <= 0", validation_filter)}
                    """,
                )
            )
        if table_name in {
            "dwd_stock_financial_indicator",
            "dwd_stock_income",
            "dwd_stock_balance_sheet",
            "dwd_stock_cashflow",
            "dwd_stock_dividend",
        }:
            rules.extend(self._financial_rules(table_name, qualified))
        if table_name == "dwd_stock_dividend":
            rules.extend(self._dividend_rules(qualified, validation_filter))
        if table_name == "dwd_stock_margin_trading":
            rules.extend(self._margin_rules(qualified, validation_filter))
        if table_name == "dwd_stock_northbound_holding":
            rules.extend(self._northbound_rules(qualified, validation_filter))
        if table_name == "dwd_stock_chip_distribution":
            rules.extend(self._chip_rules(qualified, validation_filter))
        if table_name == "dwd_index_weight":
            rules.extend(self._index_weight_rules(qualified, validation_filter))
        if table_name == "dwd_security_master":
            rules.extend(self._security_master_rules(qualified))
        return rules

    def _market_price_rules(
        self,
        table_name: str,
        qualified: str,
        validation_filter: str | None = None,
    ) -> list[ValidationRule]:
        rules = [
            ValidationRule(
                rule_id="market_ohlc_consistency",
                description="Market OHLC fields must be internally consistent",
                severity="BLOCKER",
                issue_count_sql=self._ohlc_issue_sql(
                    qualified,
                    validation_filter,
                    "vol > 0 OR open > 0 OR high > 0 OR low > 0",
                ),
            ),
            ValidationRule(
                rule_id="market_nonnegative_volume_amount",
                description="Market volume and amount must be nonnegative",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("vol < 0 OR amount < 0", validation_filter)}
                """,
            ),
            ValidationRule(
                rule_id="market_positive_prices_when_traded",
                description="Traded rows must have positive OHLC and pre-close prices",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("vol > 0 AND (open <= 0 OR high <= 0 OR low <= 0 OR close <= 0 OR pre_close <= 0)", validation_filter)}
                """,
            ),
            ValidationRule(
                rule_id="market_available_not_before_event",
                description="Market data cannot be available before event date",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("available_trade_date < event_date", validation_filter)}
                """,
            ),
        ]
        if table_name == "dwd_future_eod_price":
            rules.append(
                ValidationRule(
                    rule_id="future_settle_positive_when_traded",
                    description="Traded future rows must have positive settlement prices",
                    severity="BLOCKER",
                    issue_count_sql=f"""
                        SELECT count() AS issue_count
                        FROM {qualified}
                        {self._where_sql("vol > 0 AND (settle <= 0 OR pre_settle <= 0 OR oi < 0)", validation_filter)}
                    """,
                )
            )
        return rules

    def _daily_basic_rules(self, qualified: str, validation_filter: str | None = None) -> list[ValidationRule]:
        return [
            ValidationRule(
                rule_id="daily_basic_share_hierarchy",
                description="Total shares must be at least float shares and free shares",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("total_share < 0 OR float_share < 0 OR free_share < 0 OR total_share < float_share OR float_share < free_share", validation_filter)}
                """,
            ),
            ValidationRule(
                rule_id="daily_basic_market_value_hierarchy",
                description="Total market value must be at least circulating market value",
                severity="WARN",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("total_mv < 0 OR circ_mv < 0 OR total_mv < circ_mv", validation_filter)}
                """,
            ),
            ValidationRule(
                rule_id="daily_basic_nonnegative_turnover",
                description="Turnover and volume-ratio fields must be nonnegative",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("turnover_rate < 0 OR turnover_rate_f < 0 OR volume_ratio < 0", validation_filter)}
                """,
            ),
        ]

    def _quote_metric_rules(self, qualified: str, validation_filter: str | None = None) -> list[ValidationRule]:
        return [
            ValidationRule(
                rule_id="quote_metrics_ohlc_consistency",
                description="Quote metric OHLC fields must be internally consistent",
                severity="BLOCKER",
                issue_count_sql=self._ohlc_issue_sql(
                    qualified,
                    validation_filter,
                    "vol > 0 OR open > 0 OR high > 0 OR low > 0",
                ),
            ),
            ValidationRule(
                rule_id="quote_metrics_average_price_range",
                description="Average price should be inside the daily low-high range when traded",
                severity="WARN",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("vol > 0 AND avg_price > 0 AND (avg_price < low OR avg_price > high)", validation_filter)}
                """,
            ),
            ValidationRule(
                rule_id="quote_metrics_nonnegative_market_fields",
                description="Quote metric market activity fields must be nonnegative",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("vol < 0 OR amount < 0 OR vol_ratio < 0 OR turn_over < 0", validation_filter)}
                """,
            ),
        ]

    def _index_weight_rules(self, qualified: str, validation_filter: str | None = None) -> list[ValidationRule]:
        return [
            ValidationRule(
                rule_id="index_weight_percent_range",
                description="Index constituent weight must be a percentage in [0, 100]",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("weight < 0 OR weight > 100", validation_filter)}
                """,
            ),
            ValidationRule(
                rule_id="index_weight_available_not_before_event",
                description="Index constituent weight cannot be available before event date",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("available_trade_date < event_date", validation_filter)}
                """,
            ),
        ]

    def _financial_rules(self, table_name: str, qualified: str) -> list[ValidationRule]:
        rules = [
            ValidationRule(
                rule_id="financial_no_placeholder_dates",
                description="Financial DWD rows must not use placeholder dates",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    WHERE event_date <= toDate32('1971-01-01')
                       OR ann_date <= toDate32('1971-01-01')
                       OR available_trade_date <= toDate32('1971-01-01')
                """,
            ),
            ValidationRule(
                rule_id="financial_quarter_end_event_date",
                description="Financial event date must be a quarter-end date",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    WHERE formatDateTime(event_date, '%m-%d') NOT IN ('03-31', '06-30', '09-30', '12-31')
                """,
            ),
            ValidationRule(
                rule_id="financial_announced_after_period",
                description="Financial announcement date must not precede report period end",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    WHERE ann_date < event_date
                """,
            ),
            ValidationRule(
                rule_id="financial_no_same_day_pit_visibility",
                description="Financial rows must become available after announcement date",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    WHERE available_trade_date <= ann_date
                """,
            ),
        ]
        if table_name == "dwd_stock_balance_sheet":
            rules.append(
                ValidationRule(
                    rule_id="balance_sheet_assets_equation",
                    description="Balance sheet assets should reconcile with liabilities plus equity",
                    severity="WARN",
                    issue_count_sql=f"""
                        SELECT count() AS issue_count
                        FROM {qualified}
                        WHERE total_assets IS NOT NULL
                          AND total_liab IS NOT NULL
                          AND total_hldr_eqy_inc_min_int IS NOT NULL
                          AND abs(total_assets - total_liab - total_hldr_eqy_inc_min_int)
                              > greatest(abs(total_assets) * 0.01, 1)
                    """,
                )
            )
        if table_name == "dwd_stock_cashflow":
            rules.append(
                ValidationRule(
                    rule_id="cashflow_operating_net_flow",
                    description="Operating cash-flow net amount should reconcile with inflow minus outflow",
                    severity="WARN",
                    issue_count_sql=f"""
                        SELECT count() AS issue_count
                        FROM {qualified}
                        WHERE c_inf_fr_operate_a IS NOT NULL
                          AND st_cash_out_act IS NOT NULL
                          AND n_cashflow_act IS NOT NULL
                          AND abs(n_cashflow_act - c_inf_fr_operate_a + st_cash_out_act)
                              > greatest(abs(n_cashflow_act) * 0.01, 1)
                    """,
                )
            )
        return rules

    def _dividend_rules(self, qualified: str, validation_filter: str | None = None) -> list[ValidationRule]:
        nonnegative_condition = (
            "stk_div < 0 OR stk_bo_rate < 0 OR stk_co_rate < 0 "
            "OR cash_div < 0 OR cash_div_tax < 0 OR base_share < 0"
        )
        action_date_condition = (
            "record_date < ann_date OR ex_date < ann_date OR pay_date < ann_date "
            "OR div_listdate < ann_date OR imp_ann_date < ann_date"
        )
        return [
            ValidationRule(
                rule_id="dividend_nonnegative_values",
                description="Dividend rates and cash amounts must be nonnegative",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql(nonnegative_condition, validation_filter)}
                """,
            ),
            ValidationRule(
                rule_id="dividend_action_dates_not_before_announcement",
                description="Dividend action dates must not precede the first announcement date",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql(action_date_condition, validation_filter)}
                """,
            ),
        ]

    def _margin_rules(self, qualified: str, validation_filter: str | None = None) -> list[ValidationRule]:
        return [
            ValidationRule(
                rule_id="margin_nonnegative_fields",
                description="Margin balances and flows must be nonnegative",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("rzye < 0 OR rqye < 0 OR rzmre < 0 OR rzche < 0 OR rqyl < 0 OR rqchl < 0 OR rqmcl < 0 OR rzrqye < 0", validation_filter)}
                """,
            ),
            ValidationRule(
                rule_id="margin_total_balance_reconciliation",
                description="Total margin balance should equal financing plus securities lending balance",
                severity="WARN",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("abs(rzrqye - rzye - rqye) > greatest(abs(rzrqye) * 0.001, 1)", validation_filter)}
                """,
            ),
        ]

    def _northbound_rules(self, qualified: str, validation_filter: str | None = None) -> list[ValidationRule]:
        return [
            ValidationRule(
                rule_id="northbound_holding_bounds",
                description="Northbound holding volume and ratio must be in valid bounds",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("vol < 0 OR ratio < 0 OR ratio > 100", validation_filter)}
                """,
            ),
            ValidationRule(
                rule_id="northbound_channel_present",
                description="Northbound holding rows should keep the connect channel",
                severity="WARN",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("connect_channel = ''", validation_filter)}
                """,
            ),
        ]

    def _chip_rules(self, qualified: str, validation_filter: str | None = None) -> list[ValidationRule]:
        return [
            ValidationRule(
                rule_id="chip_price_bounds",
                description="Chip distribution historical high must be at least historical low",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("his_high < his_low", validation_filter)}
                """,
            ),
            ValidationRule(
                rule_id="chip_cost_percentiles_monotonic",
                description="Chip distribution cost percentiles must be monotonic",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("cost_5pct > cost_15pct OR cost_15pct > cost_50pct OR cost_50pct > cost_85pct OR cost_85pct > cost_95pct", validation_filter)}
                """,
            ),
            ValidationRule(
                rule_id="chip_winner_rate_bounds",
                description="Chip distribution winner rate must be between 0 and 100",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    {self._where_sql("winner_rate < 0 OR winner_rate > 100", validation_filter)}
                """,
            ),
        ]

    def _security_master_rules(self, qualified: str) -> list[ValidationRule]:
        return [
            ValidationRule(
                rule_id="security_master_lifecycle_dates",
                description="Security master list date must not be after delist date",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    WHERE delist_date IS NOT NULL AND list_date IS NOT NULL AND list_date > delist_date
                """,
            ),
            ValidationRule(
                rule_id="security_master_instrument_type",
                description="Security master instrument type must be recognized",
                severity="BLOCKER",
                issue_count_sql=f"""
                    SELECT count() AS issue_count
                    FROM {qualified}
                    WHERE instrument_type NOT IN ('stock', 'index', 'future')
                """,
            ),
        ]

    def _metadata_table_schemas(self) -> dict[str, dict[str, Any]]:
        common_indexes = [{"name": "quality_idx", "columns": ["run_id"]}]
        return {
            "dq_validation_run": {
                "comment": "Data quality validation run",
                "primary_key": [],
                "partition_key": ["toYYYYMM(started_at)"],
                "indexes": common_indexes,
                "columns": [
                    {"name": "run_id", "data_type": "str", "length": 64, "comment": "Validation run id"},
                    {"name": "layer", "data_type": "str", "length": 32, "comment": "Data layer"},
                    {"name": "stage", "data_type": "str", "length": 64, "comment": "Validation stage"},
                    {"name": "table_name", "data_type": "str", "length": 128, "comment": "Logical table name"},
                    {"name": "target_table_name", "data_type": "str", "length": 128, "comment": "Physical target table"},
                    {"name": "mode", "data_type": "str", "length": 32, "comment": "Validation mode"},
                    {"name": "status", "data_type": "str", "length": 32, "comment": "Validation run status"},
                    {"name": "started_at", "data_type": "datetime", "comment": "Run start time"},
                    {"name": "finished_at", "data_type": "datetime", "comment": "Run finish time"},
                ],
            },
            "dq_validation_result": {
                "comment": "Data quality validation rule result",
                "primary_key": [],
                "partition_key": ["toYYYYMM(created_at)"],
                "indexes": common_indexes,
                "columns": [
                    {"name": "run_id", "data_type": "str", "length": 64, "comment": "Validation run id"},
                    {"name": "rule_id", "data_type": "str", "length": 128, "comment": "Validation rule id"},
                    {"name": "severity", "data_type": "str", "length": 32, "comment": "Rule severity"},
                    {"name": "status", "data_type": "str", "length": 32, "comment": "Rule status"},
                    {"name": "issue_count", "data_type": "int", "comment": "Issue row count"},
                    {"name": "description", "data_type": "str", "length": 512, "comment": "Rule description"},
                    {"name": "message", "data_type": "str", "length": 1024, "comment": "Rule message"},
                    {"name": "created_at", "data_type": "datetime", "comment": "Created time"},
                ],
            },
            "dq_validation_metric": {
                "comment": "Data quality validation metrics",
                "primary_key": [],
                "partition_key": ["toYYYYMM(created_at)"],
                "indexes": common_indexes,
                "columns": [
                    {"name": "run_id", "data_type": "str", "length": 64, "comment": "Validation run id"},
                    {"name": "metric_name", "data_type": "str", "length": 128, "comment": "Metric name"},
                    {"name": "metric_value", "data_type": "float", "comment": "Metric value"},
                    {"name": "table_name", "data_type": "str", "length": 128, "comment": "Logical table name"},
                    {"name": "created_at", "data_type": "datetime", "comment": "Created time"},
                ],
            },
            "dq_issue_sample": {
                "comment": "Data quality failed-row samples",
                "primary_key": [],
                "partition_key": ["toYYYYMM(created_at)"],
                "indexes": common_indexes,
                "columns": [
                    {"name": "run_id", "data_type": "str", "length": 64, "comment": "Validation run id"},
                    {"name": "rule_id", "data_type": "str", "length": 128, "comment": "Validation rule id"},
                    {"name": "sample_json", "data_type": "json", "length": 8192, "comment": "Failed-row sample JSON"},
                    {"name": "created_at", "data_type": "datetime", "comment": "Created time"},
                ],
            },
        }

    def ensure_result_tables(self) -> None:
        db_engine = self.get_db_engine()
        for table_name, schema in self._metadata_table_schemas().items():
            db_engine.create_table(table_name, schema)

    def _record_run(self, run: ValidationRun) -> None:
        try:
            if self.settings.quality.create_result_tables:
                self.ensure_result_tables()

            db_engine = self.get_db_engine()
            db_engine.insert(
                "dq_validation_run",
                self._metadata_table_schemas()["dq_validation_run"],
                pd.DataFrame(
                    [
                        {
                            "run_id": run.run_id,
                            "layer": run.layer,
                            "stage": run.stage,
                            "table_name": run.table_name,
                            "target_table_name": run.target_table_name,
                            "mode": run.mode,
                            "status": run.status,
                            "started_at": run.started_at,
                            "finished_at": run.finished_at,
                        }
                    ]
                ),
            )
            if run.results:
                db_engine.insert(
                    "dq_validation_result",
                    self._metadata_table_schemas()["dq_validation_result"],
                    pd.DataFrame(
                        [
                            {
                                "run_id": run.run_id,
                                "rule_id": result.rule_id,
                                "severity": result.severity,
                                "status": result.status,
                                "issue_count": result.issue_count,
                                "description": result.description,
                                "message": result.message,
                                "created_at": run.finished_at,
                            }
                            for result in run.results
                        ]
                    ),
                )
                db_engine.insert(
                    "dq_validation_metric",
                    self._metadata_table_schemas()["dq_validation_metric"],
                    pd.DataFrame(
                        [
                            {
                                "run_id": run.run_id,
                                "metric_name": f"{result.rule_id}.issue_count",
                                "metric_value": float(result.issue_count),
                                "table_name": run.table_name,
                                "created_at": run.finished_at,
                            }
                            for result in run.results
                        ]
                    ),
                )
        except Exception:
            logging.exception("Failed to record validation run %s", run.run_id)

    def report_run(self, run_id: str) -> str:
        db_name = self.settings.database.db_name
        run_df = self.get_db_engine().query_df(
            f"""
            SELECT *
            FROM {db_name}.dq_validation_run
            WHERE run_id = '{run_id}'
            ORDER BY started_at DESC
            LIMIT 1
            """
        )
        result_df = self.get_db_engine().query_df(
            f"""
            SELECT rule_id, severity, status, issue_count, description, message
            FROM {db_name}.dq_validation_result
            WHERE run_id = '{run_id}'
            ORDER BY severity, rule_id
            """
        )
        if run_df.empty:
            return f"Validation run {run_id} not found"
        run = run_df.iloc[0].to_dict()
        lines = [
            f"run_id: {run_id}",
            f"table: {run.get('layer')}.{run.get('table_name')} target={run.get('target_table_name')}",
            f"mode/status: {run.get('mode')}/{run.get('status')}",
        ]
        for row in result_df.to_dict("records"):
            message = f" message={row['message']}" if row.get("message") else ""
            lines.append(
                f"- {row['severity']} {row['status']} {row['rule_id']} issues={row['issue_count']}{message}"
            )
        return "\n".join(lines)

    @staticmethod
    def run_to_json(run: ValidationRun) -> str:
        return json.dumps(
            {
                "run_id": run.run_id,
                "layer": run.layer,
                "stage": run.stage,
                "table_name": run.table_name,
                "target_table_name": run.target_table_name,
                "mode": run.mode,
                "status": run.status,
                "results": [result.__dict__ for result in run.results],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )


class DqcManager:
    def __init__(self, settings: TushareIntegrationSettings | None = None, db_engine: DBEngine | None = None):
        self.settings = settings or TushareIntegrationSettings.model_validate(
            yaml.safe_load(open("config.yaml", "r", encoding="utf-8").read())
        )
        self.db_engine = db_engine

    def get_db_engine(self) -> DBEngine:
        if self.db_engine is None:
            self.db_engine = DatabaseEngineFactory.create(self.settings)
        return self.db_engine

    @staticmethod
    def supported_suites() -> dict[tuple[str, str], list[str]]:
        return DQC_SUITE_TABLES.copy()

    def resolve_mode(self, override_mode: ValidationMode | None = None) -> ValidationMode:
        return override_mode or self.settings.quality.dqc_mode

    def resolve_suite(self, layer: str, suite_name: str | None) -> str:
        resolved_suite = suite_name or DQC_DEFAULT_SUITE_BY_LAYER.get(layer)
        if not resolved_suite or (layer, resolved_suite) not in DQC_SUITE_TABLES:
            raise ValueError(f"Unsupported DQC suite for layer={layer}: {suite_name or '<default>'}")
        return resolved_suite

    def resolve_tables(self, layer: str, suite_name: str, table_name: str | None = None) -> list[str]:
        tables = DQC_SUITE_TABLES[(layer, suite_name)]
        if table_name is None or table_name == "all":
            return tables
        if table_name not in tables:
            raise ValueError(f"Table {table_name} is not supported by DQC suite {layer}.{suite_name}")
        return [table_name]

    @staticmethod
    def _parse_date(value: str | datetime.date | None) -> datetime.date:
        if value is None:
            return datetime.date.today()
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        return datetime.date.fromisoformat(value)

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None or pd.isna(value):
            return None
        return float(value)

    @staticmethod
    def _safe_ratio(left_value: float, right_value: float) -> float | None:
        if right_value == 0:
            return None
        return left_value / right_value

    @staticmethod
    def _sql_date(value: datetime.date | str) -> str:
        date_value = value.isoformat() if isinstance(value, datetime.date) else value
        return f"toDate32('{date_value}')"

    @staticmethod
    def _chunks(values: list[str], chunk_size: int) -> list[list[str]]:
        return [values[index : index + chunk_size] for index in range(0, len(values), chunk_size)]

    @classmethod
    def _target_trade_date_sql(cls, as_of_date: datetime.date) -> str:
        return f"""
            (
                SELECT max(event_date)
                FROM {{db_name}}.dwd_trade_calendar
                WHERE sys_to = {FAR_FUTURE_TS}
                  AND is_open = 1
                  AND event_date <= {cls._sql_date(as_of_date)}
            )
        """

    def _metadata_table_schemas(self) -> dict[str, dict[str, Any]]:
        common_indexes = [{"name": "dqc_idx", "columns": ["run_id"]}]
        return {
            "dq_dqc_run": {
                "comment": "Systematic data quality control run",
                "primary_key": [],
                "partition_key": ["toYYYYMM(started_at)"],
                "indexes": common_indexes,
                "columns": [
                    {"name": "run_id", "data_type": "str", "length": 64, "comment": "DQC run id"},
                    {"name": "layer", "data_type": "str", "length": 32, "comment": "Data layer"},
                    {"name": "domain", "data_type": "str", "length": 64, "comment": "DQC domain"},
                    {"name": "suite_name", "data_type": "str", "length": 128, "comment": "DQC suite name"},
                    {"name": "table_name", "data_type": "str", "length": 128, "comment": "Logical table or all"},
                    {"name": "as_of_date", "data_type": "date", "comment": "DQC as-of date"},
                    {"name": "mode", "data_type": "str", "length": 32, "comment": "DQC mode"},
                    {"name": "status", "data_type": "str", "length": 32, "comment": "DQC run status"},
                    {"name": "started_at", "data_type": "datetime", "comment": "Run start time"},
                    {"name": "finished_at", "data_type": "datetime", "comment": "Run finish time"},
                    {
                        "name": "baseline_window_days",
                        "data_type": "int",
                        "comment": "Rolling baseline window in days",
                    },
                ],
            },
            "dq_dqc_result": {
                "comment": "Systematic data quality control rule result",
                "primary_key": [],
                "partition_key": ["toYYYYMM(created_at)"],
                "indexes": common_indexes,
                "columns": [
                    {"name": "run_id", "data_type": "str", "length": 64, "comment": "DQC run id"},
                    {"name": "layer", "data_type": "str", "length": 32, "comment": "Data layer"},
                    {"name": "domain", "data_type": "str", "length": 64, "comment": "DQC domain"},
                    {"name": "suite_name", "data_type": "str", "length": 128, "comment": "DQC suite name"},
                    {"name": "table_name", "data_type": "str", "length": 128, "comment": "Logical table name"},
                    {"name": "check_layer", "data_type": "str", "length": 64, "comment": "DQC check layer"},
                    {"name": "check_type", "data_type": "str", "length": 64, "comment": "DQC check type"},
                    {"name": "rule_id", "data_type": "str", "length": 160, "comment": "DQC rule id"},
                    {"name": "severity", "data_type": "str", "length": 32, "comment": "Rule severity"},
                    {"name": "status", "data_type": "str", "length": 32, "comment": "Rule status"},
                    {"name": "checked_count", "data_type": "int", "comment": "Checked row or entity count"},
                    {"name": "issue_count", "data_type": "int", "comment": "Issue count"},
                    {"name": "issue_rate", "data_type": "float", "nullable": True, "comment": "Issue count / checked count"},
                    {"name": "observed_value", "data_type": "float", "nullable": True, "comment": "Observed value"},
                    {"name": "expected_min", "data_type": "float", "nullable": True, "comment": "Expected minimum"},
                    {"name": "expected_max", "data_type": "float", "nullable": True, "comment": "Expected maximum"},
                    {"name": "baseline_mean", "data_type": "float", "nullable": True, "comment": "Baseline mean"},
                    {"name": "baseline_std", "data_type": "float", "nullable": True, "comment": "Baseline stddev"},
                    {"name": "z_score", "data_type": "float", "nullable": True, "comment": "Drift z-score"},
                    {"name": "message", "data_type": "str", "length": 1024, "comment": "Rule message"},
                    {"name": "created_at", "data_type": "datetime", "comment": "Created time"},
                ],
            },
            "dq_dqc_metric": {
                "comment": "Systematic data quality control metrics",
                "primary_key": [],
                "partition_key": ["toYYYYMM(as_of_date)"],
                "indexes": common_indexes,
                "columns": [
                    {"name": "run_id", "data_type": "str", "length": 64, "comment": "DQC run id"},
                    {"name": "layer", "data_type": "str", "length": 32, "comment": "Data layer"},
                    {"name": "domain", "data_type": "str", "length": 64, "comment": "DQC domain"},
                    {"name": "suite_name", "data_type": "str", "length": 128, "comment": "DQC suite name"},
                    {"name": "table_name", "data_type": "str", "length": 128, "comment": "Logical table name"},
                    {"name": "as_of_date", "data_type": "date", "comment": "DQC as-of date"},
                    {"name": "trade_date", "data_type": "date", "comment": "Observed trade date"},
                    {"name": "metric_scope", "data_type": "str", "length": 64, "comment": "Metric scope"},
                    {"name": "entity_name", "data_type": "str", "length": 160, "comment": "Column or entity name"},
                    {"name": "metric_name", "data_type": "str", "length": 128, "comment": "Metric name"},
                    {"name": "metric_value", "data_type": "float", "comment": "Metric value"},
                    {"name": "created_at", "data_type": "datetime", "comment": "Created time"},
                ],
            },
            "dq_dqc_consistency": {
                "comment": "Systematic data quality control consistency checks",
                "primary_key": [],
                "partition_key": ["toYYYYMM(as_of_date)"],
                "indexes": common_indexes,
                "columns": [
                    {"name": "run_id", "data_type": "str", "length": 64, "comment": "DQC run id"},
                    {"name": "layer", "data_type": "str", "length": 32, "comment": "Data layer"},
                    {"name": "domain", "data_type": "str", "length": 64, "comment": "DQC domain"},
                    {"name": "suite_name", "data_type": "str", "length": 128, "comment": "DQC suite name"},
                    {"name": "left_table", "data_type": "str", "length": 128, "comment": "Left table"},
                    {"name": "right_table", "data_type": "str", "length": 128, "comment": "Right table"},
                    {"name": "as_of_date", "data_type": "date", "comment": "DQC as-of date"},
                    {"name": "trade_date", "data_type": "date", "comment": "Observed trade date"},
                    {"name": "check_name", "data_type": "str", "length": 128, "comment": "Consistency check"},
                    {"name": "left_value", "data_type": "float", "comment": "Left value"},
                    {"name": "right_value", "data_type": "float", "comment": "Right value"},
                    {"name": "ratio", "data_type": "float", "nullable": True, "comment": "Left/right ratio"},
                    {"name": "status", "data_type": "str", "length": 32, "comment": "Check status"},
                    {"name": "created_at", "data_type": "datetime", "comment": "Created time"},
                ],
            },
            "dq_dqc_sample": {
                "comment": "Systematic data quality control samples",
                "primary_key": [],
                "partition_key": ["toYYYYMM(as_of_date)"],
                "indexes": common_indexes,
                "columns": [
                    {"name": "run_id", "data_type": "str", "length": 64, "comment": "DQC run id"},
                    {"name": "layer", "data_type": "str", "length": 32, "comment": "Data layer"},
                    {"name": "domain", "data_type": "str", "length": 64, "comment": "DQC domain"},
                    {"name": "suite_name", "data_type": "str", "length": 128, "comment": "DQC suite name"},
                    {"name": "table_name", "data_type": "str", "length": 128, "comment": "Logical table name"},
                    {"name": "rule_id", "data_type": "str", "length": 160, "comment": "DQC rule id"},
                    {"name": "as_of_date", "data_type": "date", "comment": "DQC as-of date"},
                    {"name": "trade_date", "data_type": "date", "comment": "Observed trade date"},
                    {"name": "instrument_id", "data_type": "str", "length": 64, "comment": "Instrument id"},
                    {"name": "entity_name", "data_type": "str", "length": 160, "comment": "Column or factor id"},
                    {"name": "sample_type", "data_type": "str", "length": 64, "comment": "Sample type"},
                    {"name": "sample_json", "data_type": "json", "length": 8192, "comment": "Sample JSON"},
                    {"name": "created_at", "data_type": "datetime", "comment": "Created time"},
                ],
            },
        }

    def ensure_result_tables(self) -> None:
        db_engine = self.get_db_engine()
        for table_name, schema in self._metadata_table_schemas().items():
            db_engine.create_table(table_name, schema)
        if self.settings.database.db_type == "clickhouse":
            db_engine.query(
                f"""
                ALTER TABLE {self.settings.database.db_name}.dq_dqc_result
                ADD COLUMN IF NOT EXISTS `issue_rate` Nullable(Float64) COMMENT 'Issue count / checked count'
                AFTER `issue_count`
                """
            )

    def run(
        self,
        layer: str = "dws",
        suite_name: str | None = None,
        table_name: str | None = None,
        as_of_date: str | datetime.date | None = None,
        mode: ValidationMode | None = None,
    ) -> DqcRun:
        if self.settings.database.db_type != "clickhouse":
            raise NotImplementedError("Systematic DQC currently supports ClickHouse SQL only")

        resolved_suite = self.resolve_suite(layer, suite_name)
        domain = DQC_SUITE_DOMAIN[(layer, resolved_suite)]
        tables = self.resolve_tables(layer, resolved_suite, table_name)
        resolved_mode = self.resolve_mode(mode)
        resolved_as_of_date = self._parse_date(as_of_date)
        started_at = datetime.datetime.now()
        run_id = uuid.uuid4().hex
        display_table_name = table_name or "all"

        if resolved_mode == "skip":
            run = DqcRun(
                run_id=run_id,
                layer=layer,
                domain=domain,
                suite_name=resolved_suite,
                table_name=display_table_name,
                as_of_date=resolved_as_of_date,
                mode=resolved_mode,
                status="SKIPPED",
                started_at=started_at,
                finished_at=datetime.datetime.now(),
                baseline_window_days=self.settings.quality.dqc_baseline_window_days,
                results=[],
                metrics=[],
                consistencies=[],
                samples=[],
            )
            self._record_run(run)
            return run

        try:
            if self.settings.quality.dqc_create_result_tables:
                self.ensure_result_tables()
            if (layer, resolved_suite) == ("dws", "stock_factor_panel"):
                results, metrics, consistencies, samples = self._run_dws_stock_factor_panel(
                    run_id=run_id,
                    domain=domain,
                    suite_name=resolved_suite,
                    tables=tables,
                    as_of_date=resolved_as_of_date,
                    include_consistency=len(tables) > 1,
                )
            else:
                raise ValueError(f"Unsupported DQC suite: {layer}.{resolved_suite}")
        except Exception as exc:
            logging.exception("DQC system error for %s.%s table=%s", layer, resolved_suite, display_table_name)
            results = [
                DqcResult(
                    rule_id=VALIDATION_SYSTEM_ERROR,
                    layer=layer,
                    domain=domain,
                    suite_name=resolved_suite,
                    table_name=display_table_name,
                    check_layer="system",
                    check_type="system_error",
                    severity="BLOCKER",
                    status="FAIL",
                    checked_count=1,
                    issue_count=1,
                    message=repr(exc),
                )
            ]
            metrics = []
            consistencies = []
            samples = []

        status = "FAIL" if any(result.status == "FAIL" for result in results) else "PASS"
        run = DqcRun(
            run_id=run_id,
            layer=layer,
            domain=domain,
            suite_name=resolved_suite,
            table_name=display_table_name,
            as_of_date=resolved_as_of_date,
            mode=resolved_mode,
            status=status,
            started_at=started_at,
            finished_at=datetime.datetime.now(),
            baseline_window_days=self.settings.quality.dqc_baseline_window_days,
            results=results,
            metrics=metrics,
            consistencies=consistencies,
            samples=samples,
        )
        self._record_run(run)
        if run.should_block:
            raise DqcValidationError(run)
        return run

    def _run_dws_stock_factor_panel(
        self,
        run_id: str,
        domain: str,
        suite_name: str,
        tables: list[str],
        as_of_date: datetime.date,
        include_consistency: bool,
    ) -> tuple[list[DqcResult], list[DqcMetric], list[DqcConsistency], list[DqcSample]]:
        results: list[DqcResult] = []
        metrics: list[DqcMetric] = []
        consistencies: list[DqcConsistency] = []
        samples: list[DqcSample] = []

        for table_name in tables:
            results.extend(self._dws_table_results(domain, suite_name, table_name, as_of_date))
            table_metrics = self._dws_table_metrics(domain, suite_name, table_name, as_of_date)
            metrics.extend(table_metrics)
            results.extend(self._dws_drift_results(domain, suite_name, table_name, as_of_date, table_metrics))
            samples.extend(self._dws_spot_samples(domain, suite_name, table_name, as_of_date))

        if include_consistency:
            consistency_results, consistencies, consistency_samples = self._dws_consistency_checks(
                domain, suite_name, as_of_date
            )
            results.extend(consistency_results)
            samples.extend(consistency_samples)

        return results, metrics, consistencies, samples

    def _dqc_result(
        self,
        domain: str,
        suite_name: str,
        table_name: str,
        rule_id: str,
        check_layer: str,
        check_type: str,
        severity: ValidationSeverity,
        issue_count: int,
        checked_count: int = 0,
        observed_value: float | None = None,
        expected_min: float | None = None,
        expected_max: float | None = None,
        baseline_mean: float | None = None,
        baseline_std: float | None = None,
        z_score: float | None = None,
        message: str = "",
        status: str | None = None,
    ) -> DqcResult:
        issue_rate = issue_count / checked_count if checked_count else None
        return DqcResult(
            rule_id=rule_id,
            layer="dws",
            domain=domain,
            suite_name=suite_name,
            table_name=table_name,
            check_layer=check_layer,
            check_type=check_type,
            severity=severity,
            status=status or ("FAIL" if issue_count > 0 else "PASS"),
            checked_count=checked_count,
            issue_count=issue_count,
            issue_rate=issue_rate,
            observed_value=observed_value,
            expected_min=expected_min,
            expected_max=expected_max,
            baseline_mean=baseline_mean,
            baseline_std=baseline_std,
            z_score=z_score,
            message=message,
        )

    def _query_first_record(self, sql: str) -> dict[str, Any]:
        df = self.get_db_engine().query_df(sql)
        if df.empty:
            return {}
        return df.iloc[0].to_dict()

    def _query_issue_result(
        self,
        sql: str,
        domain: str,
        suite_name: str,
        table_name: str,
        rule_id: str,
        check_layer: str,
        check_type: str,
        severity: ValidationSeverity,
        message: str = "",
        expected_min: float | None = None,
        expected_max: float | None = None,
    ) -> DqcResult:
        record = self._query_first_record(sql)
        issue_count = int(record.get("issue_count") or 0)
        checked_count = int(record.get("checked_count") or 0)
        observed_value = self._to_float(record.get("observed_value"))
        return self._dqc_result(
            domain=domain,
            suite_name=suite_name,
            table_name=table_name,
            rule_id=rule_id,
            check_layer=check_layer,
            check_type=check_type,
            severity=severity,
            issue_count=issue_count,
            checked_count=checked_count,
            observed_value=observed_value,
            expected_min=expected_min,
            expected_max=expected_max,
            message=message,
        )

    def _dws_spec(self, table_name: str) -> dict[str, Any]:
        return QualityManager._load_yaml(DWS_SCHEMA_DIR / f"{table_name}.yaml")

    def _dws_numeric_columns(self, table_name: str) -> list[str]:
        spec = self._dws_spec(table_name)
        return [
            column["name"]
            for column in spec["schema"]["columns"]
            if column.get("data_type") in DQC_FLOAT_TYPES and column["name"] not in {"factor_count"}
        ]

    def _dws_factor_count(self) -> int:
        with open(FACTOR_MAPPING_CSV, "r", encoding="utf-8") as f:
            rows = csv.DictReader(f)
            return len({row["factor_id"].strip() for row in rows if row.get("factor_id", "").strip()})

    def _dws_table_results(
        self,
        domain: str,
        suite_name: str,
        table_name: str,
        as_of_date: datetime.date,
    ) -> list[DqcResult]:
        db_name = self.settings.database.db_name
        qualified = QualityManager._quote_table(db_name, table_name)
        target_trade_date_sql = self._target_trade_date_sql(as_of_date).format(db_name=db_name)
        numeric_columns = self._dws_numeric_columns(table_name)

        checks = [
            self._query_issue_result(
                f"""
                SELECT if(count() = 0, 1, 0) AS issue_count, count() AS checked_count, count() AS observed_value
                FROM {qualified}
                WHERE trade_date = {target_trade_date_sql}
                """,
                domain,
                suite_name,
                table_name,
                "dqc_row_count_nonzero",
                "completeness",
                "row_count",
                "BLOCKER",
                "Target trade date must have rows",
                expected_min=1,
            ),
            self._query_issue_result(
                f"""
                SELECT
                    countIf(instrument_id = '' OR source_record_hash = '') AS issue_count,
                    count() AS checked_count
                FROM {qualified}
                WHERE trade_date = {target_trade_date_sql}
                """,
                domain,
                suite_name,
                table_name,
                "dqc_required_keys_not_empty",
                "completeness",
                "required_key",
                "BLOCKER",
                "DQC key and lineage fields must be populated",
            ),
            self._query_issue_result(
                f"""
                SELECT
                    countIf(available_trade_date < trade_date) AS issue_count,
                    count() AS checked_count
                FROM {qualified}
                WHERE trade_date = {target_trade_date_sql}
                """,
                domain,
                suite_name,
                table_name,
                "dqc_no_future_trade_visibility",
                "semantic",
                "pit",
                "BLOCKER",
                "Rows must not be available before their trade date",
            ),
            self._query_issue_result(
                f"""
                SELECT
                    if(max(trade_date) < {target_trade_date_sql}, 1, 0) AS issue_count,
                    count() AS checked_count,
                    toFloat64(toRelativeDayNum(max(trade_date))) AS observed_value
                FROM {qualified}
                WHERE trade_date <= {target_trade_date_sql}
                """,
                domain,
                suite_name,
                table_name,
                "dqc_latest_trade_date_fresh",
                "freshness",
                "trade_date",
                "BLOCKER",
                "Latest DWS trade date must reach the expected open trading day",
            ),
        ]

        if numeric_columns:
            checks.append(
                self._dws_numeric_finite_result(
                    domain=domain,
                    suite_name=suite_name,
                    table_name=table_name,
                    qualified=qualified,
                    target_trade_date_sql=target_trade_date_sql,
                    numeric_columns=numeric_columns,
                )
            )

        if table_name == "dws_stock_factor_wide":
            checks.extend(self._dws_factor_wide_semantic_results(domain, suite_name, qualified, target_trade_date_sql))
        if table_name == "dws_stock_factor_wide_matrix":
            checks.extend(
                self._dws_factor_matrix_semantic_results(domain, suite_name, qualified, target_trade_date_sql)
            )
        return checks

    def _dws_numeric_finite_result(
        self,
        domain: str,
        suite_name: str,
        table_name: str,
        qualified: str,
        target_trade_date_sql: str,
        numeric_columns: list[str],
    ) -> DqcResult:
        total_issue_count = 0
        max_checked_count = 0
        # Keep generated SQL below ClickHouse max_query_size for very wide factor matrices.
        for column_chunk in self._chunks(numeric_columns, 80):
            issue_terms = [
                f"countIf(isNotNull(`{column}`) AND (isNaN(assumeNotNull(`{column}`)) "
                f"OR isInfinite(assumeNotNull(`{column}`))))"
                for column in column_chunk
            ]
            record = self._query_first_record(
                f"""
                SELECT ({' + '.join(issue_terms)}) AS issue_count, count() AS checked_count
                FROM {qualified}
                WHERE trade_date = {target_trade_date_sql}
                """
            )
            total_issue_count += int(record.get("issue_count") or 0)
            max_checked_count = max(max_checked_count, int(record.get("checked_count") or 0))
        return self._dqc_result(
            domain=domain,
            suite_name=suite_name,
            table_name=table_name,
            rule_id="dqc_numeric_no_nan_inf",
            check_layer="semantic",
            check_type="numeric_finite",
            severity="BLOCKER",
            issue_count=total_issue_count,
            checked_count=max_checked_count,
            message="Numeric columns must not contain NaN or Inf values",
        )

    def _dws_factor_wide_semantic_results(
        self,
        domain: str,
        suite_name: str,
        qualified: str,
        target_trade_date_sql: str,
    ) -> list[DqcResult]:
        table_name = "dws_stock_factor_wide"
        nonnegative_columns = [
            "vol",
            "amount",
            "total_mv",
            "circ_mv",
            "total_share",
            "float_share",
            "free_share",
            "hk_hold_vol",
            "rzye",
            "rzmre",
            "rzche",
            "rqye",
            "rqyl",
            "rqmcl",
        ]
        nonnegative_condition = " OR ".join([f"`{column}` < 0" for column in nonnegative_columns])
        return [
            self._query_issue_result(
                f"""
                SELECT
                    countIf(high < low OR high < open OR high < close OR low > open OR low > close) AS issue_count,
                    count() AS checked_count
                FROM {qualified}
                WHERE trade_date = {target_trade_date_sql}
                """,
                domain,
                suite_name,
                table_name,
                "dqc_wide_ohlc_consistency",
                "semantic",
                "ohlc",
                "BLOCKER",
                "OHLC fields must be internally consistent",
            ),
            self._query_issue_result(
                f"""
                SELECT
                    countIf({nonnegative_condition}) AS issue_count,
                    count() AS checked_count
                FROM {qualified}
                WHERE trade_date = {target_trade_date_sql}
                """,
                domain,
                suite_name,
                table_name,
                "dqc_wide_nonnegative_quant_fields",
                "semantic",
                "nonnegative",
                "BLOCKER",
                "Volume, amount, share, market value, margin, and holding fields must be nonnegative",
                expected_min=0,
            ),
            self._query_issue_result(
                f"""
                SELECT
                    countIf(isNotNull(winner_rate) AND (winner_rate < 0 OR winner_rate > 100)) AS issue_count,
                    count() AS checked_count
                FROM {qualified}
                WHERE trade_date = {target_trade_date_sql}
                """,
                domain,
                suite_name,
                table_name,
                "dqc_wide_winner_rate_bounds",
                "semantic",
                "bounded_ratio",
                "WARN",
                "winner_rate should stay within [0, 100]",
                expected_min=0,
                expected_max=100,
            ),
        ]

    def _dws_factor_matrix_semantic_results(
        self,
        domain: str,
        suite_name: str,
        qualified: str,
        target_trade_date_sql: str,
    ) -> list[DqcResult]:
        table_name = "dws_stock_factor_wide_matrix"
        expected_factor_count = self._dws_factor_count()
        return [
            self._query_issue_result(
                f"""
                SELECT
                    countIf(factor_count != {expected_factor_count}) AS issue_count,
                    count() AS checked_count
                FROM {qualified}
                WHERE trade_date = {target_trade_date_sql}
                """,
                domain,
                suite_name,
                table_name,
                "dqc_matrix_factor_count_matches_mapping",
                "completeness",
                "factor_coverage",
                "BLOCKER",
                "factor_count must match the configured factor mapping count",
                expected_min=float(expected_factor_count),
                expected_max=float(expected_factor_count),
            ),
            self._query_issue_result(
                f"""
                SELECT
                    countIf(isNotNull(qb_rsi_14) AND (qb_rsi_14 < 0 OR qb_rsi_14 > 100)) AS issue_count,
                    count() AS checked_count
                FROM {qualified}
                WHERE trade_date = {target_trade_date_sql}
                """,
                domain,
                suite_name,
                table_name,
                "dqc_matrix_qb_rsi_14_bounds",
                "semantic",
                "bounded_factor",
                "BLOCKER",
                "RSI14 must stay within [0, 100]",
                expected_min=0,
                expected_max=100,
            ),
            self._query_issue_result(
                f"""
                SELECT
                    countIf(source_table != 'dws_stock_factor_wide' OR source_batch_id = ''
                        OR source_record_hash = '') AS issue_count,
                    count() AS checked_count
                FROM {qualified}
                WHERE trade_date = {target_trade_date_sql}
                """,
                domain,
                suite_name,
                table_name,
                "dqc_matrix_lineage_valid",
                "semantic",
                "lineage",
                "BLOCKER",
                "Matrix rows must keep lineage to dws_stock_factor_wide",
            ),
            self._query_issue_result(
                f"""
                SELECT
                    countIf(
                        length(
                            JSONExtractKeys(
                                ifNull(JSONExtractRaw(ifNull(factor_errors_json, '{{}}'), 'errors'), '{{}}')
                            )
                        ) > 0
                    ) AS issue_count,
                    count() AS checked_count
                FROM {qualified}
                WHERE trade_date = {target_trade_date_sql}
                """,
                domain,
                suite_name,
                table_name,
                "dqc_matrix_factor_errors_empty",
                "semantic",
                "factor_error",
                "WARN",
                "Factor calculation errors object should be empty",
            ),
        ]

    def _dws_table_metrics(
        self,
        domain: str,
        suite_name: str,
        table_name: str,
        as_of_date: datetime.date,
    ) -> list[DqcMetric]:
        db_name = self.settings.database.db_name
        qualified = QualityManager._quote_table(db_name, table_name)
        target_trade_date_sql = self._target_trade_date_sql(as_of_date).format(db_name=db_name)
        metrics: list[DqcMetric] = []

        table_df = self.get_db_engine().query_df(
            f"""
            SELECT
                trade_date,
                count() AS row_count,
                uniqExact(instrument_id) AS instrument_count,
                toFloat64(toRelativeDayNum(max(available_trade_date))) AS max_available_trade_date_day,
                toFloat64(max(toUnixTimestamp(build_time))) AS max_build_time_ts
            FROM {qualified}
            WHERE trade_date = {target_trade_date_sql}
            GROUP BY trade_date
            """
        )
        for row in table_df.to_dict("records"):
            trade_date = row["trade_date"]
            for metric_name in [
                "row_count",
                "instrument_count",
                "max_available_trade_date_day",
                "max_build_time_ts",
            ]:
                value = self._to_float(row.get(metric_name))
                if value is not None:
                    metrics.append(
                        DqcMetric(
                            layer="dws",
                            domain=domain,
                            suite_name=suite_name,
                            table_name=table_name,
                            as_of_date=as_of_date,
                            trade_date=trade_date,
                            metric_scope="table",
                            entity_name="__table__",
                            metric_name=metric_name,
                            metric_value=value,
                        )
                    )

        numeric_columns = self._dws_numeric_columns(table_name)
        if not numeric_columns:
            return metrics

        stats_frames = []
        # Matrix tables have many factor columns; batching avoids ClickHouse max_query_size parser failures.
        for column_chunk in self._chunks(numeric_columns, 40):
            stats_sql = "\nUNION ALL\n".join(
                [
                    f"""
                    SELECT
                        trade_date,
                        '{column}' AS entity_name,
                        count() AS row_count,
                        count(`{column}`) AS non_null_count,
                        if(count() = 0, 0, countIf(isNull(`{column}`)) / count()) AS null_ratio,
                        if(count(`{column}`) = 0, 0, countIf(isNotNull(`{column}`) AND assumeNotNull(`{column}`) = 0)
                            / count(`{column}`)) AS zero_ratio,
                        avg(`{column}`) AS mean,
                        stddevSamp(`{column}`) AS stddev,
                        min(`{column}`) AS min,
                        max(`{column}`) AS max,
                        quantileTDigest(0.01)(`{column}`) AS q01,
                        quantileTDigest(0.05)(`{column}`) AS q05,
                        quantileTDigest(0.50)(`{column}`) AS q50,
                        quantileTDigest(0.95)(`{column}`) AS q95,
                        quantileTDigest(0.99)(`{column}`) AS q99
                    FROM {qualified}
                    WHERE trade_date = {target_trade_date_sql}
                    GROUP BY trade_date
                    """
                    for column in column_chunk
                ]
            )
            stats_frames.append(self.get_db_engine().query_df(stats_sql))
        non_empty_stats = [frame for frame in stats_frames if not frame.empty]
        if not non_empty_stats:
            return metrics
        stats_df = pd.concat(non_empty_stats, ignore_index=True)
        if stats_df.empty:
            return metrics
        metric_names = [
            "row_count",
            "non_null_count",
            "null_ratio",
            "zero_ratio",
            "mean",
            "stddev",
            "min",
            "max",
            "q01",
            "q05",
            "q50",
            "q95",
            "q99",
        ]
        for row in stats_df.to_dict("records"):
            for metric_name in metric_names:
                value = self._to_float(row.get(metric_name))
                if value is None:
                    continue
                metrics.append(
                    DqcMetric(
                        layer="dws",
                        domain=domain,
                        suite_name=suite_name,
                        table_name=table_name,
                        as_of_date=as_of_date,
                        trade_date=row["trade_date"],
                        metric_scope="column",
                        entity_name=row["entity_name"],
                        metric_name=metric_name,
                        metric_value=value,
                    )
                )
        return metrics

    def _dws_drift_results(
        self,
        domain: str,
        suite_name: str,
        table_name: str,
        as_of_date: datetime.date,
        metrics: list[DqcMetric],
    ) -> list[DqcResult]:
        drift_metric_names = {"row_count", "instrument_count", "null_ratio", "zero_ratio", "mean", "stddev", "q50"}
        current = [
            metric
            for metric in metrics
            if metric.metric_name in drift_metric_names and metric.metric_scope in {"table", "column"}
        ]
        if not current:
            return [
                self._dqc_result(
                    domain,
                    suite_name,
                    table_name,
                    "dqc_drift_current_metrics_available",
                    "statistical",
                    "drift",
                    "WARN",
                    1,
                    message="No current metrics were generated for drift evaluation",
                )
            ]

        metric_name_sql = ", ".join([f"'{name}'" for name in sorted(drift_metric_names)])
        db_name = self.settings.database.db_name
        baseline_df = self.get_db_engine().query_df(
            f"""
            SELECT
                metric_scope,
                entity_name,
                metric_name,
                countDistinct(as_of_date) AS baseline_days,
                avg(metric_value) AS baseline_mean,
                stddevSamp(metric_value) AS baseline_std
            FROM {db_name}.dq_dqc_metric
            WHERE layer = 'dws'
              AND domain = '{domain}'
              AND suite_name = '{suite_name}'
              AND table_name = '{table_name}'
              AND as_of_date < {self._sql_date(as_of_date)}
              AND as_of_date >= {self._sql_date(as_of_date - datetime.timedelta(days=self.settings.quality.dqc_baseline_window_days))}
              AND metric_name IN ({metric_name_sql})
            GROUP BY metric_scope, entity_name, metric_name
            """
        )
        if baseline_df.empty:
            return [
                self._dqc_result(
                    domain,
                    suite_name,
                    table_name,
                    "dqc_drift_baseline_warmup",
                    "statistical",
                    "drift",
                    "MONITOR",
                    0,
                    checked_count=len(current),
                    message="No historical DQC baseline exists yet",
                    status="MONITOR",
                )
            ]

        baseline = {
            (row["metric_scope"], row["entity_name"], row["metric_name"]): row
            for row in baseline_df.to_dict("records")
        }
        min_days = self.settings.quality.dqc_min_baseline_days
        z_threshold = 5.0
        relative_thresholds = {
            "row_count": 0.2,
            "instrument_count": 0.2,
            "null_ratio": 0.1,
            "zero_ratio": 0.2,
        }
        insufficient = 0
        drifted: list[tuple[DqcMetric, dict[str, Any], float | None]] = []
        for metric in current:
            key = (metric.metric_scope, metric.entity_name, metric.metric_name)
            row = baseline.get(key)
            if row is None or int(row.get("baseline_days") or 0) < min_days:
                insufficient += 1
                continue
            baseline_mean = self._to_float(row.get("baseline_mean"))
            baseline_std = self._to_float(row.get("baseline_std"))
            z_score = None
            drift = False
            if baseline_std and baseline_std > 0:
                z_score = (metric.metric_value - float(baseline_mean or 0)) / baseline_std
                drift = abs(z_score) > z_threshold
            relative_threshold = relative_thresholds.get(metric.metric_name)
            if relative_threshold is not None and baseline_mean not in (None, 0):
                relative_change = abs(metric.metric_value - baseline_mean) / abs(baseline_mean)
                drift = drift or relative_change > relative_threshold
            if drift:
                drifted.append((metric, row, z_score))

        results = [
            self._dqc_result(
                domain,
                suite_name,
                table_name,
                "dqc_metric_drift",
                "statistical",
                "drift",
                "WARN",
                len(drifted),
                checked_count=len(current) - insufficient,
                message=f"{len(drifted)} metrics drifted beyond threshold",
            )
        ]
        if insufficient:
            results.append(
                self._dqc_result(
                    domain,
                    suite_name,
                    table_name,
                    "dqc_drift_baseline_warmup",
                    "statistical",
                    "drift",
                    "MONITOR",
                    0,
                    checked_count=insufficient,
                    message=f"{insufficient} metrics do not have {min_days} baseline days yet",
                    status="MONITOR",
                )
            )
        if drifted:
            metric, row, z_score = drifted[0]
            results.append(
                self._dqc_result(
                    domain,
                    suite_name,
                    table_name,
                    f"dqc_metric_drift_example.{metric.entity_name}.{metric.metric_name}"[:160],
                    "statistical",
                    "drift_detail",
                    "MONITOR",
                    0,
                    checked_count=1,
                    observed_value=metric.metric_value,
                    baseline_mean=self._to_float(row.get("baseline_mean")),
                    baseline_std=self._to_float(row.get("baseline_std")),
                    z_score=z_score,
                    message="Example drifted metric for alert triage",
                    status="MONITOR",
                )
            )
        return results

    def _dws_consistency_checks(
        self,
        domain: str,
        suite_name: str,
        as_of_date: datetime.date,
    ) -> tuple[list[DqcResult], list[DqcConsistency], list[DqcSample]]:
        db_name = self.settings.database.db_name
        wide = QualityManager._quote_table(db_name, "dws_stock_factor_wide")
        matrix = QualityManager._quote_table(db_name, "dws_stock_factor_wide_matrix")
        target_trade_date_sql = self._target_trade_date_sql(as_of_date).format(db_name=db_name)
        samples: list[DqcSample] = []

        counts = self._query_first_record(
            f"""
            WITH
                {target_trade_date_sql} AS target_trade_date,
                (SELECT count() FROM {wide} WHERE trade_date = target_trade_date) AS wide_rows,
                (SELECT count() FROM {matrix} WHERE trade_date = target_trade_date) AS matrix_rows,
                (SELECT uniqExact(instrument_id) FROM {wide} WHERE trade_date = target_trade_date) AS wide_instruments,
                (SELECT uniqExact(instrument_id) FROM {matrix} WHERE trade_date = target_trade_date) AS matrix_instruments,
                (
                    SELECT count()
                    FROM {wide}
                    WHERE trade_date = target_trade_date
                      AND (instrument_id, trade_date) NOT IN (
                          SELECT instrument_id, trade_date FROM {matrix} WHERE trade_date = target_trade_date
                      )
                ) AS missing_in_matrix,
                (
                    SELECT count()
                    FROM {matrix}
                    WHERE trade_date = target_trade_date
                      AND (instrument_id, trade_date) NOT IN (
                          SELECT instrument_id, trade_date FROM {wide} WHERE trade_date = target_trade_date
                      )
                ) AS missing_in_wide
            SELECT
                target_trade_date AS trade_date,
                wide_rows,
                matrix_rows,
                wide_instruments,
                matrix_instruments,
                missing_in_matrix,
                missing_in_wide
            """
        )
        trade_date = counts.get("trade_date") or as_of_date
        wide_rows = float(counts.get("wide_rows") or 0)
        matrix_rows = float(counts.get("matrix_rows") or 0)
        wide_instruments = float(counts.get("wide_instruments") or 0)
        matrix_instruments = float(counts.get("matrix_instruments") or 0)
        missing_in_matrix = int(counts.get("missing_in_matrix") or 0)
        missing_in_wide = int(counts.get("missing_in_wide") or 0)
        row_ratio = self._safe_ratio(matrix_rows, wide_rows)
        instrument_ratio = self._safe_ratio(matrix_instruments, wide_instruments)

        consistencies = [
            DqcConsistency(
                "dws",
                domain,
                suite_name,
                "dws_stock_factor_wide",
                "dws_stock_factor_wide_matrix",
                as_of_date,
                trade_date,
                "row_count_ratio",
                wide_rows,
                matrix_rows,
                row_ratio,
                "PASS" if row_ratio == 1 else "FAIL",
            ),
            DqcConsistency(
                "dws",
                domain,
                suite_name,
                "dws_stock_factor_wide",
                "dws_stock_factor_wide_matrix",
                as_of_date,
                trade_date,
                "instrument_count_ratio",
                wide_instruments,
                matrix_instruments,
                instrument_ratio,
                "PASS" if instrument_ratio == 1 else "FAIL",
            ),
        ]
        results = [
            self._dqc_result(
                domain,
                suite_name,
                "dws_stock_factor_wide,dws_stock_factor_wide_matrix",
                "dqc_dws_factor_primary_key_consistency",
                "consistency",
                "primary_key",
                "BLOCKER",
                missing_in_matrix + missing_in_wide,
                checked_count=int(wide_rows + matrix_rows),
                message="Wide and matrix tables must contain the same (instrument_id, trade_date) keys",
            ),
            self._dqc_result(
                domain,
                suite_name,
                "dws_stock_factor_wide,dws_stock_factor_wide_matrix",
                "dqc_dws_factor_row_ratio",
                "consistency",
                "row_ratio",
                "BLOCKER",
                0 if row_ratio == 1 else 1,
                checked_count=1,
                observed_value=row_ratio,
                expected_min=1,
                expected_max=1,
                message="Matrix row count should equal wide row count for the target trade date",
            ),
            self._dqc_result(
                domain,
                suite_name,
                "dws_stock_factor_wide,dws_stock_factor_wide_matrix",
                "dqc_dws_factor_instrument_ratio",
                "consistency",
                "instrument_ratio",
                "BLOCKER",
                0 if instrument_ratio == 1 else 1,
                checked_count=1,
                observed_value=instrument_ratio,
                expected_min=1,
                expected_max=1,
                message="Matrix instrument count should equal wide instrument count for the target trade date",
            ),
        ]
        samples.extend(
            self._missing_key_samples(
                domain,
                suite_name,
                as_of_date,
                target_trade_date_sql,
                "dws_stock_factor_wide",
                "dws_stock_factor_wide_matrix",
                "missing_in_matrix",
            )
        )
        samples.extend(
            self._missing_key_samples(
                domain,
                suite_name,
                as_of_date,
                target_trade_date_sql,
                "dws_stock_factor_wide_matrix",
                "dws_stock_factor_wide",
                "missing_in_wide",
            )
        )
        return results, consistencies, samples

    def _missing_key_samples(
        self,
        domain: str,
        suite_name: str,
        as_of_date: datetime.date,
        target_trade_date_sql: str,
        source_table: str,
        target_table: str,
        sample_type: str,
    ) -> list[DqcSample]:
        if self.settings.quality.max_samples <= 0:
            return []
        db_name = self.settings.database.db_name
        source = QualityManager._quote_table(db_name, source_table)
        target = QualityManager._quote_table(db_name, target_table)
        df = self.get_db_engine().query_df(
            f"""
            SELECT instrument_id, trade_date, source_code
            FROM {source}
            WHERE trade_date = {target_trade_date_sql}
              AND (instrument_id, trade_date) NOT IN (
                  SELECT instrument_id, trade_date FROM {target} WHERE trade_date = {target_trade_date_sql}
              )
            ORDER BY sipHash64(instrument_id, trade_date)
            LIMIT {self.settings.quality.max_samples}
            """
        )
        return [
            DqcSample(
                layer="dws",
                domain=domain,
                suite_name=suite_name,
                table_name=source_table,
                rule_id="dqc_dws_factor_primary_key_consistency",
                as_of_date=as_of_date,
                trade_date=row["trade_date"],
                instrument_id=str(row.get("instrument_id") or ""),
                entity_name="primary_key",
                sample_type=sample_type,
                sample_json=json.dumps(row, ensure_ascii=False, default=str),
            )
            for row in df.to_dict("records")
        ]

    def _dws_spot_samples(
        self,
        domain: str,
        suite_name: str,
        table_name: str,
        as_of_date: datetime.date,
    ) -> list[DqcSample]:
        sample_count = self.settings.quality.dqc_spot_check_samples
        if sample_count <= 0:
            return []
        db_name = self.settings.database.db_name
        qualified = QualityManager._quote_table(db_name, table_name)
        target_trade_date_sql = self._target_trade_date_sql(as_of_date).format(db_name=db_name)
        numeric_columns = self._dws_numeric_columns(table_name)
        if not numeric_columns:
            return []
        entity_expr = "arrayElement(" + str(numeric_columns) + ", 1 + modulo(sipHash64(instrument_id), " + str(len(numeric_columns)) + "))"
        df = self.get_db_engine().query_df(
            f"""
            SELECT
                instrument_id,
                trade_date,
                source_code,
                {entity_expr} AS entity_name
            FROM {qualified}
            WHERE trade_date = {target_trade_date_sql}
            ORDER BY sipHash64(instrument_id, trade_date, '{table_name}')
            LIMIT {sample_count}
            """
        )
        return [
            DqcSample(
                layer="dws",
                domain=domain,
                suite_name=suite_name,
                table_name=table_name,
                rule_id="dqc_deterministic_spot_check",
                as_of_date=as_of_date,
                trade_date=row["trade_date"],
                instrument_id=str(row.get("instrument_id") or ""),
                entity_name=str(row.get("entity_name") or ""),
                sample_type="spot_check",
                sample_json=json.dumps(row, ensure_ascii=False, default=str),
            )
            for row in df.to_dict("records")
        ]

    def _record_run(self, run: DqcRun) -> None:
        try:
            if self.settings.quality.dqc_create_result_tables:
                self.ensure_result_tables()
            schemas = self._metadata_table_schemas()
            db_engine = self.get_db_engine()
            db_engine.insert(
                "dq_dqc_run",
                schemas["dq_dqc_run"],
                pd.DataFrame(
                    [
                        {
                            "run_id": run.run_id,
                            "layer": run.layer,
                            "domain": run.domain,
                            "suite_name": run.suite_name,
                            "table_name": run.table_name,
                            "as_of_date": run.as_of_date,
                            "mode": run.mode,
                            "status": run.status,
                            "started_at": run.started_at,
                            "finished_at": run.finished_at,
                            "baseline_window_days": run.baseline_window_days,
                        }
                    ]
                ),
            )
            if run.results:
                db_engine.insert(
                    "dq_dqc_result",
                    schemas["dq_dqc_result"],
                    pd.DataFrame(
                        [
                            {
                                **result.__dict__,
                                "run_id": run.run_id,
                                "created_at": run.finished_at,
                            }
                            for result in run.results
                        ]
                    ),
                )
            if run.metrics:
                db_engine.insert(
                    "dq_dqc_metric",
                    schemas["dq_dqc_metric"],
                    pd.DataFrame(
                        [
                            {
                                **metric.__dict__,
                                "run_id": run.run_id,
                                "created_at": run.finished_at,
                            }
                            for metric in run.metrics
                        ]
                    ),
                )
            if run.consistencies:
                db_engine.insert(
                    "dq_dqc_consistency",
                    schemas["dq_dqc_consistency"],
                    pd.DataFrame(
                        [
                            {
                                **consistency.__dict__,
                                "run_id": run.run_id,
                                "created_at": run.finished_at,
                            }
                            for consistency in run.consistencies
                        ]
                    ),
                )
            if run.samples:
                db_engine.insert(
                    "dq_dqc_sample",
                    schemas["dq_dqc_sample"],
                    pd.DataFrame(
                        [
                            {
                                **sample.__dict__,
                                "run_id": run.run_id,
                                "created_at": run.finished_at,
                            }
                            for sample in run.samples
                        ]
                    ),
                )
        except Exception:
            logging.exception("Failed to record DQC run %s", run.run_id)

    @staticmethod
    def run_to_json(run: DqcRun) -> str:
        return json.dumps(
            {
                "run_id": run.run_id,
                "layer": run.layer,
                "domain": run.domain,
                "suite_name": run.suite_name,
                "table_name": run.table_name,
                "as_of_date": run.as_of_date,
                "mode": run.mode,
                "status": run.status,
                "result_count": len(run.results),
                "metric_count": len(run.metrics),
                "consistency_count": len(run.consistencies),
                "sample_count": len(run.samples),
                "failed_results": [result.__dict__ for result in run.results if result.status == "FAIL"],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
