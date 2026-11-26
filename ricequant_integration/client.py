from __future__ import annotations

import importlib
import os
from datetime import date
from types import ModuleType
from typing import Any

import pandas as pd

from ricequant_integration.quota import QuotaSnapshot


class RqDataClient:
    """Small lazy adapter around rqdatac, kept injectable for deterministic tests."""

    def __init__(self, token: str, module: ModuleType | Any | None = None):
        self.token = token
        self.rq = module

    def initialize(self) -> None:
        if self.rq is None:
            try:
                self.rq = importlib.import_module("rqdatac")
            except ImportError as exc:
                raise RuntimeError(
                    f"Cannot import rqdatac (dependency: {exc.name or 'rqdatac'}). "
                    "In this Python environment run: "
                    "python -m pip install 'rqdatac[subscribe]==3.8.1'"
                ) from exc
        # RiceQuant issues an opaque RQSDK license rather than a username and
        # password. rqdatac reads that license from RQDATAC_CONF. Keep URI
        # wrapping here so operators only need to provide the issued token.
        os.environ["RQDATAC_CONF"] = self._connection_uri(self.token)
        result = self.rq.init(use_zstd=True)
        if result is False:
            raise RuntimeError("RQData authentication failed")

    @staticmethod
    def _connection_uri(token: str) -> str:
        if not token:
            raise ValueError("RQDATA_TOKEN must be set")
        if token.startswith(("rqdata://", "tcp://")):
            return token
        return f"rqdata://license:{token}@rqdatad-pro.ricequant.com:16011"

    def quota(self) -> QuotaSnapshot:
        raw = self.rq.user.get_quota()
        if isinstance(raw, dict):
            limit = raw.get("bytes_limit", 0)
            used = raw.get("bytes_used", 0)
        else:
            limit = getattr(raw, "bytes_limit", 0)
            used = getattr(raw, "bytes_used", 0)
        return QuotaSnapshot(bytes_limit=int(limit), bytes_used=int(used))

    def trading_dates(self, start: date, end: date) -> list[date]:
        values = self.rq.get_trading_dates(start_date=start, end_date=end)
        return sorted({pd.Timestamp(value).date() for value in values})

    def index_daily(self, order_book_id: str, start: date, end: date) -> pd.DataFrame:
        return self._as_frame(
            self.rq.get_price(
                order_book_id,
                start_date=start,
                end_date=end,
                frequency="1d",
                adjust_type="none",
                expect_df=True,
            )
        )

    def index_components(self, index_id: str, start: date, end: date) -> Any:
        return self.rq.index_components(index_id, start_date=start, end_date=end)

    def index_weights(self, index_id: str, snapshot_date: date) -> Any:
        return self.rq.index_weights(index_id, date=snapshot_date)

    def index_weights_ex(self, index_id: str, start: date, end: date) -> Any:
        return self.rq.index_weights_ex(
            index_id, start_date=start, end_date=end, market="cn"
        )

    def stock_daily(
        self, order_book_ids: list[str], trading_date: date
    ) -> pd.DataFrame:
        return self._as_frame(
            self.rq.get_price(
                order_book_ids,
                start_date=trading_date,
                end_date=trading_date,
                frequency="1d",
                adjust_type="none",
                skip_suspended=True,
                expect_df=True,
            )
        )

    def stock_minute(
        self, order_book_ids: list[str], trading_date: date
    ) -> pd.DataFrame:
        return self._as_frame(
            self.rq.get_price(
                order_book_ids,
                start_date=trading_date,
                end_date=trading_date,
                frequency="1m",
                adjust_type="none",
                skip_suspended=True,
                expect_df=True,
            )
        )

    def ex_factors(
        self, order_book_ids: list[str], start: date, end: date
    ) -> pd.DataFrame:
        return self._as_frame(
            self.rq.get_ex_factor(
                order_book_ids, start_date=start, end_date=end, market="cn"
            )
        )

    def splits(
        self, order_book_ids: list[str], start: date, end: date
    ) -> pd.DataFrame:
        return self._as_frame(
            self.rq.get_split(
                order_book_ids, start_date=start, end_date=end, market="cn"
            )
        )

    def stock_connect_holding_details(
        self, order_book_ids: list[str], start: date, end: date
    ) -> pd.DataFrame:
        return self._as_frame(
            self.rq.get_stock_connect_holding_details(
                order_book_ids, start_date=start, end_date=end
            )
        )

    def _fund_api(self) -> Any:
        if not hasattr(self.rq, "fund"):
            try:
                importlib.import_module("rqdatac_fund")
            except ImportError as exc:
                raise RuntimeError(
                    "fund.get_holdings requires rqdatac-fund==1.0.44"
                ) from exc
        fund = getattr(self.rq, "fund", None)
        if fund is None:
            raise RuntimeError("rqdatac_fund did not register rqdatac.fund")
        return fund

    def fund_instruments(self) -> pd.DataFrame:
        return self._as_frame(self._fund_api().all_instruments(market="cn"))

    def fund_holdings(
        self, fund_ids: list[str], start: date, end: date
    ) -> pd.DataFrame:
        # rqdatac_fund 1.0.44 supports range kwargs even though the public
        # signature documents only ``date``. A date query selects a report
        # period, not a PIT cutoff, so PIT must use returned release_date.
        return self._as_frame(
            self._fund_api().get_holdings(
                fund_ids, start_date=start, end_date=end, market="cn"
            )
        )

    def pit_financials(
        self,
        order_book_ids: list[str],
        fields: tuple[str, ...],
        start_quarter: str,
        end_quarter: str,
        query_date: date,
    ) -> pd.DataFrame:
        """Return all source disclosure versions for one financial field group."""

        return self._as_frame(
            self.rq.get_pit_financials_ex(
                order_book_ids=order_book_ids,
                fields=list(fields),
                start_quarter=start_quarter,
                end_quarter=end_quarter,
                date=query_date,
                statements="all",
                market="cn",
            )
        )

    def concept_catalog(self, start: date, end: date) -> Any:
        return self.rq.get_concept_list(start_date=start, end_date=end, market="cn")

    def concept_names(self, snapshot_date: date) -> list[str]:
        return list(self.rq.concept_list(date=snapshot_date, market="cn") or [])

    def concept_members(
        self, concepts: list[str], start: date, end: date
    ) -> pd.DataFrame:
        return self._as_frame(
            self.rq.get_concept(
                concepts, start_date=start, end_date=end, market="cn"
            )
        )

    def concept_snapshot(self, concept: str, snapshot_date: date) -> list[str]:
        return list(self.rq.concept(concept, date=snapshot_date, market="cn") or [])

    def industry_mapping(
        self, snapshot_date: date, source: str = "citics_2019"
    ) -> pd.DataFrame:
        return self._as_frame(
            self.rq.get_industry_mapping(
                source=source, date=snapshot_date, market="cn"
            )
        )

    def industry_changes(
        self, industry: str, level: int, source: str = "citics_2019"
    ) -> pd.DataFrame:
        return self._as_frame(
            self.rq.get_industry_change(
                industry=industry, source=source, level=level, market="cn"
            )
        )

    def citics_industries(
        self, order_book_ids: list[str], snapshot_date: date
    ) -> pd.DataFrame:
        return self._as_frame(
            self.rq.get_instrument_industry(
                order_book_ids,
                source="citics_2019",
                level=0,
                date=snapshot_date,
                market="cn",
            )
        )

    def shenwan_industries(
        self, order_book_ids: list[str], snapshot_date: date, level: int
    ) -> pd.DataFrame:
        return self._as_frame(
            self.rq.shenwan_instrument_industry(
                order_book_ids,
                date=snapshot_date,
                level=level,
                expect_df=True,
                market="cn",
            )
        )

    def sector_members(self, sector_code: str) -> list[str]:
        return list(self.rq.sector(sector_code, market="cn") or [])

    def instruments(self, snapshot_date: date) -> pd.DataFrame:
        return self._as_frame(self.rq.all_instruments(type="CS", date=snapshot_date))

    def option_instruments(self, snapshot_date: date) -> pd.DataFrame:
        return self._as_frame(
            self.rq.all_instruments(type="Option", date=snapshot_date, market="cn")
        )

    def option_contract_property(
        self, order_book_ids: list[str], start: date, end: date
    ) -> pd.DataFrame:
        return self._as_frame(
            self.rq.options.get_contract_property(
                order_book_ids,
                start_date=start,
                end_date=end,
                fields=[
                    "product_name",
                    "symbol",
                    "contract_multiplier",
                    "strike_price",
                ],
                market="cn",
            )
        )

    def option_daily(
        self, order_book_ids: list[str], start: date, end: date
    ) -> pd.DataFrame:
        return self._as_frame(
            self.rq.get_price(
                order_book_ids,
                start_date=start,
                end_date=end,
                frequency="1d",
                fields=[
                    "open",
                    "high",
                    "low",
                    "close",
                    "prev_close",
                    "volume",
                    "total_turnover",
                    "open_interest",
                    "strike_price",
                    "contract_multiplier",
                    "prev_settlement",
                    "settlement",
                    "limit_up",
                    "limit_down",
                    "day_session_open",
                ],
                adjust_type="none",
                expect_df=True,
                market="cn",
            )
        )

    def tick(self, order_book_id: str, trading_date: date) -> pd.DataFrame:
        return self._as_frame(
            self.rq.get_price(
                order_book_id,
                start_date=trading_date,
                end_date=trading_date,
                frequency="tick",
                adjust_type="none",
                expect_df=True,
            )
        )

    @staticmethod
    def _as_frame(value: Any) -> pd.DataFrame:
        if value is None:
            return pd.DataFrame()
        if isinstance(value, pd.Series):
            return value.to_frame()
        if isinstance(value, pd.DataFrame):
            return value.copy()
        return pd.DataFrame(value)
