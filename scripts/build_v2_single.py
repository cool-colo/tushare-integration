#!/usr/bin/env python3
"""Build an isolated V2 candidate with one INSERT SELECT; never publish or drop."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tushare_integration.dws import DWSManager
from tushare_integration.v2_build import collect_query_metrics, save_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-table", help="New candidate name; generated if omitted")
    parser.add_argument("--instrument", action="append", help="Scope a trial to stock IDs; omit for full market")
    parser.add_argument("--validation-mode", choices=["strict", "warn_only"], default="warn_only")
    parser.add_argument("--report-path", type=Path)
    parser.add_argument("--refresh-report", type=Path, help="Only refresh asynchronously flushed query metrics")
    args = parser.parse_args()
    manager = DWSManager()
    if args.refresh_report:
        report = json.loads(args.refresh_report.read_text())
        report["query_metrics"] = collect_query_metrics(manager.get_db_engine(), report["run_id"])
        report.pop("query_metrics_error", None)
        save_report(args.refresh_report, report)
        print(f"Updated {args.refresh_report}")
        return
    result = manager.build_v2_candidate(args.target_table, instrument_ids=args.instrument,
                                        report_path=args.report_path, validation_mode=args.validation_mode)
    print(f"Candidate {result['target']}: {result['status']}; report={result['report_path']}")


if __name__ == "__main__":
    main()
