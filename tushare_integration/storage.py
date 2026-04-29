from __future__ import annotations

from copy import deepcopy


SYSTEM_METADATA_COLUMNS = [
    {
        "name": "_source",
        "data_type": "str",
        "length": 32,
        "default": "",
        "comment": "数据来源",
    },
    {
        "name": "_api_name",
        "data_type": "str",
        "length": 128,
        "default": "",
        "comment": "源接口名称",
    },
    {
        "name": "_batch_id",
        "data_type": "str",
        "length": 64,
        "default": "",
        "comment": "采集批次ID",
    },
    {
        "name": "_ingest_time",
        "data_type": "datetime",
        "default": "1970-01-01 00:00:00",
        "comment": "入库时间",
    },
    {
        "name": "_record_hash",
        "data_type": "str",
        "length": 32,
        "default": "",
        "comment": "记录哈希",
    },
]

RAW_ONLY_COLUMNS = [
    {
        "name": "_raw_json",
        "data_type": "json",
        "length": 8192,
        "default": "",
        "comment": "原始行JSON",
    }
]


def get_latest_table_name(base_table_name: str) -> str:
    return base_table_name


def get_raw_table_name(base_table_name: str) -> str:
    return f"{base_table_name}_raw"


def _merge_columns(base_columns: list[dict], extra_columns: list[dict]) -> list[dict]:
    merged_columns = deepcopy(base_columns)
    existing_names = {column["name"] for column in merged_columns}
    for column in extra_columns:
        if column["name"] not in existing_names:
            merged_columns.append(deepcopy(column))
    return merged_columns


def build_latest_schema(base_schema: dict) -> dict:
    latest_schema = deepcopy(base_schema)
    latest_schema["columns"] = _merge_columns(base_schema["columns"], SYSTEM_METADATA_COLUMNS)
    return latest_schema


def build_raw_schema(base_schema: dict) -> dict:
    raw_schema = deepcopy(base_schema)
    raw_columns = deepcopy(base_schema["columns"])

    for column in raw_columns:
        column["nullable"] = True
        column.pop("default", None)

    raw_schema["columns"] = _merge_columns(raw_columns, SYSTEM_METADATA_COLUMNS + RAW_ONLY_COLUMNS)
    raw_schema["comment"] = f"{base_schema.get('comment', '')} RAW".strip()
    raw_schema["primary_key"] = []

    # ClickHouse MergeTree sorting key cannot contain Nullable columns unless
    # allow_nullable_key is enabled at the server/table level. Raw tables keep
    # business columns nullable, so the ORDER BY must use non-null metadata.
    raw_schema["indexes"] = [{"name": "raw_order_idx", "columns": ["_ingest_time", "_batch_id", "_record_hash"]}]

    return raw_schema
