#!/usr/bin/env python3
"""Print read-only acceptance SQL. Never connect to the configured database."""

import argparse
import json
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]


def identifier(value):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise argparse.ArgumentTypeError("expected a plain SQL identifier")
    return value


def render(database, old_table, new_table):
    manifest = json.loads((ROOT / "tushare_integration/schema/dws/v2_scalar_extensions.json").read_text())
    columns = yaml.safe_load((ROOT / "tushare_integration/schema/dws/dws_stock_factor_wide_v2.yaml").read_text())[
        "schema"
    ]["columns"]
    additions = {item["name"] for item in manifest if item["status"] != "excluded"}
    audit = {"source", "source_table", "source_batch_id", "source_record_hash", "build_time"}
    old_names = [c["name"] for c in columns if c["name"] not in additions | audit]
    old, new = f"`{database}`.`{old_table}`", f"`{database}`.`{new_table}`"
    expected = ",".join("'" + c["name"] + "'" for c in columns)
    # Avoid holding all 1,736 value columns and their aggregate inputs at once.
    comparisons = []
    for offset in range(0, len(old_names), 128):
        checks = ",\n    ".join(
            f"tuple('{name}', countIf(isNull(o.`{name}`) != isNull(n.`{name}`) "
            f"OR ifNull(o.`{name}` != n.`{name}`, 0)))" for name in old_names[offset:offset + 128]
        )
        comparisons.append(f"""SELECT diff.1 AS column_name,diff.2 AS mismatches FROM (
 SELECT arrayJoin([
    {checks}
 ]) AS diff FROM {old} o INNER JOIN {new} n ON o.instrument_id=n.instrument_id AND o.trade_date=n.trade_date
) WHERE diff.2 > 0;""")
    comparison_sql = "\n\n".join(comparisons)
    null_counts = ",\n    ".join(f"tuple('{name}', countIf(`{name}` IS NOT NULL))" for name in sorted(additions))
    return f"""-- Generated from the checked-in v2 schema and 236-item manifest; read-only.
-- Expected: 1968 schema columns, no missing/extra names.
SELECT arrayFilter(x -> NOT has(actual,x), [{expected}]) AS missing,
       arrayFilter(x -> NOT has([{expected}],x), actual) AS unexpected
FROM (SELECT groupArray(name) AS actual FROM system.columns
      WHERE database='{database}' AND table='{new_table}');

-- Row count, uniqueness, and key equality must match.
SELECT 'old' AS panel,count() AS rows,uniqExact(instrument_id,trade_date) AS keys FROM {old}
UNION ALL SELECT 'new',count(),uniqExact(instrument_id,trade_date) FROM {new};
SELECT countIf(o.instrument_id='') AS only_new,countIf(n.instrument_id='') AS only_old
FROM {old} o FULL OUTER JOIN {new} n ON o.instrument_id=n.instrument_id AND o.trade_date=n.trade_date;

-- Exact NULL-safe comparison of every pre-existing value column.
{comparison_sql}

-- Review non-null counts. The 13 documented placeholders must remain zero.
SELECT metric.1 AS column_name,metric.2 AS non_null_rows FROM (
 SELECT arrayJoin([
    {null_counts}
 ]) AS metric FROM {new}
);
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=identifier, default="default")
    parser.add_argument("--old-table", type=identifier, default="dws_stock_factor_wide_v2")
    parser.add_argument("--new-table", type=identifier, default="dws_stock_factor_wide_v2_candidate")
    args = parser.parse_args()
    print(render(args.database, args.old_table, args.new_table))


if __name__ == "__main__":
    main()
