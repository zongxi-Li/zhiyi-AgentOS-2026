"""inference 公开门面：仅重导出，合同定义以 contracts 为唯一来源。

TODO(P0)：新增实现完成验收后再扩展 __all__；导入不得创建外部资源。
"""

from safe.contracts.inference import Capabilities, GenerationOptions, InferenceRequest, InferenceResult
from safe.contracts.manifest import SplitModelManifest
from safe.contracts.errors import ErrorCode, SafeError
from safe.application.inference import SplitInferenceService

__all__ = ['Capabilities', 'GenerationOptions', 'InferenceRequest', 'InferenceResult', 'SplitModelManifest', 'ErrorCode', 'SafeError', 'SplitInferenceService']
