"""
通信优化API路由
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List
from app.services.communicationoptimizer import communication_optimizer

router = APIRouter()


class SendOptimizedRequest(BaseModel):
    data: Dict
    target: str
    use_batching: bool = True
    use_compression: bool = True
    use_cache: bool = True


class OptimizeFederatedRequest(BaseModel):
    client_updates: List[Dict]
    compression: bool = True
    batching: bool = True


@router.post("/communication-optimizer/send")
async def send_optimized(request: SendOptimizedRequest):
    """发送优化后的消息"""
    try:
        result = await communication_optimizer.send_optimized(
            data=request.data,
            target=request.target,
            use_batching=request.use_batching,
            use_compression=request.use_compression,
            use_cache=request.use_cache
        )
        
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"发送消息失败: {str(e)}")


@router.post("/communication-optimizer/optimize-federated")
async def optimize_federated_communication(request: OptimizeFederatedRequest):
    """优化联邦学习通信"""
    try:
        result = communication_optimizer.optimize_federated_communication(
            client_updates=request.client_updates,
            compression=request.compression,
            batching=request.batching
        )
        
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"优化通信失败: {str(e)}")


@router.get("/communication-optimizer/stats")
async def get_optimization_stats():
    """获取优化统计"""
    try:
        stats = communication_optimizer.get_optimization_stats()
        return {
            "success": True,
            "data": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}")





