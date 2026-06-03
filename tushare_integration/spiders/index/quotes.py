import datetime

from tushare_integration.spiders.stock.quotes import StockMonthlySpider, StockWeeklySpider
from tushare_integration.spiders.tushare import DailySpider


class IndexDailySpider(DailySpider):
    name = "index/quotes/index_daily"
    custom_settings = {"TABLE_NAME": "index_daily", "BASIC_TABLE": "index_basic", "MIN_CAL_DATE": "1990-12-19"}

    @staticmethod
    def index_existed_on_date(index_row, trade_date: datetime.date) -> bool:
        list_date = DailySpider.parse_date_value(getattr(index_row, "list_date", None))
        base_date = DailySpider.parse_date_value(getattr(index_row, "base_date", None))
        exp_date = DailySpider.parse_date_value(getattr(index_row, "exp_date", None))

        start_date = list_date or base_date
        if start_date and start_date > trade_date:
            return False

        if exp_date and exp_date != datetime.date(1970, 1, 1) and exp_date < trade_date:
            return False

        return True

    @staticmethod
    def get_request_end_date() -> datetime.date:
        return datetime.date.today()

    def start_requests(self):
        conn = self.get_db_engine()
        db_name = self.spider_settings.database.db_name
        table_name = self.get_table_name()
        start_date = self.get_incremental_start_date(conn, "trade_date")
        end_date = self.get_request_end_date()

        if start_date > end_date:
            return

        trade_dates = conn.query_df(
            f"""
                SELECT DISTINCT cal_date
                FROM {db_name}.trade_cal
                WHERE is_open = 1
                  AND cal_date >= '{start_date}'
                  AND cal_date <= '{end_date}'
                  AND exchange = 'SSE'
                ORDER BY cal_date
                """
        )
        if trade_dates.empty:
            return

        index_list = conn.query_df(
            f"""
                SELECT ts_code, base_date, list_date, exp_date
                FROM {db_name}.{self.custom_settings.get('BASIC_TABLE')}
                WHERE ts_code != ''
                ORDER BY ts_code
                """
        )
        if index_list.empty:
            return

        existing_data = conn.query_df(
            f"""
                SELECT DISTINCT ts_code, trade_date
                FROM {db_name}.{table_name}
                WHERE trade_date >= '{start_date}'
                """
        )
        existing_keys = {
            (ts_code, self.parse_date_value(trade_date))
            for ts_code, trade_date in existing_data[["ts_code", "trade_date"]].itertuples(index=False)
        }

        for trade_date_value in trade_dates["cal_date"]:
            trade_date = self.parse_date_value(trade_date_value)
            if trade_date is None:
                continue

            for index_row in index_list.itertuples(index=False):
                if not self.index_existed_on_date(index_row, trade_date):
                    continue
                if (index_row.ts_code, trade_date) in existing_keys:
                    continue
                yield self.get_scrapy_request(
                    params={"ts_code": index_row.ts_code, "trade_date": trade_date.strftime("%Y%m%d")}
                )


class DailyInfoSpider(DailySpider):
    name = "index/quotes/daily_info"
    custom_settings = {"TABLE_NAME": "daily_info", "MIN_CAL_DATE": "1990-12-19"}


# noinspection SpellCheckingInspection
class IndexDailyBasicSpider(DailySpider):
    name = "index/quotes/index_dailybasic"
    custom_settings = {"TABLE_NAME": "index_dailybasic", "MIN_CAL_DATE": "2004-01-02"}


class IndexGlobalSpider(DailySpider):
    name = "index/quotes/index_global"
    custom_settings = {"TABLE_NAME": "index_global", "MIN_CAL_DATE": "1990-12-19"}


class IndexMonthlySpider(StockMonthlySpider):
    name = "index/quotes/index_monthly"
    custom_settings = {"TABLE_NAME": "index_monthly"}


class IndexWeeklySpider(StockWeeklySpider):
    name = "index/quotes/index_weekly"
    custom_settings = {"TABLE_NAME": "index_weekly"}


class IndexWeightSpider(DailySpider):
    name = "index/quotes/index_weight"
    custom_settings = {
        "TABLE_NAME": "index_weight",
        "BASIC_TABLE": "index_basic",
        "MIN_CAL_DATE": "2005-04-08",  # 根据实际数据情况设置合适的起始日期
    }

    @staticmethod
    def iter_month_ranges(start_date: datetime.date, end_date: datetime.date):
        month_start = start_date.replace(day=1)
        while month_start <= end_date:
            if month_start.month == 12:
                next_month = datetime.date(month_start.year + 1, 1, 1)
            else:
                next_month = datetime.date(month_start.year, month_start.month + 1, 1)

            month_end = min(next_month - datetime.timedelta(days=1), end_date)
            yield month_start, month_end
            month_start = next_month

    @staticmethod
    def index_existed_in_month(index_row, month_start: datetime.date, month_end: datetime.date) -> bool:
        list_date = DailySpider.parse_date_value(getattr(index_row, "list_date", None))
        base_date = DailySpider.parse_date_value(getattr(index_row, "base_date", None))
        exp_date = DailySpider.parse_date_value(getattr(index_row, "exp_date", None))

        start_date = list_date or base_date
        if start_date and start_date > month_end:
            return False

        if exp_date and exp_date != datetime.date(1970, 1, 1) and exp_date < month_start:
            return False

        return True

    @staticmethod
    def get_request_end_date() -> datetime.date:
        return datetime.date.today()

    def start_requests(self):
        conn = self.get_db_engine()
        db_name = self.spider_settings.database.db_name
        start_date = self.get_incremental_start_date(conn, "trade_date")
        end_date = self.get_request_end_date()

        index_list = conn.query_df(
            f"""
                SELECT ts_code, base_date, list_date, exp_date
                FROM {db_name}.{self.custom_settings.get('BASIC_TABLE')}
                WHERE ts_code != ''
                ORDER BY ts_code
                """
        )

        if index_list.empty or start_date > end_date:
            return

        month_ranges = list(self.iter_month_ranges(start_date, end_date))
        for index_row in index_list.itertuples(index=False):
            for month_start, month_end in month_ranges:
                if not self.index_existed_in_month(index_row, month_start, month_end):
                    continue

                yield self.get_scrapy_request(
                    params={
                        "index_code": index_row.ts_code,
                        "start_date": month_start.strftime("%Y%m%d"),
                        "end_date": month_end.strftime("%Y%m%d"),
                    }
                )


class SzDailyInfoSpider(DailySpider):
    name = "index/quotes/sz_daily_info"
    custom_settings = {"TABLE_NAME": "sz_daily_info", "MIN_CAL_DATE": "2008-01-02"}
