"""Replay verified 688585.SH difference dates through the standard CLI."""

import argparse
import csv
import datetime
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Only display the request plan')
    args = parser.parse_args()
    report_dir = Path(__file__).resolve().parent
    project = report_dir.parents[2]
    with (report_dir / '688585_difference_dates.csv').open(newline='') as handle:
        rows = list(csv.DictReader(handle))
    dates = [datetime.date.fromisoformat(row['trade_date']).isoformat() for row in rows]
    if len(dates) != 841 or len(set(dates)) != len(dates):
        raise ValueError('Expected exactly 841 unique dates from the verified report')
    command = [
        str(project / '.venv/bin/python'), str(project / 'main.py'),
        'run', 'replay', 'stock/quotes/adj_factor', '--ts-code', '688585.SH',
    ]
    for day in sorted(dates):
        command.extend(['--trade-date', day])
    if args.dry_run:
        command.append('--dry-run')
    return subprocess.run(command, cwd=project, check=True).returncode


if __name__ == '__main__':
    raise SystemExit(main())
