from __future__ import annotations
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from tushare_integration.db_engine import DatabaseEngineFactory
from tushare_integration.quality import QualityManager, ValidationMode
from tushare_integration.settings import TushareIntegrationSettings


ROOT_DIR = Path(__file__).resolve().parent.parent
DWD_SCHEMA_DIR = ROOT_DIR / "tushare_integration" / "schema" / "dwd"
ODS_SCHEMA_DIR = ROOT_DIR / "tushare_integration" / "schema"
FAR_FUTURE_TS_SQL = "toDateTime64('9999-12-31 00:00:00', 3)"
# Date32上限约2299-12-31,9999会被静默截断,故区间右端哨兵用Date32可表达的远期日
FAR_FUTURE_DATE_SQL = "toDate32('2299-12-31')"
CALENDAR_SOURCE_TABLE = "trade_cal"
MIN_LAYER_TRADE_DATE = "2010-01-01"
MIN_LAYER_TRADE_DATE_SQL = f"toDate32('{MIN_LAYER_TRADE_DATE}')"


COMMON_DWD_COLUMNS = [
    {"name": "instrument_id", "data_type": "str", "length": 64, "comment": "统一证券ID"},
    {"name": "instrument_type", "data_type": "str", "length": 32, "comment": "证券类型"},
    {"name": "exchange", "data_type": "str", "length": 32, "comment": "交易所"},
    {"name": "source_code", "data_type": "str", "length": 64, "comment": "源侧证券代码"},
    {"name": "event_date", "data_type": "date", "comment": "业务归属日期"},
    {"name": "available_trade_date", "data_type": "date", "comment": "最早可用交易日"},
    {"name": "sys_from", "data_type": "datetime", "comment": "版本开始时间"},
    {"name": "sys_to", "data_type": "datetime", "comment": "版本结束时间"},
    {"name": "source", "data_type": "str", "length": 32, "comment": "来源系统"},
    {"name": "source_table", "data_type": "str", "length": 64, "comment": "来源表"},
    {"name": "source_batch_id", "data_type": "str", "length": 64, "comment": "来源批次ID"},
    {"name": "source_record_hash", "data_type": "str", "length": 32, "comment": "来源记录哈希"},
]

COMMON_DWD_COLUMNS_NO_INSTRUMENT = [
    {"name": "event_date", "data_type": "date", "comment": "业务归属日期"},
    {"name": "available_trade_date", "data_type": "date", "comment": "最早可用交易日"},
    {"name": "sys_from", "data_type": "datetime", "comment": "版本开始时间"},
    {"name": "sys_to", "data_type": "datetime", "comment": "版本结束时间"},
    {"name": "source", "data_type": "str", "length": 32, "comment": "来源系统"},
    {"name": "source_table", "data_type": "str", "length": 64, "comment": "来源表"},
    {"name": "source_batch_id", "data_type": "str", "length": 64, "comment": "来源批次ID"},
    {"name": "source_record_hash", "data_type": "str", "length": 32, "comment": "来源记录哈希"},
]


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f.read())


def _quote_column(name: str) -> str:
    return f"`{name}`"


def _nullable_copy(column: dict[str, Any]) -> dict[str, Any]:
    copied_column = deepcopy(column)
    copied_column["nullable"] = True
    copied_column.pop("default", None)
    return copied_column


def _source_column_copy(column: dict[str, Any], business_key: set[str]) -> dict[str, Any]:
    if column["name"] not in business_key:
        return _nullable_copy(column)

    copied_column = deepcopy(column)
    copied_column.pop("nullable", None)
    return copied_column


def _schema_has_column(schema: dict[str, Any], column_name: str) -> bool:
    return any(column["name"] == column_name for column in schema.get("columns", []))


class DWDManager:
    def __init__(self):
        self.settings = TushareIntegrationSettings.model_validate(
            yaml.safe_load(open("config.yaml", "r", encoding="utf-8").read())
        )
        self.db_engine = None

    def get_db_engine(self):
        if self.db_engine is None:
            self.db_engine = DatabaseEngineFactory.create(self.settings)
        return self.db_engine

    def list_tables(self) -> list[str]:
        table_names = []
        for path in sorted(DWD_SCHEMA_DIR.glob("*.yaml")):
            spec = _load_yaml(path)
            table_names.append(spec["name"])
        return table_names

    def load_spec(self, table_name: str) -> dict[str, Any]:
        for path in DWD_SCHEMA_DIR.glob("*.yaml"):
            spec = _load_yaml(path)
            if spec["name"] == table_name:
                return spec
        raise ValueError(f"DWD table {table_name} not found")

    def load_source_schema(self, schema_name: str) -> dict[str, Any]:
        return _load_yaml(ODS_SCHEMA_DIR / f"{schema_name}.yaml")

    def _build_common_columns(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        common_columns = (
            COMMON_DWD_COLUMNS if spec.get("with_instrument", True) else COMMON_DWD_COLUMNS_NO_INSTRUMENT
        )
        extra_columns = [_nullable_copy(column) for column in spec.get("extra_columns", [])]
        return common_columns + extra_columns

    def build_schema(self, spec: dict[str, Any]) -> dict[str, Any]:
        builder = spec.get("builder", "raw_versioned")
        if builder == "security_master":
            schema = deepcopy(spec["schema"])
            schema["primary_key"] = []
            return schema
        if builder == "business_interval":
            # 业务时间轴驱动:schema在spec中显式声明,主键含业务时间维度(如in_date),
            # 不清空primary_key —— ClickHouse ORDER BY需保留in_date避免折叠历史进出。
            schema = deepcopy(spec["schema"])
            schema["partition_key"] = spec.get("partition_key", [])
            schema["indexes"] = spec.get("indexes", [])
            return schema

        source_schema = self.load_source_schema(spec["source"]["schema_name"])
        business_key = set(spec.get("business_key") or source_schema.get("primary_key", []))
        nullable_business_key = set(spec.get("nullable_business_key", []))
        source_column_excludes = set(spec.get("source_column_excludes", []))
        source_columns = [
            _nullable_copy(column)
            if column["name"] in nullable_business_key
            else _source_column_copy(column, business_key)
            for column in source_schema["columns"]
            if column["name"] not in source_column_excludes
        ]
        common_columns = self._build_common_columns(spec)

        return {
            "comment": spec["comment"],
            "primary_key": [],
            "partition_key": spec["partition_key"],
            "indexes": spec["indexes"],
            "columns": source_columns + common_columns,
        }

    def _calendar_map_sql(self) -> str:
        db_name = self.settings.database.db_name
        return f"""
calendar_map AS (
    SELECT
        c.cal_date AS calendar_date,
        min(o.cal_date) AS next_trade_date
    FROM {db_name}.{CALENDAR_SOURCE_TABLE} c
    LEFT JOIN {db_name}.{CALENDAR_SOURCE_TABLE} o
        ON o.exchange = c.exchange
       AND o.is_open = 1
       AND o.cal_date > c.cal_date
    WHERE c.exchange = 'SSE'
    GROUP BY c.cal_date
)"""

    def _render_generic_sync_sql(self, spec: dict[str, Any], target_table_name: str) -> str:
        db_name = self.settings.database.db_name
        source_alias = spec.get("source_alias", "src")
        source_schema = self.load_source_schema(spec["source"]["schema_name"])
        business_key = spec.get("business_key") or source_schema.get("primary_key", [])
        if not business_key:
            raise ValueError(f"{spec['name']} requires business_key or source primary_key")
        nullable_business_key = set(spec.get("nullable_business_key", []))

        source_column_excludes = set(spec.get("source_column_excludes", []))
        source_columns = [
            column["name"]
            for column in source_schema["columns"]
            if column["name"] not in source_column_excludes
        ]
        business_key_partition = ", ".join([f"{source_alias}.{_quote_column(column)}" for column in business_key])
        source_filters = [
            f"{source_alias}.{_quote_column(column)} IS NOT NULL"
            for column in business_key
            if column not in nullable_business_key
        ]
        if _schema_has_column(source_schema, "trade_date"):
            source_filters.append(f"{source_alias}.`trade_date` >= {MIN_LAYER_TRADE_DATE_SQL}")
        for extra_filter in spec.get("source_filters", []):
            source_filters.append(f"({extra_filter})")
        source_filter_sql = " AND ".join(source_filters)
        source_column_select = ",\n    ".join([f"{source_alias}.{_quote_column(column)}" for column in source_columns])

        derived_selects: list[str] = []
        if spec.get("with_instrument", True):
            derived_selects.extend(
                [
                    f"{spec['instrument_id_expr']} AS `instrument_id`",
                    f"'{spec['instrument_type']}' AS `instrument_type`",
                    f"{spec['exchange_expr']} AS `exchange`",
                    f"{spec['source_code_expr']} AS `source_code`",
                ]
            )

        derived_selects.extend(
            [
                f"{spec['event_date_expr']} AS `event_date`",
                f"{spec['available_trade_date_expr']} AS `available_trade_date`",
                f"{source_alias}._ingest_time AS `sys_from`",
                f"{source_alias}._next_sys_from AS `sys_to`",
                f"{source_alias}._source AS `source`",
                f"'{spec['source']['table_name']}' AS `source_table`",
                f"{source_alias}._batch_id AS `source_batch_id`",
                f"{source_alias}._record_hash AS `source_record_hash`",
            ]
        )

        for column in spec.get("extra_columns", []):
            derived_selects.append(f"{column['expr']} AS `{column['name']}`")

        derived_column_select = ",\n    ".join(derived_selects)
        with_items = []
        if spec.get("calendar_date_expr"):
            with_items.append(self._calendar_map_sql())

        with_item_sql = ",\n".join(with_items)
        with_clause = f"WITH\n{with_item_sql}" if with_items else ""
        calendar_join = (
            f"LEFT JOIN calendar_map ON calendar_map.calendar_date = {source_alias}._calendar_lookup_date"
            if spec.get("calendar_date_expr")
            else ""
        )
        calendar_lookup_select = (
            f",\n        {spec['calendar_date_expr']} AS _calendar_lookup_date" if spec.get("calendar_date_expr") else ""
        )

        return f"""
INSERT INTO {db_name}.{target_table_name}
{with_clause}
SELECT
    {source_column_select},
    {derived_column_select}
FROM (
    SELECT
        {source_alias}.*,
        leadInFrame({source_alias}._ingest_time, 1, {FAR_FUTURE_TS_SQL}) OVER (
            PARTITION BY {business_key_partition}
            ORDER BY {source_alias}._ingest_time, {source_alias}._batch_id, {source_alias}._record_hash
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS _next_sys_from
        {calendar_lookup_select}
    FROM (
        SELECT
            {source_alias}.*,
            lagInFrame({source_alias}._record_hash) OVER (
                PARTITION BY {business_key_partition}
                ORDER BY {source_alias}._ingest_time, {source_alias}._batch_id, {source_alias}._record_hash
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
            ) AS _prev_record_hash
        FROM {db_name}.{spec['source']['table_name']} {source_alias}
        WHERE {source_filter_sql}
    ) {source_alias}
    WHERE {source_alias}._prev_record_hash IS NULL OR {source_alias}._prev_record_hash != {source_alias}._record_hash
) {source_alias}
{calendar_join}
"""

    def _render_security_master_sync_sql(self, spec: dict[str, Any], target_table_name: str) -> str:
        db_name = self.settings.database.db_name
        return f"""
INSERT INTO {db_name}.{target_table_name}
WITH
{self._calendar_map_sql()},
security_union AS (
    SELECT
        concat('stock:', src.ts_code) AS instrument_id,
        'stock' AS instrument_type,
        src.exchange AS exchange,
        src.ts_code AS source_code,
        src.symbol AS symbol,
        src.name AS instrument_name,
        src.fullname AS full_name,
        src.enname AS english_name,
        src.market AS market,
        CAST(NULL, 'Nullable(String)') AS category,
        CAST(NULL, 'Nullable(String)') AS publisher,
        src.curr_type AS currency,
        src.list_status AS list_status,
        src.list_date AS list_date,
        src.delist_date AS delist_date,
        src.area AS area,
        src.industry AS industry,
        src.is_hs AS is_hs,
        CAST(NULL, 'Nullable(String)') AS underlying_code,
        CAST(NULL, 'Nullable(Float64)') AS contract_multiplier,
        CAST(NULL, 'Nullable(String)') AS trade_unit,
        CAST(NULL, 'Nullable(String)') AS quote_unit,
        coalesce(src.list_date, toDate(src._ingest_time)) AS event_date,
        coalesce(src.list_date, calendar_map.next_trade_date, toDate(src._ingest_time)) AS available_trade_date,
        src._ingest_time AS sys_from,
        src._source AS source,
        'stock_basic_raw' AS source_table,
        src._batch_id AS source_batch_id,
        src._record_hash AS source_record_hash
    FROM {db_name}.stock_basic_raw src
    LEFT JOIN calendar_map ON calendar_map.calendar_date = toDate(src._ingest_time)
    WHERE src.ts_code IS NOT NULL

    UNION ALL

        SELECT
            concat('index:', src.ts_code) AS instrument_id,
            'index' AS instrument_type,
            arrayElement(splitByChar('.', assumeNotNull(src.ts_code)), 2) AS exchange,
            src.ts_code AS source_code,
            CAST(NULL, 'Nullable(String)') AS symbol,
            src.name AS instrument_name,
        src.fullname AS full_name,
        CAST(NULL, 'Nullable(String)') AS english_name,
        src.market AS market,
        src.category AS category,
        src.publisher AS publisher,
        CAST(NULL, 'Nullable(String)') AS currency,
        CAST(NULL, 'Nullable(String)') AS list_status,
        src.list_date AS list_date,
        src.exp_date AS delist_date,
        CAST(NULL, 'Nullable(String)') AS area,
        CAST(NULL, 'Nullable(String)') AS industry,
        CAST(NULL, 'Nullable(String)') AS is_hs,
        CAST(NULL, 'Nullable(String)') AS underlying_code,
        CAST(NULL, 'Nullable(Float64)') AS contract_multiplier,
        CAST(NULL, 'Nullable(String)') AS trade_unit,
        CAST(NULL, 'Nullable(String)') AS quote_unit,
        coalesce(src.list_date, toDate(src._ingest_time)) AS event_date,
        coalesce(src.list_date, calendar_map.next_trade_date, toDate(src._ingest_time)) AS available_trade_date,
        src._ingest_time AS sys_from,
        src._source AS source,
        'index_basic_raw' AS source_table,
        src._batch_id AS source_batch_id,
        src._record_hash AS source_record_hash
    FROM {db_name}.index_basic_raw src
    LEFT JOIN calendar_map ON calendar_map.calendar_date = toDate(src._ingest_time)
    WHERE src.ts_code IS NOT NULL

    UNION ALL

    SELECT
        concat('future:', src.ts_code) AS instrument_id,
        'future' AS instrument_type,
        src.exchange AS exchange,
        src.ts_code AS source_code,
        src.symbol AS symbol,
        src.name AS instrument_name,
        CAST(NULL, 'Nullable(String)') AS full_name,
        CAST(NULL, 'Nullable(String)') AS english_name,
        CAST(NULL, 'Nullable(String)') AS market,
        CAST(NULL, 'Nullable(String)') AS category,
        CAST(NULL, 'Nullable(String)') AS publisher,
        CAST(NULL, 'Nullable(String)') AS currency,
        CAST(NULL, 'Nullable(String)') AS list_status,
        src.list_date AS list_date,
        src.delist_date AS delist_date,
        CAST(NULL, 'Nullable(String)') AS area,
        CAST(NULL, 'Nullable(String)') AS industry,
        CAST(NULL, 'Nullable(String)') AS is_hs,
        src.fut_code AS underlying_code,
        src.multiplier AS contract_multiplier,
        src.trade_unit AS trade_unit,
        src.quote_unit AS quote_unit,
        coalesce(src.list_date, toDate(src._ingest_time)) AS event_date,
        coalesce(src.list_date, calendar_map.next_trade_date, toDate(src._ingest_time)) AS available_trade_date,
        src._ingest_time AS sys_from,
        src._source AS source,
        'fut_basic_raw' AS source_table,
        src._batch_id AS source_batch_id,
        src._record_hash AS source_record_hash
    FROM {db_name}.fut_basic_raw src
    LEFT JOIN calendar_map ON calendar_map.calendar_date = toDate(src._ingest_time)
    WHERE src.ts_code IS NOT NULL
),
versioned AS (
    SELECT
        src.*,
        leadInFrame(src.sys_from, 1, {FAR_FUTURE_TS_SQL}) OVER (
            PARTITION BY src.instrument_id
            ORDER BY src.sys_from, src.source_batch_id, src.source_record_hash
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS sys_to
    FROM (
        SELECT
            src.*,
            lagInFrame(src.source_record_hash) OVER (
                PARTITION BY src.instrument_id
                ORDER BY src.sys_from, src.source_batch_id, src.source_record_hash
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
            ) AS prev_record_hash
        FROM security_union src
    ) src
    WHERE src.prev_record_hash IS NULL OR src.prev_record_hash != src.source_record_hash
)
SELECT
    instrument_id,
    instrument_type,
    exchange,
    source_code,
    symbol,
    instrument_name,
    full_name,
    english_name,
    market,
    category,
    publisher,
    currency,
    list_status,
    list_date,
    delist_date,
    area,
    industry,
    is_hs,
    underlying_code,
    contract_multiplier,
    trade_unit,
    quote_unit,
    event_date,
    available_trade_date,
    sys_from,
    sys_to,
    source,
    source_table,
    source_batch_id,
    source_record_hash
FROM versioned
"""

    def _on_or_after_calendar_map_sql(self) -> str:
        # 与_calendar_map_sql不同:这里算 >= 生效日的当日或之后最近交易日(on_or_after),
        # 而_calendar_map_sql算的是严格大于的next_trade_date。语义不可混用。
        # 关键:effective_date枚举全历史日期(而非仅trade_cal内的日期),否则早于
        # 日历起始日(1990-12-19)的in_date会join不到、平移落空。这里对每个in_date
        # 直接算 >= 它的最早交易日;若无(极晚的未来日)则回退in_date本身。
        db_name = self.settings.database.db_name
        return f"""
on_or_after_map AS (
    SELECT
        d.effective_date AS effective_date,
        o.cal_date AS on_or_after_trade_date
    FROM (
        SELECT DISTINCT 1 AS _jk, in_date AS effective_date
        FROM {db_name}.{{source_table}}
        WHERE in_date IS NOT NULL
    ) d
    ASOF LEFT JOIN (
        SELECT 1 AS _jk, cal_date
        FROM {db_name}.{CALENDAR_SOURCE_TABLE}
        WHERE exchange = 'SSE' AND is_open = 1
    ) o
        ON o._jk = d._jk AND o.cal_date >= d.effective_date
)"""

    def _render_business_interval_sync_sql(self, spec: dict[str, Any], target_table_name: str) -> str:
        db_name = self.settings.database.db_name
        source_table = spec["source"]["table_name"]
        business_key = spec.get("business_key") or ["ts_code", "l3_code", "in_date"]
        business_key_partition = ", ".join([_quote_column(column) for column in business_key])

        available_offset = spec.get("available_offset", "on_or_after")
        if available_offset not in ("on_or_after", "next"):
            raise ValueError(f"{spec['name']} unsupported available_offset: {available_offset}")

        if available_offset == "on_or_after":
            calendar_map_sql = self._on_or_after_calendar_map_sql().replace("{source_table}", source_table)
            calendar_join = "LEFT JOIN on_or_after_map ON on_or_after_map.effective_date = d.in_date"
            available_expr = "coalesce(on_or_after_map.on_or_after_trade_date, d.in_date)"
        else:
            calendar_map_sql = self._calendar_map_sql()
            calendar_join = "LEFT JOIN calendar_map ON calendar_map.calendar_date = d.in_date"
            available_expr = "coalesce(calendar_map.next_trade_date, d.in_date)"

        return f"""
INSERT INTO {db_name}.{target_table_name}
WITH
{calendar_map_sql},
dedup AS (
    SELECT *
    FROM (
        SELECT
            src.*,
            row_number() OVER (
                PARTITION BY {business_key_partition}
                ORDER BY src._ingest_time DESC, src._batch_id DESC, src._record_hash DESC
            ) AS _rn
        FROM {db_name}.{source_table} src
        WHERE src.ts_code IS NOT NULL
          AND src.l3_code IS NOT NULL
          AND src.in_date IS NOT NULL
    ) src
    WHERE src._rn = 1
)
SELECT
    d.ts_code,
    d.name,
    d.l1_code,
    d.l1_name,
    d.l2_code,
    d.l2_name,
    d.l3_code,
    d.l3_name,
    d.in_date,
    d.in_date AS event_date,
    {available_expr} AS available_date,
    if(d.is_new = 'Y', {FAR_FUTURE_DATE_SQL}, d.out_date) AS end_date,
    if(d.is_new = 'Y', 1, 0) AS is_current,
    d._source AS source,
    '{source_table}' AS source_table,
    d._batch_id AS source_batch_id,
    d._record_hash AS source_record_hash
FROM dedup d
{calendar_join}
"""

    def render_sync_sql(self, table_name: str, target_table_name: str | None = None) -> str:
        spec = self.load_spec(table_name)
        target_table_name = target_table_name or spec["name"]
        builder = spec.get("builder", "raw_versioned")
        if builder == "security_master":
            return self._render_security_master_sync_sql(spec, target_table_name)
        if builder == "business_interval":
            return self._render_business_interval_sync_sql(spec, target_table_name)
        return self._render_generic_sync_sql(spec, target_table_name)

    def get_required_source_tables(self, spec: dict[str, Any]) -> list[str]:
        builder = spec.get("builder", "raw_versioned")
        if builder == "security_master":
            return ["stock_basic_raw", "index_basic_raw", "fut_basic_raw", CALENDAR_SOURCE_TABLE]
        if builder == "business_interval":
            return sorted({spec["source"]["table_name"], CALENDAR_SOURCE_TABLE})

        required_tables = [spec["source"]["table_name"]]
        if spec.get("calendar_date_expr"):
            required_tables.append(CALENDAR_SOURCE_TABLE)
        return sorted(set(required_tables))

    def ensure_source_tables(self, spec: dict[str, Any]) -> None:
        db_name = self.settings.database.db_name
        required_tables = self.get_required_source_tables(spec)
        source_table_list = ", ".join([f"'{table_name}'" for table_name in required_tables])
        existing_tables = self.get_db_engine().query_df(
            f"""
            SELECT name
            FROM system.tables
            WHERE database = '{db_name}'
              AND name IN ({source_table_list})
            """
        )["name"].tolist()

        missing_tables = sorted(set(required_tables) - set(existing_tables))
        if missing_tables:
            raise ValueError(
                f"Missing source tables for {spec['name']}: {', '.join(missing_tables)}. "
                "Run the corresponding ODS ingestion first."
            )

    def create_table(self, table_name: str) -> None:
        spec = self.load_spec(table_name)
        self.get_db_engine().create_table(spec["name"], self.build_schema(spec))

    def _clickhouse_table_exists(self, table_name: str) -> bool:
        db_name = self.settings.database.db_name
        result = self.get_db_engine().query_df(
            f"""
            SELECT count() AS table_count
            FROM system.tables
            WHERE database = '{db_name}'
              AND name = '{table_name}'
            """
        )
        return int(result["table_count"].iloc[0]) > 0

    def _replace_clickhouse_table_from_tmp(self, target_table: str, tmp_table: str) -> None:
        db_name = self.settings.database.db_name
        db_engine = self.get_db_engine()
        qualified_target = f"{db_name}.{target_table}"
        qualified_tmp = f"{db_name}.{tmp_table}"

        if not self._clickhouse_table_exists(target_table):
            db_engine.query(f"RENAME TABLE {qualified_tmp} TO {qualified_target}")
            return

        try:
            db_engine.query(f"EXCHANGE TABLES {qualified_target} AND {qualified_tmp}")
        except Exception:
            db_engine.query(f"DROP TABLE IF EXISTS {qualified_target}")
            db_engine.query(f"RENAME TABLE {qualified_tmp} TO {qualified_target}")
        else:
            db_engine.query(f"DROP TABLE IF EXISTS {qualified_tmp}")

    def sync_table(
        self,
        table_name: str,
        validation_mode: ValidationMode | None = None,
        skip_validation: bool = False,
    ) -> None:
        spec = self.load_spec(table_name)
        self.ensure_source_tables(spec)
        target_table = spec["name"]
        tmp_table = f"{target_table}_tmp"
        schema = self.build_schema(spec)
        tmp_schema = deepcopy(schema)
        tmp_schema["comment"] = f"{schema['comment']} TMP"

        db_name = self.settings.database.db_name
        db_engine = self.get_db_engine()
        db_engine.query(f"DROP TABLE IF EXISTS {db_name}.{tmp_table}")
        db_engine.create_table(tmp_table, tmp_schema)
        db_engine.query(self.render_sync_sql(table_name, target_table_name=tmp_table))

        QualityManager(settings=self.settings, db_engine=db_engine).validate_publish(
            layer="dwd",
            table_name=target_table,
            target_table_name=tmp_table,
            stage="pre_dwd_publish",
            mode=validation_mode,
            skip_validation=skip_validation,
        )

        if self.settings.database.db_type == "clickhouse":
            self._replace_clickhouse_table_from_tmp(target_table, tmp_table)
            return

        db_engine.create_table(target_table, schema)
        db_engine.query(f"TRUNCATE TABLE {db_name}.{target_table}")
        db_engine.query(f"INSERT INTO {db_name}.{target_table} SELECT * FROM {db_name}.{tmp_table}")
        db_engine.query(f"DROP TABLE IF EXISTS {db_name}.{tmp_table}")

    def sync_all(
        self,
        validation_mode: ValidationMode | None = None,
        skip_validation: bool = False,
    ) -> None:
        for table_name in self.list_tables():
            self.sync_table(table_name, validation_mode=validation_mode, skip_validation=skip_validation)
