"""激活用例编排；只依赖 codec port 和纯规则。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P1-1)：注入 ActivationCodec；先验证 shape/raw bytes，不能接受任意 Python 对象。
TODO(P1-2)：从受信 manifest 和会话取得 hidden size/phase/position，不采信请求自报的策略。
TODO(P1-3)：本地出站顺序固定为隐私变换→编码→摘要→release 固定→签名；重试复用字节。
TODO(P1-4)：云端完成验签与会话绑定后解码；内部 tensor 只能由 runner 自行构造。

验收：不依赖 Torch/HTTP；畸形信封与超限输入不进入 runner。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
