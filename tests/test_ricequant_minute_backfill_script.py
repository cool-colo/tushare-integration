from pathlib import Path
import subprocess


def test_ricequant_minute_backfill_script_has_valid_shell_syntax():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "run_ricequant_minute_backfill.sh"

    result = subprocess.run(
        ["bash", "-n", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_ricequant_minute_backfill_runs_recent_years_first_and_stops_on_quota():
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "run_ricequant_minute_backfill.sh").read_text()

    assert "RICEQUANT_MINUTE_BACKFILL_START_YEAR:-2015" in text
    assert "RICEQUANT_MINUTE_BACKFILL_END_YEAR:-2019" in text
    assert "year = END_YEAR; year >= START_YEAR; year--" in text
    assert '"$RUNNER" bootstrap' in text
    assert "--dataset stock_minute" in text
    assert '\"status\": \"quota_paused\"' in text
