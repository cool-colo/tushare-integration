from tushare_integration.spiders.tushare import TushareSpider


class EtfBasicSpider(TushareSpider):
    name = "fund/basic/etf_basic"
    api_name = "etf_basic"

    def start_requests(self):
        # etf_basic 的入参均为可选，按交易所分别请求以覆盖沪深两市全部ETF，
        # 避免单次请求受接口默认返回条数限制而漏掉部分基金。
        for exchange in ["SH", "SZ"]:
            yield self.get_scrapy_request(params={"exchange": exchange})


class EtfIndexSpider(TushareSpider):
    name = "fund/basic/etf_index"
    api_name = "etf_index"

    def start_requests(self):
        yield self.get_scrapy_request(params={})
