"""manifest 公开门面：仅重导出，合同定义以 contracts 为唯一来源。

TODO(P0)：新增实现完成验收后再扩展 __all__；导入不得创建外部资源。
"""

from safe.contracts.manifest import SplitModelManifest

__all__ = ['SplitModelManifest']
