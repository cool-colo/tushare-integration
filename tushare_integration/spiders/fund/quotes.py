from tushare_integration.spiders.tushare import DailySpider


class FundDailySpider(DailySpider):
    name = "fund/quotes/fund_daily"
    api_name = "fund_daily"
    custom_settings = {"TABLE_NAME": "fund_daily", "MIN_CAL_DATE": "2004-01-01"}


class FundAdjSpider(DailySpider):
    name = "fund/quotes/fund_adj"
    api_name = "fund_adj"
    custom_settings = {"TABLE_NAME": "fund_adj", "MIN_CAL_DATE": "2004-01-01"}


class EtfLimitSpider(DailySpider):
    name = "fund/quotes/etf_limit"
    api_name = "etf_limit"
    custom_settings = {"TABLE_NAME": "etf_limit", "MIN_CAL_DATE": "2004-01-01"}
