"""
重试工具
"""
import asyncio
import logging
from typing import Callable, TypeVar, Any

logger = logging.getLogger(__name__)

T = TypeVar('T')

async def retry_async(
    func: Callable[..., Any],
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    *args,
    **kwargs
) -> Any:
    """
    异步重试装饰器
    
    Args:
        func: 要重试的函数
        max_attempts: 最大尝试次数
        delay: 初始延迟（秒）
        backoff: 退避倍数
        exceptions: 需要重试的异常类型
        *args, **kwargs: 函数参数
    """
    attempt = 0
    current_delay = delay
    
    while attempt < max_attempts:
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        except exceptions as e:
            attempt += 1
            if attempt >= max_attempts:
                logger.error(f"重试{max_attempts}次后仍然失败: {e}")
                raise
            
            logger.warning(f"第{attempt}次尝试失败: {e}，{current_delay}秒后重试")
            await asyncio.sleep(current_delay)
            current_delay *= backoff
    
    raise Exception("重试失败")

