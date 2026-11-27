from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ricequant_integration.specs import DEFAULT_INDEXES


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int = 8123
    user: str = "default"
    password: str = ""
    database: str = "default"
    secure: bool = False


@dataclass(frozen=True)
class RiceQuantSettings:
    database: DatabaseSettings
    token: str
    indexes: tuple[str, ...] = DEFAULT_INDEXES
    history_start_date: str = "1990-01-01"
    index_weights_ex_start_date: str = "2015-01-01"
    stock_daily_start_date: str = "2015-01-01"
    stock_minute_start_date: str = "2020-01-01"
    option_start_date: str = "2019-01-01"
    factor_start_date: str = "1990-01-01"
    financial_start_date: str = "2015-01-01"
    concept_start_date: str = "2015-01-01"
    stock_connect_holding_start_date: str = "2015-01-01"
    fund_holding_start_date: str = "2015-01-01"
    stock_dividend_start_date: str = "2015-01-01"
    stock_dividend_batch_size: int = 100
    stock_daily_batch_size: int = 1000
    stock_minute_batch_size: int = 200
    option_batch_size: int = 500
    financial_batch_size: int = 20
    stock_connect_holding_batch_size: int = 500
    fund_holding_batch_size: int = 500
    fund_holding_rescan_days: int = 365
    financial_rescan_days: int = 1100
    classification_lookback_calendar_days: int = 7
    tick_lookback_calendar_days: int = 31
    daily_data_ready_time: str = "18:00"
    quota_min_reserve_bytes: int = 256 * 1024 * 1024
    quota_estimate_multiplier: float = 1.5
    lock_file: str = "/tmp/ricequant-integration.lock"
    batch_rows: int = 200_000
    config_path: str = "ricequant.yaml"
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(
        cls, path: str | Path = "ricequant.yaml", *, require_token: bool = True
    ) -> "RiceQuantSettings":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"RiceQuant config not found: {path}. Copy ricequant.example.yaml and set database values."
            )
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        db_raw = raw.get("database") or {}
        token = os.environ.get("RQDATA_TOKEN", "")
        if require_token and not token:
            raise ValueError("RQDATA_TOKEN must be set")
        database = DatabaseSettings(
            host=os.environ.get("DB_HOST", str(db_raw.get("host", "localhost"))),
            port=int(os.environ.get("DB_PORT", db_raw.get("port", 8123))),
            user=os.environ.get("DB_USER", str(db_raw.get("user", "default"))),
            password=os.environ.get("DB_PASSWORD", str(db_raw.get("password", ""))),
            database=os.environ.get(
                "DB_NAME", str(db_raw.get("db_name", db_raw.get("database", "default")))
            ),
            secure=str(os.environ.get("DB_SECURE", db_raw.get("secure", False))).lower()
            in {"1", "true", "yes"},
        )
        known = {
            "database",
            "indexes",
            "history_start_date",
            "index_weights_ex_start_date",
            "stock_daily_start_date",
            "stock_minute_start_date",
            "option_start_date",
            "factor_start_date",
            "financial_start_date",
            "concept_start_date",
            "stock_connect_holding_start_date",
            "fund_holding_start_date",
            "stock_dividend_start_date",
            "stock_dividend_batch_size",
            "stock_daily_batch_size",
            "stock_minute_batch_size",
            "option_batch_size",
            "financial_batch_size",
            "stock_connect_holding_batch_size",
            "fund_holding_batch_size",
            "fund_holding_rescan_days",
            "financial_rescan_days",
            "classification_lookback_calendar_days",
            "tick_lookback_calendar_days",
            "daily_data_ready_time",
            "quota_min_reserve_bytes",
            "quota_estimate_multiplier",
            "lock_file",
            "batch_rows",
        }
        return cls(
            database=database,
            token=token,
            indexes=tuple(raw.get("indexes") or DEFAULT_INDEXES),
            history_start_date=str(raw.get("history_start_date", "1990-01-01")),
            index_weights_ex_start_date=str(
                raw.get("index_weights_ex_start_date", "2015-01-01")
            ),
            stock_daily_start_date=str(
                raw.get("stock_daily_start_date", "2015-01-01")
            ),
            stock_minute_start_date=str(
                raw.get("stock_minute_start_date", "2020-01-01")
            ),
            option_start_date=str(raw.get("option_start_date", "2019-01-01")),
            factor_start_date=str(raw.get("factor_start_date", "1990-01-01")),
            financial_start_date=str(
                raw.get("financial_start_date", "2015-01-01")
            ),
            concept_start_date=str(raw.get("concept_start_date", "2015-01-01")),
            stock_connect_holding_start_date=str(
                raw.get("stock_connect_holding_start_date", "2015-01-01")
            ),
            fund_holding_start_date=str(
                raw.get("fund_holding_start_date", "2015-01-01")
            ),
            stock_dividend_start_date=str(
                raw.get("stock_dividend_start_date", "2015-01-01")
            ),
            stock_dividend_batch_size=max(
                1, int(raw.get("stock_dividend_batch_size", 100))
            ),
            stock_daily_batch_size=max(
                1, int(raw.get("stock_daily_batch_size", 1000))
            ),
            stock_minute_batch_size=max(
                1, int(raw.get("stock_minute_batch_size", 200))
            ),
            option_batch_size=max(1, int(raw.get("option_batch_size", 500))),
            financial_batch_size=max(1, int(raw.get("financial_batch_size", 20))),
            stock_connect_holding_batch_size=max(
                1, int(raw.get("stock_connect_holding_batch_size", 500))
            ),
            fund_holding_batch_size=max(
                1, int(raw.get("fund_holding_batch_size", 500))
            ),
            fund_holding_rescan_days=max(
                1, int(raw.get("fund_holding_rescan_days", 365))
            ),
            financial_rescan_days=max(
                1, int(raw.get("financial_rescan_days", 1100))
            ),
            classification_lookback_calendar_days=max(
                1, int(raw.get("classification_lookback_calendar_days", 7))
            ),
            tick_lookback_calendar_days=int(raw.get("tick_lookback_calendar_days", 31)),
            daily_data_ready_time=str(raw.get("daily_data_ready_time", "18:00")),
            quota_min_reserve_bytes=int(
                raw.get("quota_min_reserve_bytes", 256 * 1024 * 1024)
            ),
            quota_estimate_multiplier=float(raw.get("quota_estimate_multiplier", 1.5)),
            lock_file=str(raw.get("lock_file", "/tmp/ricequant-integration.lock")),
            batch_rows=int(raw.get("batch_rows", 200_000)),
            config_path=str(path),
            extra={key: value for key, value in raw.items() if key not in known},
        )
