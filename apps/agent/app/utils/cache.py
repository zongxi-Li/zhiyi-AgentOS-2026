"""
缓存工具
"""
from functools import wraps
from typing import Callable, Any
import hashlib
import json
import time

# 简单的内存缓存（生产环境应使用Redis）
_cache = {}
_cache_ttl = {}

def cached(ttl: int = 3600):
    """
    缓存装饰器
    
    Args:
        ttl: 缓存时间（秒）
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 生成缓存键
            cache_key = _generate_cache_key(func.__name__, args, kwargs)
            
            # 检查缓存
            if cache_key in _cache:
                cached_data, cached_time = _cache[cache_key]
                if time.time() - cached_time < ttl:
                    return cached_data
            
            # 执行函数
            result = await func(*args, **kwargs)
            
            # 存储缓存
            _cache[cache_key] = (result, time.time())
            
            return result
        
        return wrapper
    return decorator

def _generate_cache_key(func_name: str, args: tuple, kwargs: dict) -> str:
    """生成缓存键"""
    key_data = {
        "func": func_name,
        "args": str(args),
        "kwargs": json.dumps(kwargs, sort_keys=True)
    }
    key_string = json.dumps(key_data, sort_keys=True)
    return hashlib.md5(key_string.encode()).hexdigest()

def clear_cache():
    """清除所有缓存"""
    _cache.clear()
    _cache_ttl.clear()

