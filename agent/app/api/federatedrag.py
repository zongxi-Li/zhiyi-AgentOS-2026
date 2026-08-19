"""
RAG联邦优化API
提供RAG联邦学习优化接口
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional
from app.services.federatedragoptimizer import federated_rag_optimizer

router = APIRouter()


class CollectRAGStatsRequest(BaseModel):
    """收集RAG统计请求"""
    client_id: str
    rag_stats: Dict


class OptimizeParamsRequest(BaseModel):
    """优化参数请求"""
    strategy: str = 'balanced'  # balanced/precision/recall/speed


class TrainSemanticModelRequest(BaseModel):
    """训练语义模型请求"""
    global_queries: List[str]


@router.post("/federated-rag/collect-stats")
async def collect_rag_stats(request: CollectRAGStatsRequest):
    """
    收集客户端RAG统计
    
    注意：只收集统计数据，不收集原始文档
    """
    try:
        result = federated_rag_optimizer.collect_client_stats(
            client_id=request.client_id,
            rag_stats=request.rag_stats
        )
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/federated-rag/analyze-patterns")
async def analyze_retrieval_patterns():
    """分析全局检索模式"""
    try:
        analysis = federated_rag_optimizer.analyze_retrieval_patterns()
        
        return {
            'success': True,
            'analysis': analysis
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/federated-rag/optimize-params")
async def optimize_global_parameters(request: OptimizeParamsRequest):
    """优化全局RAG参数"""
    try:
        result = federated_rag_optimizer.optimize_global_parameters(
            strategy=request.strategy
        )
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/federated-rag/get-params/{client_id}")
async def get_optimized_params(client_id: str):
    """获取优化参数（针对特定客户端）"""
    try:
        params = federated_rag_optimizer.get_optimized_params_for_client(client_id)
        
        return {
            'success': True,
            'params': params
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/federated-rag/train-semantic-model")
async def train_semantic_model(request: TrainSemanticModelRequest):
    """训练全局语义增强模型"""
    try:
        result = federated_rag_optimizer.train_semantic_enhancement_model(
            global_queries=request.global_queries
        )
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/federated-rag/status")
async def get_optimization_status():
    """获取RAG联邦优化状态"""
    try:
        status = federated_rag_optimizer.get_optimization_status()
        
        return {
            'success': True,
            'status': status
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

