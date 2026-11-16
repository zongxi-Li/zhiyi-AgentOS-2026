"""纯合同的统一严格基类与值约束，不持有外部资源。

TODO(P0)：冻结 JSON Schema 快照，覆盖未知字段、版本和 JSON/Python 输入差异。
"""

import json
import math
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class SafeContract(BaseModel):
    """禁止隐式转换、未知字段与修改；嵌套集合使用不可变类型。"""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


def parse_json_object(raw: bytes) -> dict:
    """解析已限额的 UTF-8 JSON 对象，拒绝重复键和非有限数，不回显输入。"""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def finite_float(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError
        return value

    def invalid_constant(_):
        raise ValueError

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                            parse_float=finite_float, parse_constant=invalid_constant)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, UnicodeError, RecursionError, TypeError):
        raise ValueError("JSON 协议对象无效") from None
