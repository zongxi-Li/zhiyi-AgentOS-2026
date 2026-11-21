"""The launchers and environment example must follow the shipped defaults."""
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
NATIVE = ROOT / "ops/scripts/infra/windows/native"
sys.path.insert(0, str(NATIVE))


def test_persistent_ports_follow_the_shared_backend_contract():
    from runtime_defaults import DEFAULTS
    import persistent_runtime
    assert persistent_runtime.ports({}) == DEFAULTS["ports"]
    assert persistent_runtime.ports({"portOffset": 100}) == {
        name: port + 100 for name, port in DEFAULTS["ports"].items()
    }


def test_example_uses_the_effective_stream_defaults():
    from runtime_defaults import DEFAULTS
    example = dict(line.split("=", 1) for line in (ROOT / ".env.example").read_text().splitlines()
                   if line and not line.startswith("#"))
    assert float(example["SSE_HEARTBEAT_INTERVAL"]) == DEFAULTS["stream"]["heartbeatSeconds"]
    assert int(example["SSE_IDLE_TIMEOUT"]) == DEFAULTS["stream"]["idleTimeoutMs"]
    assert int(example["SSE_MAX_DURATION"]) == DEFAULTS["stream"]["maxDurationMs"]


def test_packaged_runtime_reads_the_built_contract(tmp_path):
    source = (NATIVE / "runtime_defaults.py").read_text()
    module_path = tmp_path / "ops/scripts/infra/windows/native/runtime_defaults.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text(source)
    target = tmp_path / "apps/backend/dist/shared/runtime-defaults.json"
    target.parent.mkdir(parents=True)
    expected = {"ports": {"backend": 18081}, "stream": {}}
    target.write_text(json.dumps(expected))
    spec = importlib.util.spec_from_file_location("packaged_defaults", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.DEFAULTS == expected
