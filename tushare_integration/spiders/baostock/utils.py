from __future__ import annotations

import datetime
from typing import Any

import pandas as pd


BAOSTOCK_START_DATE = datetime.date(2015, 1, 1)
BAOSTOCK_EXCHANGE_SUFFIX = {
    "sh": "SH",
    "sz": "SZ",
    "bj": "BJ",
}


def normalize_baostock_code(code: Any) -> str:
    if code is None:
        return ""
    value = str(code).strip()
    if not value:
        return ""
    parts = value.split(".")
    if len(parts) != 2:
        return value.upper()
    exchange, symbol = parts[0].lower(), parts[1]
    suffix = BAOSTOCK_EXCHANGE_SUFFIX.get(exchange, exchange.upper())
    return f"{symbol}.{suffix}"


def baostock_exchange(code: Any) -> str:
    normalized = normalize_baostock_code(code)
    if "." not in normalized:
        return ""
    return normalized.rsplit(".", 1)[1]


def parse_date_value(value: Any) -> datetime.date | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def format_baostock_date(value: Any) -> str:
    parsed = parse_date_value(value)
    if parsed is None:
        raise ValueError(f"Invalid Baostock date: {value}")
    return parsed.isoformat()
