"""
增强RAG API路由
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Dict, Optional
from app.services.ragenhanced import enhanced_rag_service

router = APIRouter()


class EnhancedQueryRequest(BaseModel):
    query: str
    top_k: int = 5
    use_knowledge_graph: bool = True
    use_reranking: bool = True


@router.post("/rag-enhanced/query")
async def enhanced_query(request: EnhancedQueryRequest):
    """
    增强RAG查询
    
    结合知识图谱和重排序的智能检索
    """
    try:
        result = enhanced_rag_service.enhanced_query(
            query=request.query,
            top_k=request.top_k,
            use_knowledge_graph=request.use_knowledge_graph,
            use_reranking=request.use_reranking
        )
        
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"增强查询失败: {str(e)}")


@router.post("/rag-enhanced/build-context")
async def build_enhanced_context(
    query: str = Form(...),
    top_k: int = Form(5)
):
    """构建增强上下文"""
    try:
        # 先查询
        query_result = enhanced_rag_service.enhanced_query(
            query=query,
            top_k=top_k
        )
        
        # 构建上下文
        context = enhanced_rag_service.build_enhanced_context(
            query=query,
            search_results=query_result.get("results", [])
        )
        
        return {
            "success": True,
            "data": {
                "context": context,
                "query": query,
                "result_count": len(query_result.get("results", []))
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"构建上下文失败: {str(e)}")





