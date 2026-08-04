"""新架构中文注释和 TODO 边界的静态策略测试。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
COMPONENTS = (
    "contracts",
    "task_manager",
    "planner",
    "resource",
    "scheduler",
    "executor",
    "communicator",
    "memory",
    "auditor",
    "recovery",
    "runtime",
    "acg_tools",
    "adapters",
)

# 公共接口的中文说明是跨部件调用时的契约；检索适配器正处于独立迁移中，沿用文件枚举的排除规则。
PUBLIC_INTERFACE_COMPONENTS = COMPONENTS


def _has_chinese(text: str) -> bool:
    """判断文本是否含有至少一个中文字符。"""
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _source_files() -> list[Path]:
    """枚举审计范围内文件，并排除用户正在迁移的检索适配器。"""
    return [
        path
        for component in COMPONENTS
        for path in (SOURCE_ROOT / component).rglob("*.py")
        if component != "adapters"
        or "retrieval" not in path.relative_to(SOURCE_ROOT / "adapters").parts
    ]


@pytest.mark.parametrize("source_file", _source_files())
def test_source_file_starts_with_non_empty_chinese_docstring(source_file: Path) -> None:
    """每个审计模块以准确的非空中文模块说明建立阅读边界。"""
    module = ast.parse(source_file.read_text(encoding="utf-8"))
    assert module.body, f"模块不能为空：{source_file.relative_to(SOURCE_ROOT)}"
    first_statement = module.body[0]
    assert isinstance(first_statement, ast.Expr) and isinstance(first_statement.value, ast.Constant)
    assert isinstance(first_statement.value.value, str) and first_statement.value.value.strip()
    assert _has_chinese(first_statement.value.value), f"模块说明必须为中文：{source_file.relative_to(SOURCE_ROOT)}"


@pytest.mark.parametrize("source_file", _source_files())
def test_todo_lines_include_chinese_explanation(source_file: Path) -> None:
    """TODO 必须说明未完成的中文实现边界，避免成为无上下文占位。"""
    for line_number, line in enumerate(source_file.read_text(encoding="utf-8").splitlines(), 1):
        if "TODO" in line:
            assert _has_chinese(line), f"TODO 缺少中文说明：{source_file.relative_to(SOURCE_ROOT)}:{line_number}"


def _public_definitions(module: ast.Module) -> list[ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef]:
    """枚举模块公共类、函数及其公共方法；不把函数内部帮助器误判为对外接口。"""
    definitions: list[ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef] = []

    def collect(body: list[ast.stmt]) -> None:
        for node in body:
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("_"):
                continue
            definitions.append(node)
            if isinstance(node, ast.ClassDef):
                collect(node.body)

    collect(module.body)
    return definitions


@pytest.mark.parametrize("source_file", _source_files())
def test_public_interfaces_have_chinese_docstrings(source_file: Path) -> None:
    """公共类、函数、方法和 Protocol 必须有中文 docstring，建立调用语义边界。"""
    module = ast.parse(source_file.read_text(encoding="utf-8"))
    for definition in _public_definitions(module):
        docstring = ast.get_docstring(definition)
        assert docstring and _has_chinese(docstring), (
            "公共接口缺少中文 docstring："
            f"{source_file.relative_to(SOURCE_ROOT)}:{definition.lineno}:{definition.name}"
        )
