from __future__ import annotations

import datetime

import pandas as pd
from tushare_integration.spiders.baostock.base import (
    BaostockCodeListMixin,
    BaostockDailyRangeMixin,
    BaostockQuotaExceeded,
    BaostockRequestFailed,
    BaostockDirectSpider,
    BaostockSpider,
)
from tushare_integration.spiders.baostock.utils import parse_date_value


class BaostockStockBasicSpider(BaostockDirectSpider):
    name = "baostock/stock/basic"
    api_name = "query_stock_basic"
    query_method = "query_stock_basic"
    custom_settings = {"TABLE_NAME": "baostock_stock_basic", "SCHEMA_NAME": "baostock/stock_basic"}


class BaostockStockIndustrySpider(BaostockDirectSpider):
    name = "baostock/stock/industry"
    api_name = "query_stock_industry"
    query_method = "query_stock_industry"
    custom_settings = {"TABLE_NAME": "baostock_stock_industry", "SCHEMA_NAME": "baostock/stock_industry"}


class BaostockTradeDatesSpider(BaostockSpider):
    name = "baostock/stock/trade_dates"
    api_name = "query_trade_dates"
    date_field = "calendar_date"
    custom_settings = {
        "TABLE_NAME": "baostock_trade_dates",
        "SCHEMA_NAME": "baostock/stock_trade_dates",
        "MIN_CAL_DATE": "2015-01-01",
    }

    def start_requests(self):
        yield self.get_local_request(self.parse_baostock)

    def get_request_date_range(self) -> tuple[datetime.date, datetime.date] | None:
        end_date = datetime.date.today()
        row_count, latest_date = self.get_incremental_date_state(self.date_field)
        if row_count == 0 or latest_date is None:
            start_date = self.get_start_date()
        else:
            start_date = max(self.get_start_date(), latest_date + datetime.timedelta(days=1))
        if start_date > end_date:
            return None
        return start_date, end_date

    def parse_baostock(self, response):
        date_range = self.get_request_date_range()
        if date_range is None:
            self.logger.info("Baostock trade calendar is already up to date in local database")
            return
        start_date, end_date = date_range
        try:
            item = self.item_from_dataframe(
                self.get_client().query(
                    "query_trade_dates",
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat(),
                )
            )
        except (BaostockQuotaExceeded, BaostockRequestFailed) as exc:
            self.logger.warning("Skipping %s because %s", self.name, exc)
            return
        if item is not None:
            yield item


class BaostockStockDailySpider(BaostockCodeListMixin, BaostockDailyRangeMixin, BaostockSpider):
    name = "baostock/stock/daily"
    api_name = "query_history_k_data_plus"
    code_list_fields = ("code", "outDate")
    custom_settings = {
        "TABLE_NAME": "baostock_stock_daily",
        "SCHEMA_NAME": "baostock/stock_daily",
        "MIN_CAL_DATE": "2015-01-01",
    }

    fields = (
        "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,"
        "tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
    )

    def query_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self.get_client().query(
            "query_history_k_data_plus",
            code=code,
            fields=self.fields,
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="3",
        )

    def get_code_request_end_date(self, code: str | None = None) -> datetime.date:
        end_date = super().get_code_request_end_date(code)
        delist_date = self.get_code_delist_date(code)
        if delist_date is None:
            return end_date
        return min(end_date, delist_date)

    def start_requests(self):
        yield self.get_local_request(self.parse_baostock)

    def parse_baostock(self, response):
        for data in self.iter_code_frames(self.query_daily, self.load_codes()):
            item = self.item_from_dataframe(data)
            if item is not None:
                yield item


class BaostockFinancialSpider(BaostockCodeListMixin, BaostockSpider):
    query_method: str
    code_list_fields = ("code", "ipoDate", "outDate")

    @staticmethod
    def iter_year_quarters(start_year: int = 2015):
        current_year = datetime.date.today().year
        for year in range(start_year, current_year + 1):
            for quarter in range(1, 5):
                yield year, quarter

    @staticmethod
    def quarter_end_date(year: int, quarter: int) -> datetime.date:
        month_day_by_quarter = {
            1: (3, 31),
            2: (6, 30),
            3: (9, 30),
            4: (12, 31),
        }
        month, day = month_day_by_quarter[quarter]
        return datetime.date(year, month, day)

    def get_existing_stat_dates(self, code: str) -> set[datetime.date]:
        db_name = self.spider_settings.database.db_name
        table_expr = f"{db_name}.{self.get_table_name()}"
        if self.spider_settings.database.db_type == "clickhouse":
            table_expr = f"{table_expr} FINAL"
        escaped_code = code.replace("'", "''")

        try:
            data = self.get_db_engine().query_df(
                f"""
                SELECT DISTINCT `statDate`
                FROM {table_expr}
                WHERE `code` = '{escaped_code}'
                  AND `statDate` >= '{self.get_start_date().isoformat()}'
                  AND `statDate` > '1970-01-01'
                """
            )
        except Exception as exc:
            self.logger.warning(
                "Failed to load existing Baostock financial quarters for %s code=%s; falling back to full code range: %s",
                self.name,
                code,
                exc,
            )
            return set()

        if data.empty or "statDate" not in data.columns:
            return set()
        return {value for value in (parse_date_value(value) for value in data["statDate"]) if value is not None}

    def iter_code_year_quarters(self, code: str):
        ipo_date = self.get_code_ipo_date(code)
        delist_date = self.get_code_delist_date(code)
        existing_stat_dates = self.get_existing_stat_dates(code)
        today = datetime.date.today()
        for year, quarter in self.iter_year_quarters(self.get_start_date().year):
            quarter_end = self.quarter_end_date(year, quarter)
            if quarter_end > today:
                break
            if ipo_date is not None and quarter_end < ipo_date:
                continue
            if delist_date is not None and quarter_end > delist_date:
                break
            if quarter_end in existing_stat_dates:
                continue
            yield year, quarter

    def query_financial(self, code: str, year: int, quarter: int) -> pd.DataFrame:
        return self.get_client().query(self.query_method, code=code, year=year, quarter=quarter)

    def start_requests(self):
        yield self.get_local_request(self.parse_baostock)

    def parse_baostock(self, response):
        frames = []
        for code in self.load_codes():
            for year, quarter in self.iter_code_year_quarters(code):
                try:
                    frames.append(self.query_financial(code, year, quarter))
                except BaostockQuotaExceeded as exc:
                    self.logger.warning("Stopping %s because %s", self.name, exc)
                    item = self.item_from_dataframe(self.merge_frames(frames))
                    if item is not None:
                        yield item
                    return
                except BaostockRequestFailed as exc:
                    self.logger.warning(
                        "Skipping Baostock request for %s code=%s year=%s quarter=%s because %s",
                        self.name,
                        code,
                        year,
                        quarter,
                        exc,
                    )
                    continue
        item = self.item_from_dataframe(self.merge_frames(frames))
        if item is not None:
            yield item


class BaostockStockBalanceSpider(BaostockFinancialSpider):
    name = "baostock/stock/balance"
    api_name = "query_balance_data"
    query_method = "query_balance_data"
    custom_settings = {
        "TABLE_NAME": "baostock_stock_balance",
        "SCHEMA_NAME": "baostock/stock_balance",
        "MIN_CAL_DATE": "2015-01-01",
    }


class BaostockStockProfitSpider(BaostockFinancialSpider):
    name = "baostock/stock/profit"
    api_name = "query_profit_data"
    query_method = "query_profit_data"
    custom_settings = {
        "TABLE_NAME": "baostock_stock_profit",
        "SCHEMA_NAME": "baostock/stock_profit",
        "MIN_CAL_DATE": "2015-01-01",
    }


class BaostockStockCashFlowSpider(BaostockFinancialSpider):
    name = "baostock/stock/cash_flow"
    api_name = "query_cash_flow_data"
    query_method = "query_cash_flow_data"
    custom_settings = {
        "TABLE_NAME": "baostock_stock_cash_flow",
        "SCHEMA_NAME": "baostock/stock_cash_flow",
        "MIN_CAL_DATE": "2015-01-01",
    }


class BaostockStockDupontSpider(BaostockFinancialSpider):
    name = "baostock/stock/dupont"
    api_name = "query_dupont_data"
    query_method = "query_dupont_data"
    custom_settings = {
        "TABLE_NAME": "baostock_stock_dupont",
        "SCHEMA_NAME": "baostock/stock_dupont",
        "MIN_CAL_DATE": "2015-01-01",
    }


class BaostockStockOperationSpider(BaostockFinancialSpider):
    name = "baostock/stock/operation"
    api_name = "query_operation_data"
    query_method = "query_operation_data"
    custom_settings = {
        "TABLE_NAME": "baostock_stock_operation",
        "SCHEMA_NAME": "baostock/stock_operation",
        "MIN_CAL_DATE": "2015-01-01",
    }


class BaostockStockGrowthSpider(BaostockFinancialSpider):
    name = "baostock/stock/growth"
    api_name = "query_growth_data"
    query_method = "query_growth_data"
    custom_settings = {
        "TABLE_NAME": "baostock_stock_growth",
        "SCHEMA_NAME": "baostock/stock_growth",
        "MIN_CAL_DATE": "2015-01-01",
    }


class BaostockStockDebtSpider(BaostockFinancialSpider):
    name = "baostock/stock/debt"
    api_name = "query_debtpaying_data"
    query_method = "query_debtpaying_data"
    custom_settings = {
        "TABLE_NAME": "baostock_stock_debt",
        "SCHEMA_NAME": "baostock/stock_debt",
        "MIN_CAL_DATE": "2015-01-01",
    }


class BaostockStockExpressSpider(BaostockFinancialSpider):
    name = "baostock/stock/express"
    api_name = "query_performance_express_report"
    query_method = "query_performance_express_report"
    custom_settings = {
        "TABLE_NAME": "baostock_stock_express",
        "SCHEMA_NAME": "baostock/stock_express",
        "MIN_CAL_DATE": "2015-01-01",
    }


class BaostockStockFinancialIndicatorSpider(BaostockCodeListMixin, BaostockSpider):
    name = "baostock/stock/financial_indicator"
    code_list_fields = ("code", "ipoDate", "outDate")
    custom_settings = {
        "TABLE_NAME": "baostock_stock_financial_indicator",
        "SCHEMA_NAME": "baostock/stock_financial_indicator",
        "MIN_CAL_DATE": "2015-01-01",
    }
    indicator_methods = [
        "query_profit_data",
        "query_operation_data",
        "query_growth_data",
        "query_debtpaying_data",
        "query_cash_flow_data",
        "query_dupont_data",
    ]

    @staticmethod
    def iter_year_quarters(start_year: int = 2015):
        current_year = datetime.date.today().year
        for year in range(start_year, current_year + 1):
            for quarter in range(1, 5):
                yield year, quarter

    def iter_code_year_quarters(self, code: str):
        ipo_date = self.get_code_ipo_date(code)
        delist_date = self.get_code_delist_date(code)
        existing_stat_dates = BaostockFinancialSpider.get_existing_stat_dates(self, code)
        today = datetime.date.today()
        for year, quarter in self.iter_year_quarters(self.get_start_date().year):
            quarter_end = BaostockFinancialSpider.quarter_end_date(year, quarter)
            if quarter_end > today:
                break
            if ipo_date is not None and quarter_end < ipo_date:
                continue
            if delist_date is not None and quarter_end > delist_date:
                break
            if quarter_end in existing_stat_dates:
                continue
            yield year, quarter

    def start_requests(self):
        yield self.get_local_request(self.parse_baostock)

    def parse_baostock(self, response):
        rows: dict[tuple[str, str], dict] = {}
        for code in self.load_codes():
            for year, quarter in self.iter_code_year_quarters(code):
                for method_name in self.indicator_methods:
                    try:
                        frame = self.get_client().query(method_name, code=code, year=year, quarter=quarter)
                    except BaostockQuotaExceeded as exc:
                        self.logger.warning("Stopping %s because %s", self.name, exc)
                        item = self.item_from_dataframe(pd.DataFrame(list(rows.values())))
                        if item is not None:
                            yield item
                        return
                    except BaostockRequestFailed as exc:
                        self.logger.warning(
                            "Skipping Baostock request for %s method=%s code=%s year=%s quarter=%s because %s",
                            self.name,
                            method_name,
                            code,
                            year,
                            quarter,
                            exc,
                        )
                        continue
                    for row in frame.to_dict("records"):
                        stat_date = row.get("statDate")
                        if not stat_date:
                            continue
                        key = (row.get("code") or code, stat_date)
                        rows.setdefault(key, {}).update(row)

        item = self.item_from_dataframe(pd.DataFrame(list(rows.values())))
        if item is not None:
            yield item
