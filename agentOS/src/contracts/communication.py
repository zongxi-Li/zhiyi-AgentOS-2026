"""定义 ACG 与通信组件共享的结构化输入输出契约校验边界。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

from pydantic import BaseModel, ConfigDict, Field, StrictStr

try:
    from jsonschema import ValidationError as JSONSchemaValidationError
    from jsonschema.validators import validator_for

    _HAS_JSONSCHEMA = True
except ModuleNotFoundError:
    _HAS_JSONSCHEMA = False

    class JSONSchemaValidationError(ValueError):
        """无 jsonschema 依赖时，保留调用方所需的错误表面。"""

        def __init__(self, message: str, path: Iterable[str | int] = ()):
            self.message = message
            self.absolute_path = tuple(path)
            super().__init__(message)


def _matches_json_type(value: Any, expected: str) -> bool:
    """实现回退验证器所需的 JSON 基础类型判断，bool 不视为整数。"""
    return {
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str),
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "boolean": lambda: isinstance(value, bool),
        "null": lambda: value is None,
    }.get(expected, lambda: True)()


_SUPPORTED_MINIMAL_TYPES = frozenset(
    {"object", "array", "string", "number", "integer", "boolean", "null"}
)


def _schema_nonnegative_integer(schema: Dict[str, Any], keyword: str) -> int | None:
    """读取长度关键字，并拒绝回退验证器无法安全解释的值。"""
    if keyword not in schema:
        return None
    value = schema[keyword]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise JSONSchemaValidationError(
            f"schema keyword '{keyword}' must be a non-negative integer"
        )
    return value


def _validate_minimal_schema_definition(
    schema: Any, path: tuple[str | int, ...] = ()
) -> None:
    """递归确认回退验证器将要解释的 schema 定义是完整且受支持的。

    必须在验证载荷前执行：即使可选属性没有出现在载荷中，其 ``type``
    定义也不能绕过校验并在未来请求中静默失效。
    """
    if not isinstance(schema, dict):
        raise JSONSchemaValidationError("schema must be an object", path)

    if "type" in schema:
        declared_type = schema["type"]
        if isinstance(declared_type, str):
            declared_types = [declared_type]
        elif isinstance(declared_type, list) and declared_type:
            declared_types = declared_type
        else:
            raise JSONSchemaValidationError(
                "schema keyword 'type' must be a non-empty string or string array", path
            )
        for type_name in declared_types:
            if not isinstance(type_name, str):
                raise JSONSchemaValidationError(
                    "schema keyword 'type' array entries must be strings", path
                )
            if type_name not in _SUPPORTED_MINIMAL_TYPES:
                raise JSONSchemaValidationError(
                    f"unsupported JSON Schema type {type_name!r} in fallback validator",
                    path,
                )

    for keyword in ("minLength", "maxLength", "minItems", "maxItems"):
        _schema_nonnegative_integer(schema, keyword)

    if "properties" in schema:
        properties = schema["properties"]
        if not isinstance(properties, dict):
            raise JSONSchemaValidationError("schema keyword 'properties' must be an object", path)
        for property_name, property_schema in properties.items():
            if not isinstance(property_name, str):
                raise JSONSchemaValidationError("schema property names must be strings", path)
            _validate_minimal_schema_definition(property_schema, (*path, property_name))

    if "items" in schema:
        items = schema["items"]
        if not isinstance(items, dict):
            raise JSONSchemaValidationError("schema keyword 'items' must be an object", path)
        _validate_minimal_schema_definition(items, (*path, "items"))

    if "required" in schema and (
        not isinstance(schema["required"], list)
        or not all(isinstance(item, str) for item in schema["required"])
    ):
        raise JSONSchemaValidationError("schema keyword 'required' must be a string array", path)
    if "enum" in schema and not isinstance(schema["enum"], list):
        raise JSONSchemaValidationError("schema keyword 'enum' must be an array", path)
    if "nullable" in schema and not isinstance(schema["nullable"], bool):
        raise JSONSchemaValidationError("schema keyword 'nullable' must be a boolean", path)


def _validate_minimal_schema(payload: Any, schema: Dict[str, Any], path: tuple[str | int, ...] = ()) -> None:
    """验证项目当前合同使用的最小 JSON Schema 子集。

    支持 object/properties/required/type/array/items/enum/nullable，目的仅是让
    不安装 jsonschema 的运行环境仍可安全运行既有合同校验。
    # TODO: 若需 oneOf、引用解析、格式校验等完整 JSON Schema 能力，请安装 jsonschema 依赖。
    """
    nullable = schema.get("nullable") is True
    if payload is None and nullable:
        return

    expected = schema.get("type")
    expected_types = expected if isinstance(expected, list) else [expected]
    expected_types = [item for item in expected_types if isinstance(item, str)]
    if expected_types and not any(_matches_json_type(payload, item) for item in expected_types):
        description = " or ".join(expected_types)
        raise JSONSchemaValidationError(f"{payload!r} is not of type '{description}'", path)

    allowed = schema.get("enum")
    if isinstance(allowed, list) and payload not in allowed:
        raise JSONSchemaValidationError(f"{payload!r} is not one of {allowed!r}", path)

    min_length = _schema_nonnegative_integer(schema, "minLength")
    max_length = _schema_nonnegative_integer(schema, "maxLength")
    if isinstance(payload, str):
        if min_length is not None and len(payload) < min_length:
            raise JSONSchemaValidationError(
                f"{payload!r} is too short", path
            )
        if max_length is not None and len(payload) > max_length:
            raise JSONSchemaValidationError(
                f"{payload!r} is too long", path
            )

    min_items = _schema_nonnegative_integer(schema, "minItems")
    max_items = _schema_nonnegative_integer(schema, "maxItems")
    if isinstance(payload, list):
        if min_items is not None and len(payload) < min_items:
            raise JSONSchemaValidationError(f"{payload!r} has too few items", path)
        if max_items is not None and len(payload) > max_items:
            raise JSONSchemaValidationError(f"{payload!r} has too many items", path)

    if isinstance(payload, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in payload:
                    raise JSONSchemaValidationError(f"'{key}' is a required property", path)
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                if key in payload and isinstance(child_schema, dict):
                    _validate_minimal_schema(payload[key], child_schema, (*path, key))

    if isinstance(payload, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(payload):
                _validate_minimal_schema(item, item_schema, (*path, index))


class ContextContractError(ValueError):
    """步骤输入或输出未满足声明 JSON Schema 时的结构化错误。

    ``step_id``、``direction`` 与 ``path`` 定位违例边界；错误对象只描述校验结果，
    不修改载荷或合同。
    """

    def __init__(self, *, step_id: str, direction: str, message: str, path: str = ""):
        self.step_id = step_id
        self.direction = direction
        self.path = path
        super().__init__(f"{direction} contract violation at {step_id}{f' ({path})' if path else ''}: {message}")


def check_contract_schema(schema: Dict[str, Any], *, label: str) -> None:
    """校验步骤 JSON Schema 的合法性。

    空模式表示不设约束；优先使用 ``jsonschema``，不可用时使用受限校验器。仅验证
    模式定义，不修改传入对象；无效时以 ``ValueError`` 标明 ``label``。
    """
    if not schema:
        return
    if not isinstance(schema, dict):
        raise ValueError(f"invalid JSON Schema for {label}: schema must be an object")
    if not _HAS_JSONSCHEMA:
        try:
            _validate_minimal_schema_definition(schema)
        except JSONSchemaValidationError as exc:
            raise ValueError(f"invalid JSON Schema for {label}: {exc.message}") from exc
        return
    validator = validator_for(schema)
    try:
        validator.check_schema(schema)
    except Exception as exc:
        raise ValueError(f"invalid JSON Schema for {label}: {exc}") from exc


def validate_contract_payload(
    payload: Any,
    schema: Dict[str, Any],
    *,
    step_id: str,
    direction: str,
) -> None:
    """验证载荷是否符合步骤输入或输出合同。

    ``schema`` 为空时直接通过；否则在不修改 ``payload`` 的前提下校验，并把失败转换为
    带步骤、方向与 JSON 路径信息的 ``ContextContractError``。
    """
    if not schema:
        return
    if not _HAS_JSONSCHEMA:
        try:
            _validate_minimal_schema_definition(schema)
            _validate_minimal_schema(payload, schema)
        except JSONSchemaValidationError as exc:
            path = ".".join(str(item) for item in exc.absolute_path)
            raise ContextContractError(
                step_id=step_id,
                direction=direction,
                message=exc.message,
                path=path,
            ) from exc
        return
    validator = validator_for(schema)(schema)
    try:
        validator.validate(payload)
    except JSONSchemaValidationError as exc:
        path = ".".join(str(item) for item in exc.absolute_path)
        raise ContextContractError(
            step_id=step_id,
            direction=direction,
            message=exc.message,
            path=path,
        ) from exc


def apply_contract_defaults(payload: Any, schema: Dict[str, Any]) -> Any:
    """复制载荷并仅应用 JSON Schema 显式默认值。

    模型输出仍是不可信输入。此保守归一器不会强制转换类型、删除数组项或臆造未声明值；
    返回深复制结构，不改写 ``payload`` 或 ``schema``，递归复杂度与访问节点数线性相关。
    """

    if isinstance(payload, dict):
        normalized = {key: deepcopy(value) for key, value in payload.items()}
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return normalized
        for key, property_schema in properties.items():
            if not isinstance(property_schema, dict):
                continue
            if key not in normalized and "default" in property_schema:
                normalized[key] = deepcopy(property_schema["default"])
            if key in normalized:
                normalized[key] = apply_contract_defaults(
                    normalized[key], property_schema
                )
        return normalized

    if isinstance(payload, list):
        item_schema = schema.get("items")
        if not isinstance(item_schema, dict):
            return deepcopy(payload)
        return [apply_contract_defaults(item, item_schema) for item in payload]

    return deepcopy(payload)


def compact_contract_text_arrays(payload: Any, schema: Dict[str, Any]) -> Any:
    """在不删除文本的前提下压缩超过 ``maxItems`` 的字符串数组。

    模型供应商可能接受 JSON Schema 却不严格执行数组数量约束。对于纯字符串数组，
    相邻条目可以用换行重新分组而不丢失原文；只有在所有内容都能同时满足
    ``maxItems`` 与条目 ``maxLength`` 时才返回压缩结果，否则保持原载荷，交由既有
    严格校验产生合同错误。函数递归复制载荷，不修改调用方对象或 Schema。
    """

    if isinstance(payload, dict):
        normalized = {key: deepcopy(value) for key, value in payload.items()}
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return normalized
        for key, property_schema in properties.items():
            if key in normalized and isinstance(property_schema, dict):
                normalized[key] = compact_contract_text_arrays(
                    normalized[key], property_schema
                )
        return normalized

    if not isinstance(payload, list):
        return deepcopy(payload)

    item_schema = schema.get("items")
    normalized = (
        [compact_contract_text_arrays(item, item_schema) for item in payload]
        if isinstance(item_schema, dict)
        else deepcopy(payload)
    )
    max_items = schema.get("maxItems")
    if (
        not isinstance(max_items, int)
        or isinstance(max_items, bool)
        or max_items < 1
        or len(normalized) <= max_items
        or not isinstance(item_schema, dict)
        or item_schema.get("type") != "string"
        or not all(isinstance(item, str) for item in normalized)
    ):
        return normalized

    max_length = item_schema.get("maxLength")
    if (
        max_length is not None
        and (
            not isinstance(max_length, int)
            or isinstance(max_length, bool)
            or max_length < 0
            or any(len(item) > max_length for item in normalized)
        )
    ):
        return normalized

    compacted = list(normalized)
    while len(compacted) > max_items:
        candidates = [
            (len(left) + 1 + len(right), index)
            for index, (left, right) in enumerate(zip(compacted, compacted[1:]))
            if max_length is None or len(left) + 1 + len(right) <= max_length
        ]
        if not candidates:
            return normalized
        _, merge_index = min(candidates)
        compacted[merge_index : merge_index + 2] = [
            f"{compacted[merge_index]}\n{compacted[merge_index + 1]}"
        ]
    return compacted


__all__ = [
    "ContextContractError",
    "apply_contract_defaults",
    "check_contract_schema",
    "compact_contract_text_arrays",
    "validate_contract_payload",
]


def _utc_now() -> datetime:
    """生成带时区的通信事实时间。"""
    return datetime.now(timezone.utc)


class ContextPackRef(BaseModel):
    """通信层传递的可校验上下文包引用。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    context_id: StrictStr = Field(alias="contextId", min_length=1)
    uri: StrictStr = Field(min_length=1)
    checksum: StrictStr = Field(min_length=1)
    content_type: StrictStr = Field(default="application/json", alias="contentType", min_length=1)


class MessageEnvelope(BaseModel):
    """部件间消息信封，仅承载通用 JSON 数据。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    message_id: StrictStr = Field(alias="messageId", min_length=1)
    topic: StrictStr = Field(min_length=1)
    sender: StrictStr = Field(min_length=1)
    recipient: StrictStr | None = None
    correlation_id: StrictStr | None = Field(default=None, alias="correlationId")
    payload: Dict[str, Any] = Field(default_factory=dict)
    context: ContextPackRef | None = None
    sent_at: datetime = Field(default_factory=_utc_now, alias="sentAt")


__all__.extend(["ContextPackRef", "MessageEnvelope"])
