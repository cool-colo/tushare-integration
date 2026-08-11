import logging
from urllib import request
from venv import logger
import pandas as pd

from tushare_integration.spiders.tushare import DailySpider, TushareSpider
from tushare_integration.items import TushareIntegrationItem


class IndexClassifySpider(TushareSpider):
    name = "index/sw/index_classify"
    custom_settings = {"TABLE_NAME": "index_classify"}


class IndexMemberSpider(TushareSpider):
    name = "index/sw/index_member"
    custom_settings = {"TABLE_NAME": "index_member"}

    def start_requests(self):
        # 从index_classify表中获取所有的index_code，然后构造请求
        df = self.get_db_engine().query_df("select distinct index_code from index_classify")

        for index_code in df["index_code"]:
            yield self.get_scrapy_request(
                params={
                    'index_code': index_code,
                }
            )


class IndexMemberAllSpider(TushareSpider):
    name = "index/sw/index_member_all"
    custom_settings = {"TABLE_NAME": "index_member_all"}

    # 官方单次最大2000行(doc_id=335),超过会被静默截断导致漏行
    PAGE_LIMIT = 2000

    def start_requests(self):
        # is_new默认为'Y'(仅当前成分),必须同时显式采集'N'(历史已剔除,带真实out_date)
        # 首页先用scrapy请求触发,剩余页在parse中通过request_with_requests串行翻页
        request = self.get_scrapy_request(params={'is_new': 'Y', 'offset': 0, 'limit': self.PAGE_LIMIT})
        request.meta.update({'is_new': 'Y', 'offset': 0, 'limit': self.PAGE_LIMIT})
        yield request

    def parse(self, response, **kwargs):
        all_data = []
        first_page = self.parse_response(response, **kwargs)
        if not first_page["data"].empty:
            all_data.append(first_page["data"])

        # 'Y'首页已在scrapy请求中取过,从第二页(offset=PAGE_LIMIT)继续;'N'从头开始
        for is_new, start_offset in (('Y', self.PAGE_LIMIT), ('N', 0)):
            offset = start_offset
            while True:
                parsed_data = self.request_with_requests(
                    params={'is_new': is_new, 'offset': offset, 'limit': self.PAGE_LIMIT}
                )
                if parsed_data["data"].empty:
                    break
                all_data.append(parsed_data["data"])
                offset += self.PAGE_LIMIT

        if not all_data:
            return None

        return TushareIntegrationItem(data=pd.concat(all_data, ignore_index=True))


class SWDailySpider(DailySpider):
    name = "index/sw/sw_daily"
    custom_settings = {"TABLE_NAME": "sw_daily"}
