"""activation 公开门面：仅重导出，合同定义以 contracts 为唯一来源。

TODO(P0)：新增实现完成验收后再扩展 __all__；导入不得创建外部资源。
"""

from safe.contracts.activation import ActivationEnvelope
from safe.ports.activation_codec import ActivationCodec

__all__ = ['ActivationEnvelope', 'ActivationCodec']
