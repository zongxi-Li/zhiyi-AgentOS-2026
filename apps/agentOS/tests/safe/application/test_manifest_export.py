"""CLI导出经用例和端口，不直接把基础设施当作业务入口。"""

from pathlib import Path

import pytest

from safe.application.manifest import ManifestService
from safe.contracts.errors import SafeError


def test_export_delegates_to_injected_port_only():
    calls = []

    def exporter(source, destination, **options):
        calls.append((source, destination, options))
        return "a" * 64

    service = ManifestService(exporter=exporter)
    assert service.export(Path("source"), Path("target"), model_id="test/qwen", revision="b" * 40,
                          cut_layer=2, license_id="Apache-2.0") == "a" * 64
    assert calls[0][0:2] == (Path("source"), Path("target"))
    assert calls[0][2]["cut_layer"] == 2


def test_export_without_port_refuses():
    with pytest.raises(SafeError):
        ManifestService().export(Path("source"), Path("target"), model_id="test/qwen", revision="b" * 40,
                                 cut_layer=2, license_id="Apache-2.0")
