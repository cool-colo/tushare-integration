from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_ricequant_realtime.sh"


@pytest.fixture
def docker_env(tmp_path):
    fake = tmp_path / "docker"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['TEST_DOCKER_ARGS']).write_text(json.dumps(sys.argv[1:]))\n"
    )
    fake.chmod(0o755)
    (tmp_path / "ricequant.yaml").write_text("database: {host: localhost}\n")
    (tmp_path / "ricequant.env").write_text("RQDATA_TOKEN=test-only\n")
    env = {key: value for key, value in os.environ.items() if not key.startswith("RICEQUANT_")}
    env.update(PROJECT_DIR=str(tmp_path), DOCKER_BIN=str(fake), USE_SUDO="0",
               TEST_DOCKER_ARGS=str(tmp_path / "docker-args.json"))
    return env


@pytest.mark.parametrize("scope,name", [("stock", "ricequant-realtime"), ("csi2000", "ricequant-realtime-csi2000")])
def test_docker_collector_uses_matching_scope_container_and_durable_mount(docker_env, scope, name):
    docker_env["RICEQUANT_REALTIME_SCOPE"] = scope
    result = subprocess.run(["bash", str(SCRIPT), "start"], env=docker_env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    args = json.loads(Path(docker_env["TEST_DOCKER_ARGS"]).read_text())
    assert args[args.index("--name") + 1] == name
    assert args[args.index("--scope") + 1] == scope
    assert args[args.index("--state-dir") + 1] == "/code/app/data/ricequant-realtime"
    assert f"{docker_env['PROJECT_DIR']}/data/{name}:/code/app/data/ricequant-realtime" in args
    assert "tick_" not in " ".join(args)


@pytest.mark.parametrize("action", ["stop", "status", "logs"])
def test_csi2000_lifecycle_targets_only_its_container(docker_env, action):
    docker_env["RICEQUANT_REALTIME_SCOPE"] = "csi2000"
    result = subprocess.run(["bash", str(SCRIPT), action], env=docker_env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    args = json.loads(Path(docker_env["TEST_DOCKER_ARGS"]).read_text())
    assert args[-1] == "ricequant-realtime-csi2000"


@pytest.mark.parametrize("scope,options", [("other", []), ("stock", ["--scope", "csi2000"]),
                                          ("stock", ["--scope=csi2000"])])
def test_invalid_scope_or_scope_override_never_starts_a_container(docker_env, scope, options):
    docker_env["RICEQUANT_REALTIME_SCOPE"] = scope
    result = subprocess.run(["bash", str(SCRIPT), "start", *options], env=docker_env, capture_output=True, text=True)
    assert result.returncode == 2
    assert "RICEQUANT_REALTIME_SCOPE" in result.stderr
    assert not Path(docker_env["TEST_DOCKER_ARGS"]).exists()
