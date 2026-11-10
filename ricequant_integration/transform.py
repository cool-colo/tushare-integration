from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


METADATA = ("_source", "_api_name", "_batch_id", "_ingest_time", "_record_hash")
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _normalise_index(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if isinstance(result.index, pd.MultiIndex):
        result = result.reset_index()
    elif not isinstance(result.index, pd.RangeIndex):
        index_name = result.index.name or "datetime"
        result = result.reset_index(names=index_name)
    return result


def _find_column(frame: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    lookup = {str(column).lower(): column for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return str(lookup[candidate.lower()])
    return None


def _record_hash(record: dict[str, Any]) -> str:
    def serializable(value: Any) -> Any:
        if value is None:
            return None
        try:
            if bool(pd.isna(value)):
                return None
        except (TypeError, ValueError):
            pass
        if isinstance(value, (pd.Timestamp, datetime, date)):
            return value.isoformat()
        if isinstance(value, np.generic):
            return value.item()
        return value

    payload = {
        key: serializable(value) for key, value in record.items() if key not in METADATA
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.md5(encoded, usedforsecurity=False).hexdigest()


def add_metadata(frame: pd.DataFrame, api_name: str, batch_id: str) -> pd.DataFrame:
    result = frame.copy()
    result["_source"] = "ricequant"
    result["_api_name"] = api_name
    result["_batch_id"] = batch_id
    result["_ingest_time"] = datetime.now(SHANGHAI_TZ)
    result["_record_hash"] = [
        _record_hash(record) for record in result.to_dict("records")
    ]
    return result


def _shanghai_datetime(values: Any) -> pd.Series:
    """Interpret RQData's timezone-naive timestamps as Shanghai local time."""

    result = pd.to_datetime(values, errors="coerce")
    if result.dt.tz is None:
        return result.dt.tz_localize(SHANGHAI_TZ)
    return result.dt.tz_convert(SHANGHAI_TZ)


def conform(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column not in result:
            result[column] = None
    return result[columns]


INDEX_DAILY_COLUMNS = [
    "order_book_id",
    "trading_date",
    "open",
    "high",
    "low",
    "close",
    "prev_close",
    "volume",
    "total_turnover",
    "num_trades",
    *METADATA,
]


def index_daily_frame(
    raw: pd.DataFrame, order_book_id: str, batch_id: str
) -> pd.DataFrame:
    raw = _normalise_index(raw)
    if raw.empty:
        return conform(
            add_metadata(pd.DataFrame(), "get_price", batch_id), INDEX_DAILY_COLUMNS
        )
    date_column = _find_column(raw, ("trading_date", "date", "datetime"))
    if date_column is None:
        raise ValueError("RQData index daily response has no date/datetime column")
    result = raw.rename(columns={date_column: "trading_date"})
    result["trading_date"] = pd.to_datetime(result["trading_date"]).dt.date
    result["order_book_id"] = order_book_id
    for column in (
        "open",
        "high",
        "low",
        "close",
        "prev_close",
        "volume",
        "total_turnover",
        "num_trades",
    ):
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return conform(add_metadata(result, "get_price", batch_id), INDEX_DAILY_COLUMNS)


COMPONENT_COLUMNS = ["index_id", "trading_date", "component_id", *METADATA]


def index_components_frame(
    raw: Any, index_id: str, batch_id: str, default_date: date
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    if raw is None:
        pass
    elif isinstance(raw, dict):
        for key, values in raw.items():
            when = pd.Timestamp(key).date()
            if isinstance(values, pd.DataFrame):
                component_column = _find_column(
                    values, ("order_book_id", "component_id", "stock_code")
                )
                components = (
                    values[component_column].tolist()
                    if component_column
                    else values.index.tolist()
                )
            elif isinstance(values, pd.Series):
                components = (
                    values.index.tolist()
                    if not isinstance(values.index, pd.RangeIndex)
                    else values.tolist()
                )
            else:
                components = list(values)
            records.extend(
                {
                    "index_id": index_id,
                    "trading_date": when,
                    "component_id": str(component),
                }
                for component in components
            )
    elif isinstance(raw, (list, tuple, set, pd.Index)):
        records.extend(
            {
                "index_id": index_id,
                "trading_date": default_date,
                "component_id": str(component),
            }
            for component in raw
        )
    else:
        frame = _normalise_index(pd.DataFrame(raw))
        date_column = _find_column(frame, ("trading_date", "date", "datetime"))
        component_column = _find_column(
            frame, ("order_book_id", "component_id", "stock_code")
        )
        if component_column is None:
            raise ValueError(
                "RQData index_components response has no component identifier"
            )
        for _, row in frame.iterrows():
            when = (
                pd.Timestamp(row[date_column]).date() if date_column else default_date
            )
            records.append(
                {
                    "index_id": index_id,
                    "trading_date": when,
                    "component_id": str(row[component_column]),
                }
            )
    result = pd.DataFrame.from_records(
        records, columns=COMPONENT_COLUMNS[:3]
    ).drop_duplicates()
    return conform(
        add_metadata(result, "index_components", batch_id), COMPONENT_COLUMNS
    )


WEIGHT_COLUMNS = ["index_id", "snapshot_date", "component_id", "weight", *METADATA]


def index_weights_frame(
    raw: Any, index_id: str, batch_id: str, snapshot_date: date
) -> pd.DataFrame:
    if raw is None:
        result = pd.DataFrame(columns=WEIGHT_COLUMNS[:4])
    elif isinstance(raw, pd.Series):
        result = raw.rename("weight").rename_axis("component_id").reset_index()
    else:
        result = _normalise_index(pd.DataFrame(raw))
        component = _find_column(
            result, ("order_book_id", "component_id", "stock_code")
        )
        weight = _find_column(result, ("weight", "weights"))
        if component is None and not isinstance(result.index, pd.RangeIndex):
            result = result.reset_index().rename(
                columns={result.index.name or "index": "component_id"}
            )
            component = "component_id"
        if component is None or weight is None:
            raise ValueError(
                "RQData index_weights response lacks component or weight column"
            )
        result = result.rename(columns={component: "component_id", weight: "weight"})
    result["index_id"] = index_id
    result["snapshot_date"] = snapshot_date
    if "component_id" in result:
        result["component_id"] = result["component_id"].astype(str)
    if "weight" in result:
        result["weight"] = pd.to_numeric(result["weight"], errors="coerce")
    return conform(add_metadata(result, "index_weights", batch_id), WEIGHT_COLUMNS)


WEIGHT_EX_COLUMNS = [
    "index_id",
    "trading_date",
    "component_id",
    "weight",
    *METADATA,
]


def index_weights_ex_frame(raw: Any, index_id: str, batch_id: str) -> pd.DataFrame:
    if raw is None:
        result = pd.DataFrame(columns=WEIGHT_EX_COLUMNS[:4])
    else:
        result = _normalise_index(pd.DataFrame(raw))
        date_column = _find_column(result, ("trading_date", "date", "datetime"))
        component_column = _find_column(
            result, ("order_book_id", "component_id", "stock_code")
        )
        weight_column = _find_column(result, ("weight", "weights"))
        if date_column is None or component_column is None or weight_column is None:
            raise ValueError(
                "RQData index_weights_ex response lacks date, component, or weight"
            )
        result = result.rename(
            columns={
                date_column: "trading_date",
                component_column: "component_id",
                weight_column: "weight",
            }
        )
    result["index_id"] = index_id
    if "trading_date" in result:
        result["trading_date"] = pd.to_datetime(
            result["trading_date"], format="ISO8601", errors="coerce"
        ).dt.date
    if "component_id" in result:
        result["component_id"] = result["component_id"].astype(str)
    if "weight" in result:
        result["weight"] = pd.to_numeric(result["weight"], errors="coerce")
    return conform(
        add_metadata(result, "index_weights_ex", batch_id), WEIGHT_EX_COLUMNS
    )


STOCK_DAILY_VALUE_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "prev_close",
    "volume",
    "total_turnover",
    "num_trades",
    "limit_up",
    "limit_down",
]
STOCK_DAILY_COLUMNS = [
    "trading_date",
    "order_book_id",
    *STOCK_DAILY_VALUE_COLUMNS,
    *METADATA,
]


def stock_daily_frame(
    raw: pd.DataFrame, trading_date: date, batch_id: str
) -> pd.DataFrame:
    result = _normalise_index(raw)
    if result.empty:
        return conform(add_metadata(result, "get_price", batch_id), STOCK_DAILY_COLUMNS)
    identifier = _find_column(result, ("order_book_id", "instrument"))
    date_column = _find_column(result, ("trading_date", "date", "datetime"))
    if identifier is None or date_column is None:
        raise ValueError("RQData stock daily response lacks order_book_id or date")
    result = result.rename(
        columns={identifier: "order_book_id", date_column: "trading_date"}
    )
    result["trading_date"] = pd.to_datetime(
        result["trading_date"], format="ISO8601", errors="coerce"
    ).dt.date
    returned_dates = set(result["trading_date"].dropna())
    if returned_dates != {trading_date}:
        raise ValueError(
            f"RQData stock daily response dates {sorted(returned_dates)} do not match requested {trading_date}"
        )
    result["order_book_id"] = result["order_book_id"].astype(str)
    for column in STOCK_DAILY_VALUE_COLUMNS:
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return conform(add_metadata(result, "get_price", batch_id), STOCK_DAILY_COLUMNS)


STOCK_MINUTE_VALUE_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "total_turnover",
    "num_trades",
]
STOCK_MINUTE_COLUMNS = [
    "trading_date",
    "order_book_id",
    "datetime",
    *STOCK_MINUTE_VALUE_COLUMNS,
    *METADATA,
]


def stock_minute_frame(
    raw: pd.DataFrame, trading_date: date, batch_id: str
) -> pd.DataFrame:
    result = _normalise_index(raw)
    if result.empty:
        return conform(
            add_metadata(result, "get_price", batch_id), STOCK_MINUTE_COLUMNS
        )
    identifier = _find_column(result, ("order_book_id", "instrument"))
    datetime_column = _find_column(result, ("datetime", "timestamp", "date"))
    if identifier is None or datetime_column is None:
        raise ValueError("RQData stock minute response lacks order_book_id or datetime")
    result = result.rename(
        columns={identifier: "order_book_id", datetime_column: "datetime"}
    )
    result["datetime"] = _shanghai_datetime(result["datetime"])
    returned_dates = set(result["datetime"].dt.date.dropna())
    if returned_dates != {trading_date}:
        raise ValueError(
            f"RQData stock minute response dates {sorted(returned_dates)} do not match requested {trading_date}"
        )
    result["trading_date"] = trading_date
    result["order_book_id"] = result["order_book_id"].astype(str)
    for column in STOCK_MINUTE_VALUE_COLUMNS:
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return conform(add_metadata(result, "get_price", batch_id), STOCK_MINUTE_COLUMNS)


EX_FACTOR_COLUMNS = [
    "order_book_id",
    "ex_date",
    "announcement_date",
    "ex_end_date",
    "ex_factor",
    "ex_cum_factor",
    "rice_create_tm",
    *METADATA,
]


def ex_factor_frame(raw: pd.DataFrame, batch_id: str) -> pd.DataFrame:
    result = _normalise_index(raw)
    if result.empty:
        return conform(
            add_metadata(result, "get_ex_factor", batch_id), EX_FACTOR_COLUMNS
        )
    identifier = _find_column(result, ("order_book_id", "instrument"))
    ex_date = _find_column(result, ("ex_date",))
    if identifier is None or ex_date is None:
        raise ValueError("RQData ex-factor response lacks order_book_id or ex_date")
    result = result.rename(columns={identifier: "order_book_id", ex_date: "ex_date"})
    result["order_book_id"] = result["order_book_id"].astype(str)
    for column in ("ex_date", "announcement_date", "ex_end_date"):
        if column in result:
            result[column] = pd.to_datetime(result[column], errors="coerce").dt.date
    if "rice_create_tm" in result:
        result["rice_create_tm"] = _shanghai_datetime(result["rice_create_tm"])
    for column in ("ex_factor", "ex_cum_factor"):
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return conform(add_metadata(result, "get_ex_factor", batch_id), EX_FACTOR_COLUMNS)


SPLIT_COLUMNS = [
    "order_book_id",
    "ex_dividend_date",
    "book_closure_date",
    "payable_date",
    "split_coefficient_from",
    "split_coefficient_to",
    "cum_factor",
    "rice_create_tm",
    *METADATA,
]


def split_frame(raw: pd.DataFrame, batch_id: str) -> pd.DataFrame:
    result = _normalise_index(raw)
    if result.empty:
        return conform(add_metadata(result, "get_split", batch_id), SPLIT_COLUMNS)
    identifier = _find_column(result, ("order_book_id", "instrument"))
    ex_date = _find_column(result, ("ex_dividend_date", "ex_date"))
    if identifier is None or ex_date is None:
        raise ValueError("RQData split response lacks order_book_id or ex-dividend date")
    result = result.rename(
        columns={identifier: "order_book_id", ex_date: "ex_dividend_date"}
    )
    result["order_book_id"] = result["order_book_id"].astype(str)
    for column in ("ex_dividend_date", "book_closure_date", "payable_date"):
        if column in result:
            result[column] = pd.to_datetime(result[column], errors="coerce").dt.date
    if "rice_create_tm" in result:
        result["rice_create_tm"] = _shanghai_datetime(result["rice_create_tm"])
    for column in ("split_coefficient_from", "split_coefficient_to", "cum_factor"):
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return conform(add_metadata(result, "get_split", batch_id), SPLIT_COLUMNS)


CONCEPT_CATALOG_COLUMNS = ["concept_name", "inclusion_date", *METADATA]


def concept_catalog_frame(raw: Any, batch_id: str) -> pd.DataFrame:
    if isinstance(raw, pd.Series):
        result = raw.rename("concept_name").rename_axis("inclusion_date").reset_index()
    else:
        result = _normalise_index(pd.DataFrame(raw))
        name = _find_column(result, ("concept_name", "concept"))
        inclusion = _find_column(result, ("inclusion_date", "date"))
        if not result.empty and (name is None or inclusion is None):
            raise ValueError("RQData concept catalog lacks concept name or inclusion date")
        if name and inclusion:
            result = result.rename(
                columns={name: "concept_name", inclusion: "inclusion_date"}
            )
    if "inclusion_date" in result:
        result["inclusion_date"] = pd.to_datetime(
            result["inclusion_date"], errors="coerce"
        ).dt.date
    if "concept_name" in result:
        result["concept_name"] = result["concept_name"].astype(str)
    result = conform(result, CONCEPT_CATALOG_COLUMNS[:2]).drop_duplicates(
        ["concept_name", "inclusion_date"]
    )
    return conform(
        add_metadata(result, "get_concept_list", batch_id), CONCEPT_CATALOG_COLUMNS
    )


CONCEPT_MEMBER_COLUMNS = [
    "concept_name",
    "order_book_id",
    "inclusion_date",
    *METADATA,
]


def concept_member_frame(raw: pd.DataFrame, batch_id: str) -> pd.DataFrame:
    result = _normalise_index(raw)
    if result.empty:
        return conform(
            add_metadata(result, "get_concept", batch_id), CONCEPT_MEMBER_COLUMNS
        )
    concept = _find_column(result, ("concept_name", "concept"))
    identifier = _find_column(result, ("order_book_id", "instrument"))
    inclusion = _find_column(result, ("inclusion_date", "date"))
    if concept is None or identifier is None or inclusion is None:
        raise ValueError("RQData concept members lack concept, instrument, or inclusion date")
    result = result.rename(
        columns={
            concept: "concept_name",
            identifier: "order_book_id",
            inclusion: "inclusion_date",
        }
    )
    result["concept_name"] = result["concept_name"].astype(str)
    result["order_book_id"] = result["order_book_id"].astype(str)
    result["inclusion_date"] = pd.to_datetime(
        result["inclusion_date"], errors="coerce"
    ).dt.date
    result = result.drop_duplicates(
        ["concept_name", "order_book_id", "inclusion_date"]
    )
    return conform(add_metadata(result, "get_concept", batch_id), CONCEPT_MEMBER_COLUMNS)


CONCEPT_SNAPSHOT_COLUMNS = [
    "observation_date",
    "observed_at",
    "snapshot_date",
    "concept_name",
    "order_book_id",
    *METADATA,
]


def concept_snapshot_frame(
    members: Iterable[str],
    concept_name: str,
    snapshot_date: date,
    observation_date: date,
    observed_at: datetime,
    batch_id: str,
) -> pd.DataFrame:
    result = pd.DataFrame(
        {
            "observation_date": observation_date,
            "observed_at": observed_at,
            "snapshot_date": snapshot_date,
            "concept_name": concept_name,
            "order_book_id": sorted({str(value) for value in members}),
        }
    )
    return conform(
        add_metadata(result, "concept", batch_id), CONCEPT_SNAPSHOT_COLUMNS
    )


INDUSTRY_MAPPING_COLUMNS = [
    "snapshot_date",
    "source_name",
    "first_industry_code",
    "first_industry_name",
    "second_industry_code",
    "second_industry_name",
    "third_industry_code",
    "third_industry_name",
    *METADATA,
]


def industry_mapping_frame(
    raw: pd.DataFrame, snapshot_date: date, source_name: str, batch_id: str
) -> pd.DataFrame:
    result = _normalise_index(raw)
    result["snapshot_date"] = snapshot_date
    result["source_name"] = source_name
    for column in INDUSTRY_MAPPING_COLUMNS[:8]:
        if column in {"snapshot_date", "source_name"}:
            continue
        if column in result:
            result[column] = result[column].fillna("").astype(str)
    result = conform(result, INDUSTRY_MAPPING_COLUMNS[:8]).drop_duplicates(
        INDUSTRY_MAPPING_COLUMNS[:8]
    )
    return conform(
        add_metadata(result, "get_industry_mapping", batch_id),
        INDUSTRY_MAPPING_COLUMNS,
    )


INDUSTRY_MEMBER_COLUMNS = [
    "source_name",
    "industry_level",
    "industry_code",
    "industry_name",
    "order_book_id",
    "start_date",
    "cancel_date",
    *METADATA,
]


def industry_member_frame(
    raw: pd.DataFrame,
    source_name: str,
    level: int,
    industry_code: str,
    industry_name: str,
    batch_id: str,
) -> pd.DataFrame:
    result = _normalise_index(raw)
    if result.empty:
        return conform(
            add_metadata(result, "get_industry_change", batch_id),
            INDUSTRY_MEMBER_COLUMNS,
        )
    identifier = _find_column(result, ("order_book_id", "instrument"))
    if identifier is None or "start_date" not in result:
        raise ValueError("RQData industry changes lack instrument or start_date")
    result = result.rename(columns={identifier: "order_book_id"})
    result["source_name"] = source_name
    result["industry_level"] = level
    result["industry_code"] = str(industry_code)
    result["industry_name"] = str(industry_name)
    result["order_book_id"] = result["order_book_id"].astype(str)
    for column in ("start_date", "cancel_date"):
        if column in result:
            result[column] = pd.to_datetime(result[column], errors="coerce").dt.date
    return conform(
        add_metadata(result, "get_industry_change", batch_id), INDUSTRY_MEMBER_COLUMNS
    )


INDUSTRY_SNAPSHOT_COLUMNS = [
    "observation_date",
    "observed_at",
    "snapshot_date",
    "source_name",
    "industry_level",
    "order_book_id",
    "industry_code",
    "industry_name",
    *METADATA,
]


def citics_industry_snapshot_frame(
    raw: pd.DataFrame,
    snapshot_date: date,
    observation_date: date,
    observed_at: datetime,
    batch_id: str,
) -> pd.DataFrame:
    wide = _normalise_index(raw)
    identifier = _find_column(wide, ("order_book_id", "instrument"))
    if not wide.empty and identifier is None:
        raise ValueError("RQData CITICS industry response lacks order_book_id")
    records: list[dict[str, Any]] = []
    if identifier:
        for _, row in wide.iterrows():
            for level, prefix in ((1, "first"), (2, "second"), (3, "third")):
                code = row.get(f"{prefix}_industry_code")
                name = row.get(f"{prefix}_industry_name")
                if pd.isna(code):
                    continue
                records.append(
                    {
                        "observation_date": observation_date,
                        "observed_at": observed_at,
                        "snapshot_date": snapshot_date,
                        "source_name": "citics_2019",
                        "industry_level": level,
                        "order_book_id": str(row[identifier]),
                        "industry_code": str(code),
                        "industry_name": "" if pd.isna(name) else str(name),
                    }
                )
    result = pd.DataFrame.from_records(records)
    return conform(
        add_metadata(result, "get_instrument_industry", batch_id),
        INDUSTRY_SNAPSHOT_COLUMNS,
    )


def shenwan_industry_snapshot_frame(
    raw: pd.DataFrame,
    snapshot_date: date,
    observation_date: date,
    observed_at: datetime,
    level: int,
    batch_id: str,
) -> pd.DataFrame:
    result = _normalise_index(raw)
    identifier = _find_column(result, ("order_book_id", "instrument"))
    code = _find_column(result, ("index_code", "industry_code"))
    name = _find_column(result, ("index_name", "industry_name"))
    if not result.empty and (identifier is None or code is None or name is None):
        raise ValueError("RQData Shenwan industry response lacks required columns")
    if identifier and code and name:
        result = result.rename(
            columns={
                identifier: "order_book_id",
                code: "industry_code",
                name: "industry_name",
            }
        )
    result["observation_date"] = observation_date
    result["observed_at"] = observed_at
    result["snapshot_date"] = snapshot_date
    result["source_name"] = "shenwan"
    result["industry_level"] = level
    return conform(
        add_metadata(result, "shenwan_instrument_industry", batch_id),
        INDUSTRY_SNAPSHOT_COLUMNS,
    )


SECTOR_SNAPSHOT_COLUMNS = [
    "observation_date",
    "observed_at",
    "sector_code",
    "sector_name",
    "order_book_id",
    *METADATA,
]


def sector_snapshot_frame(
    members: Iterable[str],
    sector_code: str,
    sector_name: str,
    observation_date: date,
    observed_at: datetime,
    batch_id: str,
) -> pd.DataFrame:
    result = pd.DataFrame(
        {
            "observation_date": observation_date,
            "observed_at": observed_at,
            "sector_code": sector_code,
            "sector_name": sector_name,
            "order_book_id": sorted({str(value) for value in members}),
        }
    )
    return conform(add_metadata(result, "sector", batch_id), SECTOR_SNAPSHOT_COLUMNS)


INSTRUMENT_COLUMNS = [
    "snapshot_date",
    "order_book_id",
    "symbol",
    "abbrev_symbol",
    "type",
    "exchange",
    "listed_date",
    "de_listed_date",
    "status",
    *METADATA,
]


def instruments_frame(
    raw: pd.DataFrame, snapshot_date: date, batch_id: str
) -> pd.DataFrame:
    result = _normalise_index(raw)
    identifier = _find_column(result, ("order_book_id", "instrument"))
    if not result.empty and identifier is None:
        raise ValueError("RQData all_instruments response has no order_book_id")
    if identifier and identifier != "order_book_id":
        result = result.rename(columns={identifier: "order_book_id"})
    result["snapshot_date"] = snapshot_date
    for column in ("listed_date", "de_listed_date"):
        if column in result:
            # RQData returns ISO-8601 dates mixed with missing values. Giving
            # pandas the explicit source format avoids per-element inference
            # warnings and keeps parsing deterministic.
            result[column] = pd.to_datetime(
                result[column], format="ISO8601", errors="coerce"
            ).dt.date
    return conform(
        add_metadata(result, "all_instruments", batch_id), INSTRUMENT_COLUMNS
    )


TICK_VALUE_COLUMNS = [
    "last",
    "open",
    "high",
    "low",
    "prev_close",
    "volume",
    "total_turnover",
    "num_trades",
    "limit_up",
    "limit_down",
    "change_rate",
    "a1",
    "a1_v",
    "a2",
    "a2_v",
    "a3",
    "a3_v",
    "a4",
    "a4_v",
    "a5",
    "a5_v",
    "b1",
    "b1_v",
    "b2",
    "b2_v",
    "b3",
    "b3_v",
    "b4",
    "b4_v",
    "b5",
    "b5_v",
]
TICK_COLUMNS = [
    "trading_date",
    "order_book_id",
    "datetime",
    "tick_sequence",
    *TICK_VALUE_COLUMNS,
    *METADATA,
]


def tick_frame(
    raw: pd.DataFrame, order_book_id: str, trading_date: date, batch_id: str
) -> pd.DataFrame:
    result = _normalise_index(raw)
    if result.empty:
        return conform(add_metadata(result, "get_price", batch_id), TICK_COLUMNS)
    datetime_column = _find_column(result, ("datetime", "date", "timestamp"))
    if datetime_column is None:
        raise ValueError("RQData Tick response has no datetime column")
    result = result.rename(columns={datetime_column: "datetime"})
    result["datetime"] = _shanghai_datetime(result["datetime"])
    source_trading_date = _find_column(result, ("trading_date",))
    if source_trading_date:
        returned_dates = set(
            pd.to_datetime(result[source_trading_date]).dt.date.dropna()
        )
        if returned_dates != {trading_date}:
            raise ValueError(
                f"RQData Tick response dates {sorted(returned_dates)} do not match requested {trading_date}"
            )
    result["trading_date"] = trading_date
    result["order_book_id"] = order_book_id
    # Multiple source ticks may share a timestamp. cumcount is deterministic for
    # the ordered RQData response and therefore forms a stable replay-safe key.
    result["tick_sequence"] = (
        result.groupby("datetime", sort=False).cumcount().astype("uint32")
    )
    for column in TICK_VALUE_COLUMNS:
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return conform(add_metadata(result, "get_price", batch_id), TICK_COLUMNS)


def financial_version_key(
    order_book_id: str,
    quarter: str,
    info_date: date | None,
    if_adjusted: int | None,
    rice_create_tm: datetime | None,
) -> str:
    """Build a stable non-null identity for one RQData disclosure version."""

    return _record_hash(
        {
            "order_book_id": order_book_id,
            "quarter": quarter,
            "info_date": info_date,
            "if_adjusted": if_adjusted,
            "rice_create_tm": rice_create_tm,
        }
    )


def _quarter_report_period(value: Any) -> date:
    text = str(value).strip().lower()
    if len(text) != 6 or text[4] != "q" or text[5] not in "1234":
        raise ValueError(f"invalid RQData financial quarter: {value!r}")
    try:
        year = int(text[:4])
    except ValueError as exc:
        raise ValueError(f"invalid RQData financial quarter: {value!r}") from exc
    quarter = int(text[5])
    month_day = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    month, day = month_day[quarter]
    return date(year, month, day)


FINANCIAL_COMMON_COLUMNS = [
    "order_book_id",
    "report_period",
    "quarter",
    "source_version_id",
    "info_date",
    "if_adjusted",
    "rice_create_tm",
    "query_date",
    "observed_at",
    "statements",
]


def financial_statement_frame(
    raw: pd.DataFrame,
    fields: tuple[str, ...],
    query_date: date,
    observed_at: datetime,
    batch_id: str,
) -> pd.DataFrame:
    """Normalize one independently requested PIT financial field group.

    ``statements='all'`` is represented explicitly and source availability
    fields are never filled from another source or inferred from a trading day.
    """

    result = _normalise_index(raw)
    columns = [*FINANCIAL_COMMON_COLUMNS, *fields, *METADATA]
    if result.empty:
        return conform(
            add_metadata(pd.DataFrame(), "get_pit_financials_ex", batch_id),
            columns,
        )

    identifier = _find_column(result, ("order_book_id",))
    quarter_column = _find_column(result, ("quarter",))
    required_source_columns = {
        "info_date",
        "if_adjusted",
        "rice_create_tm",
    }
    missing_common = required_source_columns - set(map(str, result.columns))
    missing_fields = set(fields) - set(map(str, result.columns))
    if identifier is None or quarter_column is None or missing_common or missing_fields:
        raise ValueError(
            "RQData PIT financial response schema mismatch: "
            f"missing_common={sorted(missing_common)} "
            f"missing_fields={sorted(missing_fields)}"
        )
    allowed = set(fields) | required_source_columns | {
        str(identifier),
        str(quarter_column),
    }
    unexpected = set(map(str, result.columns)) - allowed
    if unexpected:
        raise ValueError(
            f"RQData PIT financial response has unexpected columns: {sorted(unexpected)}"
        )

    result = result.rename(
        columns={identifier: "order_book_id", quarter_column: "quarter"}
    )
    result["order_book_id"] = result["order_book_id"].astype(str)
    result["quarter"] = result["quarter"].astype(str).str.lower()
    result["report_period"] = result["quarter"].map(_quarter_report_period)
    result["info_date"] = pd.to_datetime(
        result["info_date"], format="ISO8601", errors="coerce"
    ).dt.date
    result["if_adjusted"] = pd.to_numeric(
        result["if_adjusted"], errors="coerce"
    ).astype("Int64")
    result["rice_create_tm"] = _shanghai_datetime(result["rice_create_tm"])
    result["query_date"] = query_date
    result["observed_at"] = observed_at
    result["statements"] = "all"
    result["source_version_id"] = [
        financial_version_key(
            str(row["order_book_id"]),
            str(row["quarter"]),
            row["info_date"],
            None if pd.isna(row["if_adjusted"]) else int(row["if_adjusted"]),
            None if pd.isna(row["rice_create_tm"]) else row["rice_create_tm"],
        )
        for _, row in result.iterrows()
    ]
    for field in fields:
        result[field] = pd.to_numeric(result[field], errors="coerce")
    return conform(
        add_metadata(result, "get_pit_financials_ex", batch_id), columns
    )
