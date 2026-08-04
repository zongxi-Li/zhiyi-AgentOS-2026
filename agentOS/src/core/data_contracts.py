"""Structured input/output contract validation shared by ACG and communication."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable

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
    """A step input or output does not satisfy its declared JSON Schema."""

    def __init__(self, *, step_id: str, direction: str, message: str, path: str = ""):
        self.step_id = step_id
        self.direction = direction
        self.path = path
        super().__init__(f"{direction} contract violation at {step_id}{f' ({path})' if path else ''}: {message}")


def check_contract_schema(schema: Dict[str, Any], *, label: str) -> None:
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
    """Copy a payload while applying only explicit JSON Schema defaults.

    Model output remains untrusted input. This conservative normalizer never
    coerces types, drops array items, or invents undeclared values.
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


__all__ = [
    "ContextContractError",
    "apply_contract_defaults",
    "check_contract_schema",
    "validate_contract_payload",
]
