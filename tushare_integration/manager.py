import json
import logging
import re
import signal
import uuid
from pathlib import Path

import scrapy.crawler
import scrapy.signals
import yaml
from scrapy.signalmanager import dispatcher

from tushare_integration.db_engine import DatabaseEngineFactory
from tushare_integration.reporters import ReporterLoader
from tushare_integration.settings import TushareIntegrationSettings


TUSHARE_RATE_LIMIT_MESSAGE_FRAGMENTS = (
    "频率超限",
    "rate limit",
)

DEFAULT_UPDATE_TYPE = "incremental"
UPDATE_TYPE_ALIASES = {
    "daily": "incremental",
    "incremental": "incremental",
    "full": "full",
    "fully": "full",
}
VALID_UPDATE_TYPES = set(UPDATE_TYPE_ALIASES.values())
LOCAL_FIRST_DEPENDENCY_TABLES = {
    "baostock/stock/basic": "baostock_stock_basic",
}
BAOSTOCK_BASIC_REQUIRED_CODE_TYPES = {
    "baostock/index/daily": {"2"},
}
DEFAULT_BAOSTOCK_BASIC_CODE_TYPES = {"1"}


class CrawlManager(object):
    def __init__(self):
        self.batch_id = uuid.uuid1().hex
        self.settings = TushareIntegrationSettings.model_validate(
            yaml.safe_load(open('config.yaml', 'r', encoding='utf8').read())
        )

        self.process = scrapy.crawler.CrawlerProcess(self.get_settings())

        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

        self.signals = []
        dispatcher.connect(self.append_signal, signal=scrapy.signals.item_error)
        dispatcher.connect(self.append_signal, signal=scrapy.signals.spider_error)

    def list_spiders(self, spider: str | None = None) -> list[str]:
        """
        列出所有spider
        :param spider: 通配符
        :return: spider列表
        """
        # 获取spiders列表
        spiders = self.process.spider_loader.list()
        # 过滤
        if spider:
            spiders = [s for s in spiders if re.fullmatch(spider, s)]
        return spiders

    @staticmethod
    def get_signal_name(scrapy_signal):
        if scrapy_signal == scrapy.signals.item_error:
            return "item_error"
        if scrapy_signal == scrapy.signals.spider_error:
            return "spider_error"
        return str(scrapy_signal)

    @staticmethod
    def get_failure_message(failure):
        if failure is None:
            return ""
        if getattr(failure, "value", None) is not None:
            return repr(failure.value)
        if hasattr(failure, "getErrorMessage"):
            return failure.getErrorMessage()
        return str(failure)

    @classmethod
    def describe_signal(cls, scrapy_signal):
        response = scrapy_signal.get("response")
        response_url = getattr(response, "url", "")
        response_params = getattr(response, "meta", {}).get("params", {}) if response else {}
        spider = scrapy_signal.get("spider")
        spider_name = getattr(spider, "name", "")
        failure_message = cls.get_failure_message(scrapy_signal.get("failure"))

        parts = [f"signal={cls.get_signal_name(scrapy_signal.get('signal'))}"]
        if spider_name:
            parts.append(f"spider={spider_name}")
        if response_url:
            parts.append(f"response={response_url}")
        if response_params:
            parts.append(f"params={response_params}")
        if failure_message:
            parts.append(f"error={failure_message}")
        return " ".join(parts)

    @classmethod
    def is_rate_limit_signal(cls, scrapy_signal) -> bool:
        failure_message = cls.get_failure_message(scrapy_signal.get("failure"))
        if any(fragment in failure_message for fragment in TUSHARE_RATE_LIMIT_MESSAGE_FRAGMENTS):
            return True

        response = scrapy_signal.get("response")
        response_text = getattr(response, "text", None)
        if not response_text:
            return False

        try:
            payload = json.loads(response_text)
            code = int(payload.get("code", 0))
        except (json.JSONDecodeError, TypeError, ValueError):
            return False
        return code // 100 == 402

    def append_signal(self, signal, sender=None, item=None, response=None, spider=None, failure=None, **kwargs):
        if not any(
            [
                s['signal'] == signal
                and s['spider'] == spider
                and self.get_failure_message(s.get('failure')) == self.get_failure_message(failure)
                for s in self.signals
            ]
        ):
            self.signals.append(
                {
                    'signal': signal,
                    'sender': sender,
                    'item': item,
                    'response': response,
                    'spider': spider,
                    'failure': failure,
                }
            )

    def get_settings(self):
        settings = self.settings.get_settings()
        settings['LOG_LEVEL'] = 'INFO'
        settings['BATCH_ID'] = self.batch_id
        return settings

    def get_dependency_db_engine(self):
        if not hasattr(self, "_dependency_db_engine"):
            self._dependency_db_engine = DatabaseEngineFactory.create(self.settings)
        return self._dependency_db_engine

    @classmethod
    def get_required_baostock_basic_code_types(cls, spiders: list[str]) -> set[str]:
        required_code_types: set[str] = set()
        for spider in spiders:
            required_code_types.update(
                BAOSTOCK_BASIC_REQUIRED_CODE_TYPES.get(spider, DEFAULT_BAOSTOCK_BASIC_CODE_TYPES)
            )
        return required_code_types

    def local_dependency_has_rows(self, dependency: str, spiders: list[str] | None = None) -> bool:
        table_name = LOCAL_FIRST_DEPENDENCY_TABLES.get(dependency)
        if table_name is None:
            return False
        required_code_types = (
            self.get_required_baostock_basic_code_types(spiders)
            if spiders
            else set(DEFAULT_BAOSTOCK_BASIC_CODE_TYPES)
        )
        code_types_sql = ", ".join(f"'{code_type}'" for code_type in sorted(required_code_types))

        db_name = self.settings.database.db_name
        table_expr = f"{db_name}.{table_name}"
        if self.settings.database.db_type == "clickhouse":
            table_expr = f"{table_expr} FINAL"

        try:
            data = self.get_dependency_db_engine().query_df(
                f"""
                SELECT `type`, count(*) AS row_count
                FROM {table_expr}
                WHERE `type` IN ({code_types_sql})
                  AND code != ''
                GROUP BY `type`
                """
            )
        except Exception as exc:
            logging.info("Local dependency %s is unavailable; keeping dependency crawl: %s", dependency, exc)
            return False

        if data.empty or "type" not in data.columns or "row_count" not in data.columns:
            return False
        row_count_by_type = {
            str(row["type"]): int(row["row_count"] or 0)
            for row in data[["type", "row_count"]].to_dict("records")
        }
        missing_code_types = [
            code_type for code_type in sorted(required_code_types) if row_count_by_type.get(code_type, 0) <= 0
        ]
        if missing_code_types:
            return False

        logging.info(
            "Skipping dependency %s because local table %s has rows for code types %s",
            dependency,
            table_name,
            ",".join(sorted(required_code_types)),
        )
        return True

    @staticmethod
    def get_dependencies(spiders: list[str]) -> list[str]:
        dependencies = []
        for spider in spiders:
            schema_path = Path(f"tushare_integration/schema/{spider}.yaml")
            if not schema_path.exists() and spider.startswith("baostock/"):
                parts = spider.split("/")
                if len(parts) == 3:
                    schema_path = Path(f"tushare_integration/schema/{parts[0]}/{parts[1]}_{parts[2]}.yaml")
            with open(schema_path, 'r', encoding='utf8') as f:
                schema = yaml.safe_load(f.read())
            dependencies.extend(schema.get('dependencies', []))
        return list(dict.fromkeys(dependencies))

    def get_required_dependencies(self, spiders: list[str]) -> list[str]:
        return [
            dependency
            for dependency in self.get_dependencies(spiders)
            if not self.local_dependency_has_rows(dependency, spiders)
        ]

    @staticmethod
    def normalize_update_type(update_type: str | None) -> str | None:
        if update_type is None:
            return None

        normalized = UPDATE_TYPE_ALIASES.get(update_type.strip().lower())
        if normalized is None:
            valid_values = ", ".join(sorted(VALID_UPDATE_TYPES | set(UPDATE_TYPE_ALIASES.keys())))
            raise ValueError(f"Unsupported update_type {update_type!r}; expected one of: {valid_values}")
        return normalized

    @classmethod
    def get_job_spider_update_types(cls, job: dict, spider: dict) -> set[str]:
        update_types = spider.get("update_types", spider.get("update_type", job.get("update_type", DEFAULT_UPDATE_TYPE)))
        if isinstance(update_types, str):
            update_types = [update_types]

        return {cls.normalize_update_type(update_type) for update_type in update_types}

    @classmethod
    def spider_matches_update_type(cls, job: dict, spider: dict, update_type: str | None) -> bool:
        if spider.get("enabled", True) is False:
            return False

        normalized_update_type = cls.normalize_update_type(update_type)
        if normalized_update_type is None:
            return True
        return normalized_update_type in cls.get_job_spider_update_types(job, spider)

    @classmethod
    def filter_job_spiders_by_update_type(cls, job: dict, update_type: str | None) -> list[dict]:
        return [
            spider
            for spider in job.get("spiders", [])
            if cls.spider_matches_update_type(job, spider, update_type)
        ]

    def get_spiders_by_job(self, job_name: str, update_type: str | None = None) -> list[str]:
        with open("jobs.yaml", 'r', encoding='utf8') as f:
            jobs = yaml.safe_load(f.read())
        for job in jobs['cronjob']:
            if job['name'] == job_name:
                selected_spiders = []
                for spider in self.filter_job_spiders_by_update_type(job, update_type):
                    for spider_name in self.list_spiders(spider['name']):
                        if spider_name not in selected_spiders:
                            selected_spiders.append(spider_name)
                return selected_spiders
        raise ValueError(f"Job {job_name} not found")

    def run_spiders_in_sequence(self, spiders: list[str]):
        logging.info("Running spiders in sequence: %s", spiders)

        if len(spiders) == 0:
            return

        deferred = self.process.crawl(spiders[0])
        if len(spiders) > 1:
            deferred.addCallback(lambda _: self.run_spiders_in_sequence(spiders[1:]))

    def run_job(self, job_name: str, update_type: str | None = None):
        spiders = self.get_spiders_by_job(job_name, update_type=update_type)
        all_spiders = self.get_all_spiders(spiders)

        if len(all_spiders) == 0:
            logging.info("No spiders matched job=%s update_type=%s; skipping crawl.", job_name, update_type)
            return

        self.run_spiders_in_sequence(all_spiders)
        self.process.start()

        self.report()
        # 如果有异常就抛出
        self.raise_for_signal()

    def run_spider(self, spider: str):
        spiders = self.list_spiders(spider)
        all_spiders = self.get_all_spiders(spiders)

        self.run_spiders_in_sequence(all_spiders)
        self.process.start()

        self.report()
        # 如果有异常就抛出
        self.raise_for_signal()

    def get_all_spiders(self, spiders):
        dependencies = [spiders]
        # 采集服务不是并发安全的，开启依赖解析的情况下可能会导致数据出现重复等问题
        if not self.settings.parallel_mode:
            while True:
                required_dependencies = self.get_required_dependencies(dependencies[-1])
                if not required_dependencies:
                    break
                dependencies.append(required_dependencies)
        all_spiders = []
        # 从列表最后一个开始，因为最后一个是最底层的依赖
        for dependency in reversed(dependencies):
            for spider in dependency:
                if spider not in all_spiders:
                    all_spiders.append(spider)
        return all_spiders

    def raise_for_signal(self):
        fatal_signals = [scrapy_signal for scrapy_signal in self.signals if not self.is_rate_limit_signal(scrapy_signal)]
        if fatal_signals:
            signal_details = "\n".join([self.describe_signal(scrapy_signal) for scrapy_signal in fatal_signals])
            raise RuntimeError(f"Scrapy signals captured:\n{signal_details}")

        for scrapy_signal in self.signals:
            logging.warning("Non-fatal Scrapy signal captured: %s", self.describe_signal(scrapy_signal))

    def get_report_content(self):
        content = f"批次ID：{self.batch_id}\n"

        db_engine = DatabaseEngineFactory.create(self.settings)

        for index, row in db_engine.query_df(
            f"select description,count from {self.settings.database.db_name}.tushare_integration_log "
            f"where batch_id = '{self.batch_id}'"
        ).iterrows():
            content += f"爬虫名称:{row['description']}  数据数量:{row['count']}\n"

        if self.signals:
            content += "警告信息：\n"
            for scrapy_signal in self.signals:
                if scrapy_signal['signal'] == scrapy.signals.item_error:
                    content += f"爬虫名称:{scrapy_signal['spider'].name} 警告信息:{self.describe_signal(scrapy_signal)}\n"
                elif scrapy_signal['signal'] == scrapy.signals.spider_error:
                    content += f"爬虫名称:{scrapy_signal['spider'].name} 警告信息:{self.describe_signal(scrapy_signal)}\n"
        return content

    def report(self):
        reporter_loader = ReporterLoader(self.get_settings())

        for reporter in reporter_loader.get_reporters():
            reporter.send_report(subject='数据更新通知', content=self.get_report_content())

    def stop(self, signum, frame):
        logging.info("caught stop signal, stopping...")
        self.process.stop()
