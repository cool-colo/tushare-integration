from __future__ import annotations

import signal
from contextlib import contextmanager
from pathlib import Path

import pytest

from ricequant_integration.commands import (
    SHUTDOWN_SIGNALS,
    _shutdown_on_signal,
    install_shutdown_signal_handlers,
)


def test_shutdown_handler_unwinds_lock_context_and_ignores_followup_signals(
    monkeypatch,
):
    installed = []
    released = False

    def record_handler(signum, handler):
        installed.append((signum, handler))

    @contextmanager
    def held_lock():
        nonlocal released
        try:
            yield
        finally:
            released = True

    monkeypatch.setattr(signal, "signal", record_handler)

    with pytest.raises(SystemExit) as exc_info:
        with held_lock():
            _shutdown_on_signal(signal.SIGTERM, None)

    assert exc_info.value.code == 128 + signal.SIGTERM
    assert released
    assert installed == [
        (shutdown_signal, signal.SIG_IGN)
        for shutdown_signal in SHUTDOWN_SIGNALS
    ]


def test_install_shutdown_signal_handlers_registers_every_stop_signal(monkeypatch):
    installed = []
    monkeypatch.setattr(
        signal,
        "signal",
        lambda signum, handler: installed.append((signum, handler)),
    )

    install_shutdown_signal_handlers()

    assert installed == [
        (shutdown_signal, _shutdown_on_signal)
        for shutdown_signal in SHUTDOWN_SIGNALS
    ]


def test_docker_wrapper_forwards_signals_without_force_removing_live_runner():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_ricequant_jobs.sh"
    ).read_text(encoding="utf-8")

    assert "trap 'forward_signal INT' INT" in script
    assert "trap 'forward_signal TERM' TERM" in script
    assert 'docker_cmd kill --signal="$signal_name"' in script
    assert "trap cleanup_stale_container INT TERM" not in script
