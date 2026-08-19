"""
增强RAG服务
集成高级RAG功能，支持更智能的检索和生成
"""
import logging
from typing import Dict, List, Optional
from app.services.ragservice import RAGService
from app.services.knowledgegraphservice import KnowledgeGraphService

logger = logging.getLogger(__name__)


class EnhancedRAGService:
    """增强RAG服务"""
    
    def __init__(self):
        self.rag_service = RAGService(use_vector_db=True)
        self.kg_service = KnowledgeGraphService()
    
    def enhanced_query(
        self,
        query: str,
        top_k: int = 5,
        use_knowledge_graph: bool = True,
        use_reranking: bool = True
    ) -> Dict:
        """
        增强查询（结合知识图谱和重排序）
        
        Args:
            query: 查询文本
            top_k: 返回结果数量
            use_knowledge_graph: 是否使用知识图谱
            use_reranking: 是否使用重排序
        
        Returns:
            增强的检索结果
        """
        # 1. 基础RAG检索
        rag_results = self.rag_service.search(query, top_k=top_k * 2)  # 获取更多候选
        
        # 2. 知识图谱增强（如果启用）
        kg_results = []
        if use_knowledge_graph:
            try:
                # 从知识图谱中查找相关实体和关系
                entities = self.kg_service.extract_entities(query)
                
                # 查找相关路径
                for entity in entities[:3]:  # 最多3个实体
                    paths = self.kg_service.find_paths(entity, max_depth=2)
                    kg_results.extend(paths)
            except Exception as e:
                logger.warning(f"知识图谱增强失败: {e}")
        
        # 3. 重排序（如果启用）
        if use_reranking:
            reranked_results = self._rerank_results(rag_results, query, kg_results)
        else:
            reranked_results = rag_results
        
        # 4. 融合结果
        fused_results = self._fuse_results(reranked_results, kg_results, top_k)
        
        return {
            "query": query,
            "results": fused_results,
            "rag_count": len(rag_results),
            "kg_count": len(kg_results),
            "use_kg": use_knowledge_graph,
            "use_reranking": use_reranking
        }
    
    def _rerank_results(
        self,
        rag_results: List[Dict],
        query: str,
        kg_results: List[Dict]
    ) -> List[Dict]:
        """
        重排序结果（增强实现）
        
        使用多种策略进行重排序：
        1. 向量相似度分数
        2. 知识图谱匹配度
        3. 查询词匹配度
        4. 文档位置权重
        5. 文档长度归一化
        """
        try:
            # 尝试使用embedding服务计算查询-文档相似度
            from app.services.embeddingservice import embedding_service
            import asyncio
            
            # 异步计算查询向量
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    query_embedding = asyncio.create_task(embedding_service.generate_embedding(query))
                    query_embedding = loop.run_until_complete(query_embedding)
                else:
                    query_embedding = loop.run_until_complete(embedding_service.generate_embedding(query))
            except RuntimeError:
                query_embedding = asyncio.run(embedding_service.generate_embedding(query))
            
            # 计算每个结果的增强分数
            for i, result in enumerate(rag_results):
                base_score = result.get("score", 0.0)
                rerank_score = base_score
                
                # 1. 向量相似度（如果结果有embedding）
                if "embedding" in result and query_embedding:
                    doc_embedding = result["embedding"]
                    if len(doc_embedding) == len(query_embedding):
                        # 计算余弦相似度
                        dot_product = sum(a * b for a, b in zip(query_embedding, doc_embedding))
                        norm_a = sum(a * a for a in query_embedding) ** 0.5
                        norm_b = sum(b * b for b in doc_embedding) ** 0.5
                        if norm_a > 0 and norm_b > 0:
                            cosine_sim = dot_product / (norm_a * norm_b)
                            rerank_score = rerank_score * 0.6 + cosine_sim * 0.4
                
                # 2. 知识图谱匹配度
                doc_id = result.get("doc_id", "")
                kg_match = False
                for kg_result in kg_results:
                    if doc_id in str(kg_result) or doc_id in str(kg_result.get("entity", "")):
                        kg_match = True
                        rerank_score += 0.15  # 知识图谱匹配加分
                        break
                
                # 3. 查询词匹配度（TF-IDF风格）
                query_words = set(query.lower().split())
                content = result.get("content", "").lower()
                content_words = content.split()
                if content_words:
                    # 计算查询词在文档中的频率
                    match_ratio = sum(1 for word in query_words if word in content_words) / len(query_words) if query_words else 0
                    rerank_score += match_ratio * 0.1
                
                # 4. 文档位置权重（前面的结果稍微加分）
                position_weight = 1.0 - (i * 0.01)  # 每往后一个位置减0.01
                rerank_score *= position_weight
                
                # 5. 文档长度归一化（避免过长文档占优势）
                content_length = len(content)
                if content_length > 0:
                    length_norm = min(1.0, 500.0 / content_length)  # 500字为基准
                    rerank_score *= (0.8 + length_norm * 0.2)  # 长度归一化
                
                result["rerank_score"] = rerank_score
                result["rerank_method"] = "enhanced"
            
        except Exception as e:
            logger.warning(f"增强重排序失败: {e}，使用简化实现")
            # 降级到简化实现
            for result in rag_results:
                score = result.get("score", 0.0)
                
                # 检查是否在知识图谱结果中
                doc_id = result.get("doc_id", "")
                for kg_result in kg_results:
                    if doc_id in str(kg_result):
                        score += 0.2
                
                # 查询词匹配度
                query_words = query.lower().split()
                content = result.get("content", "").lower()
                match_count = sum(1 for word in query_words if word in content)
                score += match_count * 0.1
                
                result["rerank_score"] = score
                result["rerank_method"] = "simplified"
        
        # 按重排序分数排序
        reranked = sorted(rag_results, key=lambda x: x.get("rerank_score", 0.0), reverse=True)
        
        return reranked
    
    def _fuse_results(
        self,
        rag_results: List[Dict],
        kg_results: List[Dict],
        top_k: int
    ) -> List[Dict]:
        """融合RAG和知识图谱结果"""
        fused = []
        
        # 添加RAG结果
        for result in rag_results[:top_k]:
            fused.append({
                "type": "rag",
                "content": result.get("content", ""),
                "score": result.get("rerank_score", result.get("score", 0.0)),
                "source": result.get("filename", "unknown"),
                "metadata": result.get("metadata", {})
            })
        
        # 添加知识图谱结果（去重）
        seen_entities = set()
        for kg_result in kg_results[:top_k // 2]:
            entity = kg_result.get("entity", "")
            if entity not in seen_entities:
                seen_entities.add(entity)
                fused.append({
                    "type": "knowledge_graph",
                    "content": f"实体: {entity}, 关系: {kg_result.get('relation', '')}",
                    "score": 0.8,  # 知识图谱结果默认分数
                    "source": "knowledge_graph",
                    "metadata": kg_result
                })
        
        # 按分数排序
        fused.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        
        return fused[:top_k]
    
    def build_enhanced_context(
        self,
        query: str,
        search_results: List[Dict]
    ) -> str:
        """
        构建增强上下文
        
        Args:
            query: 查询文本
            search_results: 搜索结果
        
        Returns:
            增强后的上下文
        """
        context_parts = [f"用户查询: {query}\n\n"]
        
        # 添加RAG结果
        rag_results = [r for r in search_results if r.get("type") == "rag"]
        if rag_results:
            context_parts.append("相关文档内容:\n")
            for i, result in enumerate(rag_results[:3], 1):
                context_parts.append(
                    f"[文档{i}] {result.get('source', '未知')}\n"
                    f"{result.get('content', '')[:300]}\n"
                )
        
        # 添加知识图谱结果
        kg_results = [r for r in search_results if r.get("type") == "knowledge_graph"]
        if kg_results:
            context_parts.append("\n相关知识:\n")
            for result in kg_results[:2]:
                context_parts.append(f"- {result.get('content', '')}\n")
        
        return "\n".join(context_parts)


# 全局增强RAG服务实例
enhanced_rag_service = EnhancedRAGService()





