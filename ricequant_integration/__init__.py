"""Independent RiceQuant/RQData ingestion package.

The package intentionally does not import :mod:`tushare_integration`; loading it
must never initialise Scrapy or read the production Tushare configuration.
"""

__version__ = "0.1.0"
