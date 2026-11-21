import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "check_repository_hygiene.py"
spec = importlib.util.spec_from_file_location("repository_hygiene", SCRIPT)
hygiene = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hygiene)


def test_finds_stale_paths_in_new_active_scripts(tmp_path):
    path = tmp_path / "ops/scripts/new_launcher.py"
    path.parent.mkdir(parents=True)
    path.write_text("entry = 'apps/backend-ts/dist/main.js'\n")
    assert any("backend-ts" in failure for failure in hygiene.check_paths(tmp_path, [path.relative_to(tmp_path)]))


def test_accepts_legacy_environment_keys_and_historical_evidence(tmp_path):
    active = tmp_path / "apps/backend/src/config.ts"
    active.parent.mkdir(parents=True)
    active.write_text("const port = env.ZHIYI_BACKEND_TS_PORT\n")
    history = tmp_path / "docs/audits/old.md"
    history.parent.mkdir(parents=True)
    history.write_text("Before migration: apps/backend-ts\n")
    assert hygiene.check_paths(tmp_path, [active.relative_to(tmp_path), history.relative_to(tmp_path)]) == []


def test_rejects_kernel_test_path_regression(tmp_path):
    path = tmp_path / "README.md"
    path.write_text("python -m pytest apps/agentOS/tests -q\n")
    assert any("agentOS/tests" in failure for failure in hygiene.check_paths(tmp_path, [Path("README.md")]))


def test_catches_manifest_lock_drift(tmp_path):
    package = tmp_path / "apps/backend"
    package.mkdir(parents=True)
    manifest = {"name": "backend", "engines": {"node": ">=24.9.0 <25"},
                "devDependencies": {"typescript": "5.9.3"}}
    (package / "package.json").write_text(json.dumps(manifest))
    locked = dict(manifest, devDependencies={"typescript": "5.4.5"})
    (package / "package-lock.json").write_text(json.dumps({"packages": {"": locked}}))
    assert any("devDependencies" in failure for failure in hygiene.check_package(tmp_path, Path("apps/backend")))


def test_rejects_tracked_research_build_outputs(tmp_path):
    assert hygiene.check_artifacts([Path("papers/architecture/.build/viewer.min.js")])
    assert hygiene.check_artifacts([Path("papers/planner/paper.pdf")])
    assert hygiene.check_artifacts([Path("papers/planner/README.md"), Path("papers/architecture/source.drawio"),
                                    Path("papers/architecture/deck_source.js")]) == []
