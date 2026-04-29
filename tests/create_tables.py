import logging
import os
import sys

import yaml

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tushare_integration.db_engine import DatabaseEngineFactory
from tushare_integration.manager import CrawlManager
from tushare_integration.settings import TushareIntegrationSettings
from tushare_integration.storage import build_latest_schema, build_raw_schema, get_latest_table_name, get_raw_table_name


def main():
    manager = CrawlManager()
    settings = TushareIntegrationSettings.model_validate(yaml.safe_load(open('config.yaml', 'r', encoding='utf-8')))
    for spider in manager.list_spiders('.*'):
        spider_cls = manager.process.spider_loader.load(spider)
        table_name = spider_cls.custom_settings.get("TABLE_NAME", spider.split('/')[-1])

        schema = yaml.safe_load(open(f"tushare_integration/schema/{spider}.yaml", "r", encoding="utf-8").read())
        db_engine = DatabaseEngineFactory.create(settings)
        try:
            logging.info(f"Creating tables {get_latest_table_name(table_name)} and {get_raw_table_name(table_name)}")
            db_engine.create_table(get_latest_table_name(table_name), build_latest_schema(schema))
            db_engine.create_table(get_raw_table_name(table_name), build_raw_schema(schema))
        except Exception as e:
            print(spider, e)


if __name__ == '__main__':
    main()
