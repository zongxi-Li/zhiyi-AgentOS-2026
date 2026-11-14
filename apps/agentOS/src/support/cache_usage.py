"""Normalize provider cache counters from mappings or SDK usage objects."""
from collections.abc import Mapping
import math


def _field(value, name):
    return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)


def _tokens(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return int(value)


def cache_usage(usage) -> tuple[int, bool]:
    """First valid alias wins, including zero; missing statistics remain unknown."""
    for key in ('cache_read_tokens', 'cache_read_input_tokens', 'cached_tokens',
                'cacheReadTokens', 'prompt_cache_hit_tokens'):
        value = _tokens(_field(usage, key))
        if value is not None:
            return value, True
    for key in ('prompt_tokens_details', 'input_tokens_details'):
        value = _tokens(_field(_field(usage, key), 'cached_tokens'))
        if value is not None:
            return value, True
    return 0, False
