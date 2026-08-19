"""
文本向量化服务
支持多种embedding模型（通义千问、OpenAI等）
"""
import logging
import httpx
from typing import List, Dict, Optional
from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """文本向量化服务"""
    
    def __init__(self):
        """初始化向量化服务"""
        # 获取API密钥
        self.api_key = getattr(settings, 'DASHSCOPE_API_KEY', '') or getattr(settings, 'QWEN_API_KEY', '')
        self.model = "text-embedding-v2"  # 通义千问embedding模型
        self.base_url = "https://dashscope.aliyuncs.com/api/v1"
        
        if not self.api_key:
            logger.warning("未配置API密钥，文本向量化将使用简化实现（TF-IDF）")
        else:
            logger.info(f"文本向量化服务已初始化，模型: {self.model}")
    
    async def generate_embedding(self, text: str) -> List[float]:
        """
        生成文本向量（使用通义千问embedding API）
        
        Args:
            text: 输入文本
        
        Returns:
            文本向量（浮点数列表）
        """
        if not self.api_key:
            # 如果没有API密钥，使用简化的TF-IDF方法
            logger.debug("使用TF-IDF简化实现（未配置API密钥）")
            return self._tfidf_embedding(text)
        
        try:
            # 通义千问embedding API端点
            embedding_url = f"{self.base_url}/services/embeddings/text-embedding/text-embedding"
            
            # 构建请求数据
            request_data = {
                "model": self.model,
                "input": {
                    "texts": [text]  # 支持批量，这里单个文本
                }
            }
            
            # 创建HTTP客户端
            async with httpx.AsyncClient(timeout=30.0) as client:
                # 调用API
                response = await client.post(
                    embedding_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json=request_data
                )
                
                # 检查响应状态
                response.raise_for_status()
                result = response.json()
                
                # 解析响应
                if result.get("output"):
                    output = result["output"]
                    embeddings = output.get("embeddings", [])
                    if embeddings and len(embeddings) > 0:
                        embedding = embeddings[0].get("embedding", [])
                        if embedding:
                            logger.debug(f"文本向量化成功: {len(text)} 字符, 向量维度: {len(embedding)}")
                            return embedding
                
                error_msg = result.get("message", "API返回格式错误")
                logger.error(f"文本向量化API返回错误: {result}")
                raise ValueError(f"文本向量化API错误: {error_msg}")
                
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_response = e.response.json()
                error_detail = error_response.get("message", str(e))
            except:
                error_detail = str(e)
            
            logger.warning(f"文本向量化API调用失败: {error_detail}，使用TF-IDF降级方案")
            return self._tfidf_embedding(text)
        except Exception as e:
            logger.warning(f"文本向量化API调用异常: {e}，使用TF-IDF降级方案")
            return self._tfidf_embedding(text)
    
    async def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        批量生成文本向量
        
        Args:
            texts: 文本列表
        
        Returns:
            向量列表
        """
        if not self.api_key:
            # 如果没有API密钥，使用TF-IDF
            return [self._tfidf_embedding(text) for text in texts]
        
        try:
            # 通义千问embedding API端点
            embedding_url = f"{self.base_url}/services/embeddings/text-embedding/text-embedding"
            
            # 构建请求数据（批量）
            request_data = {
                "model": self.model,
                "input": {
                    "texts": texts
                }
            }
            
            # 创建HTTP客户端
            async with httpx.AsyncClient(timeout=60.0) as client:
                # 调用API
                response = await client.post(
                    embedding_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json=request_data
                )
                
                response.raise_for_status()
                result = response.json()
                
                # 解析响应
                if result.get("output"):
                    output = result["output"]
                    embeddings = output.get("embeddings", [])
                    if embeddings:
                        vectors = [emb.get("embedding", []) for emb in embeddings]
                        logger.debug(f"批量文本向量化成功: {len(texts)} 个文本")
                        return vectors
                
                error_msg = result.get("message", "API返回格式错误")
                raise ValueError(f"文本向量化API错误: {error_msg}")
                
        except Exception as e:
            logger.warning(f"批量文本向量化失败: {e}，使用TF-IDF降级方案")
            return [self._tfidf_embedding(text) for text in texts]
    
    def _tfidf_embedding(self, text: str, dimension: int = 128) -> List[float]:
        """
        TF-IDF简化向量化（降级方案）
        
        Args:
            text: 输入文本
            dimension: 向量维度
        
        Returns:
            文本向量
        """
        # 简化实现：使用词频向量
        import re
        from collections import Counter
        
        # 分词（简单实现）
        words = re.findall(r'\w+', text.lower())
        word_count = Counter(words)
        
        # 生成固定维度向量（基于词频）
        vector = [0.0] * dimension
        for i, (word, count) in enumerate(word_count.items()):
            # 简单的哈希映射到向量维度
            idx = hash(word) % dimension
            vector[idx] = float(count) / len(words) if words else 0.0
        
        # 归一化
        norm = sum(x * x for x in vector) ** 0.5
        if norm > 0:
            vector = [x / norm for x in vector]
        
        return vector


# 全局向量化服务实例
embedding_service = EmbeddingService()

