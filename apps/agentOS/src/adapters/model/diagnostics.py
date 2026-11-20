"""Body-free diagnostics shared by model transport, guards and audit."""
from __future__ import annotations


_STREAM_KEYS = frozenset({
    "streamStarted", "firstTokenObserved", "outputDeltaObserved", "deltaCount",
    "completionObserved", "streamTerminationReason", "elapsedMs",
})
_TRANSPORT_KEYS = frozenset({"phase", "httpStatus", "exceptionType"})


def _safe_fields(value, keys):
    return {
        key: item for key, item in value.items()
        if key in keys and isinstance(item, (bool, int, float, str))
    } if isinstance(value, dict) else {}


def safe_stream_diagnostics(value):
    return _safe_fields(value, _STREAM_KEYS)


def safe_transport_diagnostics(value):
    return _safe_fields(value, _TRANSPORT_KEYS)
