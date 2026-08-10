"""AgentOS Core 的适配器 retrieval_adapter 模块，连接模型、检索和联邦增强等外部能力。"""



from retrieval.chroma_client import chroma_client, chroma_legal_client
from retrieval.code_index_builder import build_code_index, code_index_builder, search_code
from retrieval.education_index_builder import education_index_builder
from retrieval.legal_index_builder import legal_index_builder

__all__ = [
    "build_code_index",
    "chroma_client",
    "chroma_legal_client",
    "code_index_builder",
    "education_index_builder",
    "legal_index_builder",
    "search_code",
]
