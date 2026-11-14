"""纯合同的统一严格基类与值约束，不持有外部资源。

TODO(P0)：冻结 JSON Schema 快照，覆盖未知字段、版本和 JSON/Python 输入差异。
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class SafeContract(BaseModel):
    """禁止隐式转换、未知字段与修改；嵌套集合使用不可变类型。"""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)
