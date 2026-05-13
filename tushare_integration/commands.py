import typer

from tushare_integration.dwd import DWDManager
from tushare_integration.dws import DWSManager
from tushare_integration.manager import CrawlManager
from tushare_integration.quality import QualityManager, ValidationMode

try:
    from rich import print
except ImportError:
    pass

crawl_app = typer.Typer(name='CrawlManager', help='CrawlManager help', no_args_is_help=True)

query_app = typer.Typer(
    name='QueryManager',
    help='QueryManager help',
    no_args_is_help=True,
)

dwd_app = typer.Typer(
    name='DWDManager',
    help='DWDManager help',
    no_args_is_help=True,
)

dws_app = typer.Typer(
    name='DWSManager',
    help='DWSManager help',
    no_args_is_help=True,
)

quality_app = typer.Typer(
    name='QualityManager',
    help='QualityManager help',
    no_args_is_help=True,
)


def _resolve_validation_mode(skip_validation: bool, validation_mode: str | None) -> ValidationMode | None:
    if skip_validation:
        return "skip"
    if validation_mode is None:
        return None
    if validation_mode not in {"strict", "warn_only", "skip"}:
        raise typer.BadParameter("validation mode must be one of: strict, warn_only, skip")
    return validation_mode  # type: ignore[return-value]


@query_app.command('list', help="List spiders")
def list_spiders():
    manager = CrawlManager()
    print(manager.list_spiders())


@dwd_app.command('list', help="List DWD tables")
def list_dwd_tables():
    manager = DWDManager()
    print(manager.list_tables())


@dwd_app.command('create', help="Create a DWD table", no_args_is_help=True)
def create_dwd_table(
    table_name: str = typer.Argument(..., help="DWD table name, e.g. dwd_stock_eod_price"),
):
    manager = DWDManager()
    manager.create_table(table_name)


@dwd_app.command('sync', help="Sync ODS raw tables to DWD", no_args_is_help=True)
def sync_dwd_table(
    table_name: str = typer.Argument(..., help="DWD table name or all"),
    skip_validation: bool = typer.Option(False, "--skip-validation", help="Temporarily skip validation"),
    validation_mode: str | None = typer.Option(
        None,
        "--validation-mode",
        help="Override validation mode: strict, warn_only, or skip",
    ),
):
    manager = DWDManager()
    resolved_mode = _resolve_validation_mode(skip_validation, validation_mode)
    if table_name == 'all':
        manager.sync_all(validation_mode=resolved_mode, skip_validation=skip_validation)
        return
    manager.sync_table(table_name, validation_mode=resolved_mode, skip_validation=skip_validation)


@dwd_app.command('sql', help="Render DWD sync SQL", no_args_is_help=True)
def render_dwd_sql(
    table_name: str = typer.Argument(..., help="DWD table name, e.g. dwd_stock_eod_price"),
):
    manager = DWDManager()
    print(manager.render_sync_sql(table_name))


@dws_app.command('list', help="List DWS tables")
def list_dws_tables():
    manager = DWSManager()
    print(manager.list_tables())


@dws_app.command('create', help="Create a DWS table", no_args_is_help=True)
def create_dws_table(
    table_name: str = typer.Argument(..., help="DWS table name, e.g. dws_stock_factor_wide"),
):
    manager = DWSManager()
    manager.create_table(table_name)


@dws_app.command('sync', help="Sync DWD tables to DWS", no_args_is_help=True)
def sync_dws_table(
    table_name: str = typer.Argument(..., help="DWS table name or all"),
    skip_validation: bool = typer.Option(False, "--skip-validation", help="Temporarily skip validation"),
    validation_mode: str | None = typer.Option(
        None,
        "--validation-mode",
        help="Override validation mode: strict, warn_only, or skip",
    ),
):
    manager = DWSManager()
    resolved_mode = _resolve_validation_mode(skip_validation, validation_mode)
    if table_name == 'all':
        manager.sync_all(validation_mode=resolved_mode, skip_validation=skip_validation)
        return
    manager.sync_table(table_name, validation_mode=resolved_mode, skip_validation=skip_validation)


@dws_app.command('sql', help="Render DWS sync SQL", no_args_is_help=True)
def render_dws_sql(
    table_name: str = typer.Argument(..., help="DWS table name, e.g. dws_stock_factor_wide"),
):
    manager = DWSManager()
    print(manager.render_sync_sql(table_name))


@quality_app.command('list', help="List validation rules", no_args_is_help=True)
def list_quality_rules(
    layer: str = typer.Argument(..., help="Validation layer: ods, dwd, or dws"),
    table_name: str = typer.Argument(..., help="Logical table name"),
):
    manager = QualityManager()
    for rule in manager.list_rules(layer=layer, table_name=table_name):
        print(f"{rule.severity} {rule.rule_id}: {rule.description}")


@quality_app.command('run', help="Run validation rules", no_args_is_help=True)
def run_quality_rules(
    layer: str = typer.Option(..., "--layer", help="Validation layer: ods, dwd, or dws"),
    table_name: str = typer.Option(..., "--table", help="Logical table name"),
    target_table_name: str | None = typer.Option(
        None,
        "--target-table",
        help="Physical table to validate; defaults to --table",
    ),
    mode: str | None = typer.Option(None, "--mode", help="Override validation mode: strict, warn_only, or skip"),
):
    manager = QualityManager()
    resolved_mode = _resolve_validation_mode(False, mode)
    run = manager.validate_publish(
        layer=layer,
        table_name=table_name,
        target_table_name=target_table_name or table_name,
        stage=f"manual_{layer}",
        mode=resolved_mode,
    )
    print(manager.run_to_json(run))


@quality_app.command('report', help="Show validation report", no_args_is_help=True)
def report_quality_run(
    run_id: str = typer.Argument(..., help="Validation run id"),
):
    manager = QualityManager()
    print(manager.report_run(run_id))


@crawl_app.command('job', help="Run a job", no_args_is_help=True)
def run_job(
    job_name: str = typer.Argument(..., help="Name of the job to run"),
    update_type: str | None = typer.Option(
        None,
        "--update-type",
        "-u",
        help="Optional update dimension to run: incremental/daily or full/fully.",
    ),
):
    manager = CrawlManager()
    manager.run_job(job_name, update_type=update_type)


@crawl_app.command('spider', help="Run spiders", no_args_is_help=True)
def run_spider(
    spider: str = typer.Argument(
        ...,
        help="Wildcard of the spider to run",
    )
):
    manager = CrawlManager()
    manager.run_spider(spider)
