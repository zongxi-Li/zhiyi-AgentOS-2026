"""
性能优化API路由
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional
from app.services.performanceoptimizer import performance_optimizer

router = APIRouter()


class OptimizeMultimodalRequest(BaseModel):
    processing_tasks: List[Dict]


class OptimizeConcurrentRequest(BaseModel):
    concurrent_limit: int = 10


class OptimizeVoiceRequest(BaseModel):
    sample_rate: int = 16000
    duration: Optional[float] = None


class OptimizeGenerationRequest(BaseModel):
    generation_type: str  # text/image/video
    quality_level: str = "balanced"  # speed/balanced/quality


@router.get("/performance-optimizer/system")
async def optimize_system_performance():
    """优化系统性能"""
    try:
        result = performance_optimizer.optimize_system_performance()
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"优化系统性能失败: {str(e)}")


@router.post("/performance-optimizer/multimodal")
async def optimize_multimodal_processing(request: OptimizeMultimodalRequest):
    """优化多模态处理性能"""
    try:
        result = performance_optimizer.optimize_multimodal_processing(
            processing_tasks=request.processing_tasks
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"优化多模态处理失败: {str(e)}")


@router.post("/performance-optimizer/concurrent")
async def optimize_concurrent_processing(request: OptimizeConcurrentRequest):
    """优化并发处理性能"""
    try:
        result = performance_optimizer.optimize_concurrent_processing(
            concurrent_limit=request.concurrent_limit
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"优化并发处理失败: {str(e)}")


@router.post("/performance-optimizer/voice")
async def optimize_voice_processing(request: OptimizeVoiceRequest):
    """优化语音处理性能"""
    try:
        # 模拟音频数据
        audio_data = b'\x00' * int(request.sample_rate * 2 * (request.duration or 1.0))
        
        result = performance_optimizer.optimize_voice_processing(
            audio_data=audio_data,
            sample_rate=request.sample_rate
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"优化语音处理失败: {str(e)}")


@router.post("/performance-optimizer/generation")
async def optimize_generation_quality(request: OptimizeGenerationRequest):
    """优化生成质量"""
    try:
        result = performance_optimizer.optimize_generation_quality(
            generation_type=request.generation_type,
            quality_level=request.quality_level
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"优化生成质量失败: {str(e)}")

