from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

import clickhouse_connect
import pandas as pd

from ricequant_integration.schema import ESTIMATE_DDL, RUN_DDL, STATE_DDL, TABLE_SCHEMAS
from ricequant_integration.settings import DatabaseSettings
from ricequant_integration.specs import DatasetSpec


def quote_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def dataframe_hash(frame: pd.DataFrame, keys: Iterable[str]) -> str:
    if frame.empty:
        return hashlib.md5(b"", usedforsecurity=False).hexdigest()
    ordered = frame.sort_values(list(keys), kind="stable").copy()
    if "_record_hash" in ordered:
        payload = "\n".join(ordered["_record_hash"].astype(str)).encode()
    else:
        payload = ordered.to_json(
            orient="records", date_format="iso", default_handler=str
        ).encode()
    return hashlib.md5(payload, usedforsecurity=False).hexdigest()


@dataclass(frozen=True)
class PublishResult:
    row_count: int
    content_hash: str


class RiceQuantStorage:
    """ClickHouse storage which never relies on background deduplication."""

    def __init__(self, settings: DatabaseSettings, client=None):
        self.database = settings.database
        self.client = client or clickhouse_connect.get_client(
            host=settings.host,
            port=settings.port,
            username=settings.user,
            password=settings.password,
            database=settings.database,
            secure=settings.secure,
            apply_server_timezone=True,
        )

    @property
    def db(self) -> str:
        return f"`{self.database}`"

    def initialize(self) -> None:
        for schema in TABLE_SCHEMAS.values():
            self.client.command(schema.create_sql(self.database))
        self.client.command(STATE_DDL.format(database=self.database))
        self.client.command(RUN_DDL.format(database=self.database))
        self.client.command(ESTIMATE_DDL.format(database=self.database))

    @contextmanager
    def distributed_runner_lock(self, owner: str, stale_after_seconds: int = 86_400):
        """Serialize runners across hosts using atomic ClickHouse DDL.

        A hard crash leaves the tiny Memory table behind. It is considered stale
        after one day, longer than a normal quota-bounded run.
        """
        lock_table = "ricequant_runtime_lock"
        create_sql = (
            f"CREATE TABLE {self.db}.`{lock_table}` "
            "(`owner` String, `acquired_at` DateTime64(6, 'Asia/Shanghai')) ENGINE = Memory"
        )
        try:
            self.client.command(create_sql)
        except Exception as exc:
            status = self.client.query(
                "SELECT count(), if(count() = 0, 0, dateDiff('second', max(metadata_modification_time), now())) "
                "FROM system.tables "
                f"WHERE database = {quote_string(self.database)} AND name = {quote_string(lock_table)}"
            ).first_row
            exists, age_seconds = int(status[0]), int(status[1])
            if not exists or age_seconds <= stale_after_seconds:
                raise RuntimeError(
                    "another RiceQuant runner holds the distributed ClickHouse lock"
                ) from exc
            self.client.command(f"DROP TABLE {self.db}.`{lock_table}`")
            self.client.command(create_sql)
        inserted = False
        try:
            self.client.insert(
                f"{self.database}.{lock_table}",
                [[owner, datetime.now()]],
                column_names=["owner", "acquired_at"],
            )
            inserted = True
            yield
        finally:
            with suppress(Exception):
                current = ""
                if inserted:
                    current = self.client.query(
                        f"SELECT any(owner) FROM {self.db}.`{lock_table}`"
                    ).first_row[0]
                if not inserted or current == owner:
                    self.client.command(f"DROP TABLE {self.db}.`{lock_table}`")

    def insert_frame(self, table: str, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        self.client.insert_df(f"{self.database}.{table}", frame)

    def _validate_unique(self, table: str, keys: tuple[str, ...]) -> None:
        group = ", ".join(f"`{key}`" for key in keys)
        result = self.client.query(
            f"SELECT count() FROM (SELECT {group} FROM {self.db}.`{table}` "
            f"GROUP BY {group} HAVING count() > 1 LIMIT 1)"
        )
        if result.first_row[0] != 0:
            raise ValueError(
                f"duplicate primary key detected in staging table {table}: {keys}"
            )

    def _validate_non_null(self, table: str, keys: tuple[str, ...]) -> None:
        predicate = " OR ".join(f"isNull(`{key}`)" for key in keys)
        result = self.client.query(
            f"SELECT count() FROM {self.db}.`{table}` WHERE {predicate}"
        )
        if result.first_row[0] != 0:
            raise ValueError(
                f"NULL primary key detected in staging table {table}: {keys}"
            )

    def publish_partition(
        self,
        spec: DatasetSpec,
        partition_sql: str,
        frame: pd.DataFrame,
        *,
        replace_keys: tuple[str, ...] | None = None,
        replace_values: tuple[object, ...] | None = None,
        replace_range: tuple[str, date, date] | None = None,
    ) -> PublishResult:
        """Rebuild one final partition and atomically swap it into place.

        ``replace_keys`` selects the subset being refreshed. Other rows already
        in the same ClickHouse partition are copied server-side into staging.
        This makes a one-day incremental update safe for a monthly partition.
        """
        schema = TABLE_SCHEMAS[spec.table]
        stage = f"_rq_stage_{uuid.uuid4().hex}"
        self.client.command(
            f"CREATE TABLE {self.db}.`{stage}` AS {self.db}.`{spec.table}`"
        )
        try:
            if replace_keys and replace_range:
                raise ValueError("use either replace_keys or replace_range")
            if replace_keys:
                if replace_values is None or len(replace_keys) != len(replace_values):
                    raise ValueError(
                        "replace_keys and replace_values must have the same length"
                    )
                keep_predicates = []
                for key, value in zip(replace_keys, replace_values, strict=True):
                    literal = self._literal(value)
                    keep_predicates.append(f"`{key}` != {literal}")
                keep_sql = " OR ".join(keep_predicates)
                self.client.command(
                    f"INSERT INTO {self.db}.`{stage}` SELECT * FROM {self.db}.`{spec.table}` "
                    f"WHERE {schema.partition_by} = {partition_sql} AND ({keep_sql})"
                )
            elif replace_range:
                column, range_start, range_end = replace_range
                if column not in spec.primary_key:
                    raise ValueError(
                        f"replace range column must be in primary key: {column}"
                    )
                self.client.command(
                    f"INSERT INTO {self.db}.`{stage}` SELECT * FROM {self.db}.`{spec.table}` "
                    f"WHERE {schema.partition_by} = {partition_sql} "
                    f"AND NOT (`{column}` BETWEEN {quote_string(str(range_start))} AND {quote_string(str(range_end))})"
                )
            self.insert_frame(stage, frame)
            self._validate_non_null(stage, spec.primary_key)
            self._validate_unique(stage, spec.primary_key)
            wrong_partition = int(
                self.client.query(
                    f"SELECT count() FROM {self.db}.`{stage}` "
                    f"WHERE {schema.partition_by} != {partition_sql}"
                ).first_row[0]
            )
            if wrong_partition:
                raise ValueError(
                    f"staging table {stage} has {wrong_partition} rows outside partition {partition_sql}"
                )
            count = int(
                self.client.query(f"SELECT count() FROM {self.db}.`{stage}`").first_row[
                    0
                ]
            )
            content = self.client.query(
                f"SELECT lower(hex(groupBitXor(cityHash64(_record_hash)))) "
                f"FROM {self.db}.`{stage}`"
            ).first_row[0]
            if count == 0:
                # An empty authoritative response must also remove stale data.
                existing = int(
                    self.client.query(
                        f"SELECT count() FROM {self.db}.`{spec.table}` "
                        f"WHERE {schema.partition_by} = {partition_sql}"
                    ).first_row[0]
                )
                if existing:
                    self.client.command(
                        f"ALTER TABLE {self.db}.`{spec.table}` DROP PARTITION {partition_sql}"
                    )
            else:
                self.client.command(
                    f"ALTER TABLE {self.db}.`{spec.table}` REPLACE PARTITION {partition_sql} "
                    f"FROM {self.db}.`{stage}`"
                )
            return PublishResult(
                row_count=count,
                content_hash=str(content or dataframe_hash(frame, spec.primary_key)),
            )
        finally:
            with suppress(Exception):
                self.client.command(f"DROP TABLE IF EXISTS {self.db}.`{stage}`")

    def prepare_daily_stage(
        self, spec: DatasetSpec, trading_date: date
    ) -> tuple[str, bool]:
        """Create or reopen a persistent per-day stage for resumable downloads."""

        stage = f"{spec.table}_stage_{trading_date:%Y%m%d}"
        existed = bool(
            self.client.query(
                "SELECT count() FROM system.tables "
                f"WHERE database = {quote_string(self.database)} "
                f"AND name = {quote_string(stage)}"
            ).first_row[0]
        )
        self.client.command(
            f"CREATE TABLE IF NOT EXISTS {self.db}.`{stage}` AS {self.db}.`{spec.table}`"
        )
        return stage, existed

    def prepare_partition_stage(
        self, spec: DatasetSpec, stage_suffix: str
    ) -> tuple[str, bool]:
        """Create a resumable stage for a non-daily authoritative partition."""

        safe_suffix = "".join(
            character if character.isalnum() else "_" for character in stage_suffix
        )
        stage = f"{spec.table}_stage_{safe_suffix}"
        existed = bool(
            self.client.query(
                "SELECT count() FROM system.tables "
                f"WHERE database = {quote_string(self.database)} "
                f"AND name = {quote_string(stage)}"
            ).first_row[0]
        )
        self.client.command(
            f"CREATE TABLE IF NOT EXISTS {self.db}.`{stage}` AS {self.db}.`{spec.table}`"
        )
        return stage, existed

    def discard_daily_stage(self, spec: DatasetSpec, trading_date: date) -> None:
        stage = f"{spec.table}_stage_{trading_date:%Y%m%d}"
        self.client.command(f"DROP TABLE IF EXISTS {self.db}.`{stage}`")

    def discard_partition_stage(self, spec: DatasetSpec, stage_suffix: str) -> None:
        """Discard an incomplete non-daily stage whose authority bounds changed."""

        safe_suffix = "".join(
            character if character.isalnum() else "_" for character in stage_suffix
        )
        stage = f"{spec.table}_stage_{safe_suffix}"
        self.client.command(f"DROP TABLE IF EXISTS {self.db}.`{stage}`")

    def replace_daily_stage_batch(
        self,
        spec: DatasetSpec,
        stage: str,
        order_book_ids: list[str],
        frame: pd.DataFrame,
    ) -> None:
        """Replace one authoritative instrument batch inside a daily stage."""

        if not order_book_ids:
            return
        unexpected = (
            set(frame["order_book_id"].dropna().astype(str)) - set(order_book_ids)
            if "order_book_id" in frame
            else set()
        )
        if unexpected:
            raise ValueError(
                f"source returned instruments outside requested batch: {sorted(unexpected)[:5]}"
            )
        if not frame.empty and frame.duplicated(list(spec.primary_key)).any():
            raise ValueError(
                f"duplicate primary key detected in source batch for {spec.name}: {spec.primary_key}"
            )
        identifiers = ", ".join(quote_string(value) for value in order_book_ids)
        self.client.command(
            f"ALTER TABLE {self.db}.`{stage}` DELETE WHERE order_book_id IN ({identifiers}) "
            "SETTINGS mutations_sync = 2"
        )
        self.insert_frame(stage, frame)

    def replace_partition_stage_batch(
        self,
        spec: DatasetSpec,
        stage: str,
        key_column: str,
        requested_values: list[str],
        frame: pd.DataFrame,
    ) -> None:
        """Replace one requested-identifier batch in a persistent stage."""

        if not requested_values:
            return
        if key_column not in spec.primary_key:
            raise ValueError(f"stage batch key must be in primary key: {key_column}")
        unexpected = (
            set(frame[key_column].dropna().astype(str)) - set(requested_values)
            if key_column in frame
            else set()
        )
        if unexpected:
            raise ValueError(
                f"source returned {key_column} values outside requested batch: "
                f"{sorted(unexpected)[:5]}"
            )
        if not frame.empty and frame.duplicated(list(spec.primary_key)).any():
            raise ValueError(
                f"duplicate primary key detected in source batch for {spec.name}: "
                f"{spec.primary_key}"
            )
        values = ", ".join(quote_string(value) for value in requested_values)
        self.client.command(
            f"ALTER TABLE {self.db}.`{stage}` DELETE WHERE `{key_column}` IN ({values}) "
            "SETTINGS mutations_sync = 2"
        )
        self.insert_frame(stage, frame)

    def publish_partition_stage(
        self,
        spec: DatasetSpec,
        stage: str,
        partition_sql: str,
        *,
        allow_empty: bool = True,
    ) -> PublishResult:
        """Validate and atomically publish a completed persistent partition stage."""

        schema = TABLE_SCHEMAS[spec.table]
        self._validate_non_null(stage, spec.primary_key)
        self._validate_unique(stage, spec.primary_key)
        wrong_partition = int(
            self.client.query(
                f"SELECT count() FROM {self.db}.`{stage}` "
                f"WHERE {schema.partition_by} != {partition_sql}"
            ).first_row[0]
        )
        if wrong_partition:
            raise ValueError(
                f"partition stage {stage} has {wrong_partition} rows outside {partition_sql}"
            )
        count = int(
            self.client.query(f"SELECT count() FROM {self.db}.`{stage}`").first_row[0]
        )
        if not count and not allow_empty:
            raise ValueError(f"refusing to publish empty {spec.name} partition")
        if count:
            content = str(
                self.client.query(
                    f"SELECT lower(hex(groupBitXor(cityHash64(_record_hash)))) "
                    f"FROM {self.db}.`{stage}`"
                ).first_row[0]
            )
            self.client.command(
                f"ALTER TABLE {self.db}.`{spec.table}` REPLACE PARTITION {partition_sql} "
                f"FROM {self.db}.`{stage}`"
            )
        else:
            content = dataframe_hash(pd.DataFrame(), spec.primary_key)
            self.client.command(
                f"ALTER TABLE {self.db}.`{spec.table}` DROP PARTITION {partition_sql}"
            )
        self.client.command(f"DROP TABLE {self.db}.`{stage}`")
        return PublishResult(row_count=count, content_hash=content)

    def publish_daily_stage(
        self,
        spec: DatasetSpec,
        stage: str,
        trading_date: date,
        *,
        allow_empty: bool = False,
    ) -> PublishResult:
        """Validate and atomically publish a complete all-market daily partition."""

        self._validate_non_null(stage, spec.primary_key)
        self._validate_unique(stage, spec.primary_key)
        schema = TABLE_SCHEMAS[spec.table]
        # Daily source tables do not all call their date ``trading_date``.
        # Their schema contract is a single bare date partition column, so use
        # it directly instead of guessing a shared source field name.
        date_column = schema.partition_by
        if not date_column.isidentifier():
            raise ValueError(
                f"daily table {spec.table} must partition by one date column, "
                f"got {date_column!r}"
            )
        day = quote_string(str(trading_date))
        wrong_dates = int(
            self.client.query(
                f"SELECT count() FROM {self.db}.`{stage}` "
                f"WHERE `{date_column}` != toDate({day})"
            ).first_row[0]
        )
        if wrong_dates:
            raise ValueError(
                f"daily staging {stage} contains {wrong_dates} rows outside {trading_date}"
            )
        count = int(
            self.client.query(f"SELECT count() FROM {self.db}.`{stage}`").first_row[0]
        )
        if not count and not allow_empty:
            raise ValueError(
                f"refusing to publish empty all-market {spec.name} day: {trading_date}"
            )
        if count:
            content = str(
                self.client.query(
                    f"SELECT lower(hex(groupBitXor(cityHash64(_record_hash)))) "
                    f"FROM {self.db}.`{stage}`"
                ).first_row[0]
            )
            self.client.command(
                f"ALTER TABLE {self.db}.`{spec.table}` REPLACE PARTITION {day} "
                f"FROM {self.db}.`{stage}`"
            )
        else:
            content = dataframe_hash(pd.DataFrame(), spec.primary_key)
            self.client.command(
                f"ALTER TABLE {self.db}.`{spec.table}` DROP PARTITION {day}"
            )
        self.client.command(f"DROP TABLE {self.db}.`{stage}`")
        return PublishResult(row_count=count, content_hash=content)

    def prepare_tick_day(self, trading_date: date) -> str:
        stage = f"ricequant_stock_tick_stage_{trading_date:%Y%m%d}"
        self.client.command(
            f"CREATE TABLE IF NOT EXISTS {self.db}.`{stage}` AS {self.db}.`ricequant_stock_tick`"
        )
        return stage

    def replace_tick_instrument(
        self, stage: str, order_book_id: str, frame: pd.DataFrame
    ) -> None:
        self.client.command(
            f"ALTER TABLE {self.db}.`{stage}` DELETE WHERE order_book_id = {quote_string(order_book_id)} "
            "SETTINGS mutations_sync = 2"
        )
        self.insert_frame(stage, frame)
        self._validate_unique(
            stage, ("trading_date", "order_book_id", "datetime", "tick_sequence")
        )

    def publish_tick_day(self, stage: str, trading_date: date) -> PublishResult:
        spec = __import__(
            "ricequant_integration.specs", fromlist=["DATASET_SPECS"]
        ).DATASET_SPECS["tick"]
        self._validate_non_null(stage, spec.primary_key)
        self._validate_unique(stage, spec.primary_key)
        day = quote_string(str(trading_date))
        wrong_dates = int(
            self.client.query(
                f"SELECT count() FROM {self.db}.`{stage}` WHERE trading_date != toDate({day})"
            ).first_row[0]
        )
        if wrong_dates:
            raise ValueError(
                f"tick staging {stage} contains {wrong_dates} rows outside {trading_date}"
            )
        count = int(
            self.client.query(f"SELECT count() FROM {self.db}.`{stage}`").first_row[0]
        )
        if not count:
            raise ValueError(
                f"refusing to publish empty all-market Tick day: {trading_date}"
            )
        content = str(
            self.client.query(
                f"SELECT lower(hex(groupBitXor(cityHash64(_record_hash)))) "
                f"FROM {self.db}.`{stage}`"
            ).first_row[0]
        )
        self.client.command(
            f"ALTER TABLE {self.db}.`ricequant_stock_tick` REPLACE PARTITION {day} FROM {self.db}.`{stage}`"
        )
        self.client.command(f"DROP TABLE {self.db}.`{stage}`")
        return PublishResult(row_count=count, content_hash=content)

    def table_frame(self, table: str, where: str = "1") -> pd.DataFrame:
        return self.client.query_df(f"SELECT * FROM {self.db}.`{table}` WHERE {where}")

    def estimate_bytes(self, dataset: str, default: int) -> int:
        result = self.client.query(
            "SELECT if(isNaN(q), toUInt64(0), toUInt64(q)) FROM ("
            f"SELECT quantile(0.8)(bytes_used) AS q FROM {self.db}.`ricequant_quota_observation` "
            f"WHERE dataset = {quote_string(dataset)} AND observed_at >= now() - INTERVAL 90 DAY)"
        )
        observed = int(result.first_row[0])
        return observed or default

    def record_quota_observation(
        self, dataset: str, slice_key: str, bytes_used: int, row_count: int
    ) -> None:
        frame = pd.DataFrame(
            [
                {
                    "event_id": uuid.uuid4().hex,
                    "dataset": dataset,
                    "slice_key": slice_key,
                    "bytes_used": max(0, bytes_used),
                    "row_count": max(0, row_count),
                    "observed_at": datetime.now(),
                }
            ]
        )
        self.insert_frame("ricequant_quota_observation", frame)

    @staticmethod
    def _literal(value: object) -> str:
        if isinstance(value, (date, datetime)):
            return quote_string(str(value))
        if isinstance(value, str):
            return quote_string(value)
        if value is None:
            return "NULL"
        return str(value)
