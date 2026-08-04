"""低熵通信子系统。

以工作流引擎为唯一可信中介，把智能体间的“自由对话”转为沿依赖边流动的
“精准数据流”：按需投递、证据链聚合、低熵度量与数据血缘审计。
"""

from __future__ import annotations

from core.communication.assembler import ContextAssembler
from core.communication.audit import (
    DataConsumptionEvent,
    DataProductionEvent,
    ProvenanceLedger,
    RuntimeInteraction,
)
from core.communication.contract import ContextPack, estimate_tokens
from core.data_contracts import (
    ContextContractError,
    check_contract_schema,
    validate_contract_payload,
)

__all__ = [
    "ContextAssembler",
    "ContextPack",
    "estimate_tokens",
    "ProvenanceLedger",
    "DataProductionEvent",
    "DataConsumptionEvent",
    "RuntimeInteraction",
    "ContextContractError",
    "check_contract_schema",
    "validate_contract_payload",
]
