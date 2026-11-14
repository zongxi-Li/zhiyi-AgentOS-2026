"""本机固定分词器和增量文本解码；云端不处理原文。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P2-1)：从批准本地目录加载 tokenizer/config/chat template，逐一验证 manifest 哈希。
TODO(P2-2)：模板与 special token 完全冻结；模板应用后检查prompt≤128、总长≤160。
TODO(P2-3)：定义增量 detokenize、特殊token隐藏与EOS；禁止把prompt或tokenIDs写日志。
TODO(P2-4)：在线下载和远程模型代码保持关闭；缺失制品直接不可用。

验收：中英文、多字节字符、空模板、特殊token及边界长度与完整模型一致。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
