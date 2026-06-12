from __future__ import annotations

import pandas as pd

from tushare_integration.spiders.baostock.base import BaostockCodeListMixin, BaostockDailyRangeMixin, BaostockSpider


class BaostockIndexDailySpider(BaostockCodeListMixin, BaostockDailyRangeMixin, BaostockSpider):
    name = "baostock/index/daily"
    api_name = "query_history_k_data_plus"
    code_type = "2"
    custom_settings = {
        "TABLE_NAME": "baostock_index_daily",
        "SCHEMA_NAME": "baostock/index_daily",
        "MIN_CAL_DATE": "2015-01-01",
    }
    fields = "date,code,open,high,low,close,preclose,volume,amount,pctChg"

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

    def start_requests(self):
        yield self.get_local_request(self.parse_baostock)

    def parse_baostock(self, response):
        for data in self.iter_code_frames(self.query_daily, self.load_codes()):
            item = self.item_from_dataframe(data)
            if item is not None:
                yield item
