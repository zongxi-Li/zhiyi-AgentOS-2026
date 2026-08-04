"""部件化目标架构的回归保护测试。"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"

COMPONENT_FILES = {
    "task_manager": ("models.py", "state_machine.py", "service.py", "scheduler.py", "algorithms.py", "store.py"),
    "planner": ("models.py", "intent_analyzer.py", "task_structurer.py", "cognitive_router.py", "template_matcher.py", "acg_builder.py", "algorithms.py", "service.py"),
    "scheduler": ("models.py", "binder.py", "scorer.py", "leases.py", "package_builder.py", "algorithms.py", "service.py"),
    "executor": ("graph.py", "dispatcher.py", "barrier.py", "service.py", "algorithms.py", "fault_injection.py"),
    "communicator": ("models.py", "contracts.py", "assembler.py", "compressor.py", "provenance.py", "algorithms.py", "service.py"),
    "memory": ("models.py", "store.py", "admission.py", "retrieval.py", "compression.py", "lifecycle.py", "algorithms.py", "service.py"),
    "auditor": ("models.py", "structural.py", "evidence.py", "risk.py", "quality.py", "policy.py", "algorithms.py", "service.py"),
    "recovery": ("models.py", "classifier.py", "checkpoint.py", "planner.py", "validator.py", "algorithms.py", "service.py"),
    "runtime": ("bootstrap.py", "workflow_runtime.py", "dependencies.py", "compatibility.py"),
    "acg_tools": ("models.py", "serializer.py", "exporter.py", "labels.py", "mermaid.py", "graphviz.py", "service.py"),
}

ADAPTER_PACKAGES = ("model", "tool", "storage", "remote_agent")
SERVICE_EXPORTS = {
    "task_manager": "TaskManagerService",
    "planner": "PlannerService",
    "scheduler": "SchedulerService",
    "executor": "ExecutorService",
    "communicator": "CommunicatorService",
    "memory": "MemoryService",
    "auditor": "AuditorService",
    "recovery": "RecoveryService",
    "acg_tools": "ACGToolsService",
}


@pytest.mark.parametrize("component, files", COMPONENT_FILES.items())
def test_component_files_exist_and_are_non_empty(component: str, files: tuple[str, ...]) -> None:
    """所有目标部件文件都是可读的实质模块，禁止退化为空占位文件。"""
    for filename in files:
        target = SOURCE_ROOT / component / filename
        assert target.is_file(), f"缺少目标模块：{target.relative_to(SOURCE_ROOT)}"
        assert target.stat().st_size > 0, f"模块不得为空：{target.relative_to(SOURCE_ROOT)}"


@pytest.mark.parametrize("package", ADAPTER_PACKAGES)
def test_adapter_subpackages_have_non_empty_package_contract(package: str) -> None:
    """适配器边界以非空包初始化文件公开，迁移期不隐藏外部依赖。"""
    target = SOURCE_ROOT / "adapters" / package / "__init__.py"
    assert target.is_file(), f"缺少适配器包：{target.relative_to(SOURCE_ROOT)}"
    assert target.stat().st_size > 0, f"适配器包声明不得为空：{target.relative_to(SOURCE_ROOT)}"


@pytest.mark.parametrize("component, service_name", SERVICE_EXPORTS.items())
def test_component_publicly_exports_its_service(component: str, service_name: str) -> None:
    """消费者仅需从部件包导入服务 Facade，而不应依赖内部模块。"""
    package = import_module(component)
    assert getattr(package, service_name, None) is not None


@pytest.mark.parametrize(
    "legacy_file",
    (
        "communication/message.py",
        "communication/protocol.py",
        "communication/router.py",
        "governance/evidence_chain.py",
        "governance/policy_engine.py",
        "governance/review_manager.py",
        "governance/trace_logger.py",
        "infrastructure/stores/base_store.py",
        "infrastructure/stores/task_store.py",
        "infrastructure/stores/workflow_store.py",
        "recovery/recovery_manager.py",
        "recovery/retry_strategy.py",
    ),
)
def test_obsolete_top_level_placeholder_modules_are_absent(legacy_file: str) -> None:
    """旧顶层占位模块不得与新的部件边界同时存在。"""
    assert not (SOURCE_ROOT / legacy_file).exists()
