from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ricequant_integration.specs import DATASET_SPECS


def test_ricequant_incremental_script_has_valid_shell_syntax():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "run_ricequant_incremental.sh"

    result = subprocess.run(
        ["bash", "-n", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_ricequant_incremental_script_schedules_every_implemented_dataset():
    root = Path(__file__).resolve().parents[1]
    script = (
        root / "scripts" / "run_ricequant_incremental.sh"
    ).read_text(encoding="utf-8")
    scheduled = set(re.findall(r"^  ([a-z_]+)$", script, flags=re.MULTILINE))
    if "datasets+=(tick)" in script:
        scheduled.add("tick")
    expected = set(DATASET_SPECS) - {"trading_calendar", "instruments"}

    assert scheduled == expected
    assert 'args=(incremental)' in script
    assert 'RICEQUANT_INCLUDE_TICK:-1' in script
    assert "ricequant-incremental-cron-$(date +%Y%m%d).log" in script
    assert 'exec >>"$CRON_LOG" 2>&1' in script
    assert '"$RUNNER" "${args[@]}" || status=$?' in script
    assert 'exit "$status"' in script
