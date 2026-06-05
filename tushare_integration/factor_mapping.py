from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
FACTOR_MAPPING_CSV_ENV = "TUSHARE_FACTOR_MAPPING_CSV"
DEFAULT_FACTOR_MAPPING_CSV = ROOT_DIR / "docs" / "prd" / "factor_mapping_readable.csv"
FACTOR_MAPPING_CSV_CANDIDATES = [
    DEFAULT_FACTOR_MAPPING_CSV,
    ROOT_DIR / "docs" / "prd" / "factor" / "v1" / "factor_mapping_readable.csv",
    ROOT_DIR / "docs" / "prd" / "factor" / "v2" / "factor_mapping_readable_v2.csv",
]


def resolve_factor_mapping_csv(
    extra_candidates: list[Path] | tuple[Path, ...] = (),
    *,
    require_exists: bool = False,
) -> Path:
    env_path = os.environ.get(FACTOR_MAPPING_CSV_ENV)
    if env_path:
        path = Path(env_path)
        if require_exists and not path.exists():
            raise FileNotFoundError(
                f"{FACTOR_MAPPING_CSV_ENV} points to a missing factor mapping CSV: {path}"
            )
        return path

    candidates = [*FACTOR_MAPPING_CSV_CANDIDATES, *extra_candidates]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    if require_exists:
        searched = ", ".join(str(candidate) for candidate in candidates)
        raise FileNotFoundError(
            f"factor mapping CSV not found; set {FACTOR_MAPPING_CSV_ENV} or add one of: {searched}"
        )
    return DEFAULT_FACTOR_MAPPING_CSV
