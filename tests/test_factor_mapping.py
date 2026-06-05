from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tushare_integration import factor_mapping


class FactorMappingPathTest(unittest.TestCase):
    def test_resolves_checked_in_mapping(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(factor_mapping.FACTOR_MAPPING_CSV_ENV, None)

            path = factor_mapping.resolve_factor_mapping_csv(require_exists=True)

        self.assertEqual(path.name, "factor_mapping_readable.csv")
        self.assertIn("docs/prd/factor/v1", path.as_posix())

    def test_env_override_wins(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "factor_mapping_readable.csv"
            path.write_text("factor_id,expression\nf1,$close\n", encoding="utf-8")

            with mock.patch.dict(os.environ, {factor_mapping.FACTOR_MAPPING_CSV_ENV: str(path)}):
                self.assertEqual(factor_mapping.resolve_factor_mapping_csv(require_exists=True), path)

    def test_missing_env_override_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "missing_factor_mapping_readable.csv"

            with mock.patch.dict(os.environ, {factor_mapping.FACTOR_MAPPING_CSV_ENV: str(path)}):
                with self.assertRaisesRegex(FileNotFoundError, factor_mapping.FACTOR_MAPPING_CSV_ENV):
                    factor_mapping.resolve_factor_mapping_csv(require_exists=True)


if __name__ == "__main__":
    unittest.main()
