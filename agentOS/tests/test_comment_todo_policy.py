"""新架构中文注释和 TODO 边界的静态策略测试。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
# 注释策略覆盖 ``src`` 中所有仍参与运行的 Python 模块。虽然 agents、domain、
# packs、skills、stores 是新部件的配套实现，它们仍被运行时导入，不能成为注释盲区。
# 检索适配器正在由用户独立迁移，避免本次架构收尾改变其迁移中的契约。
EXCLUDED_RETRIEVAL_NAMES = {"retrieval_adapter.py"}


def _has_chinese(text: str) -> bool:
    """判断文本是否含有至少一个中文字符。"""
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _source_files() -> list[Path]:
    """枚举全部源码模块，并排除用户独立迁移中的检索适配器。"""
    return [
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if "retrieval" not in path.parts and path.name not in EXCLUDED_RETRIEVAL_NAMES
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
