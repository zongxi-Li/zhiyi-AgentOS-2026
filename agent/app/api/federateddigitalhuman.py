"""
联邦学习数字人API路由
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional
from app.services.federateddigitalhuman import federated_digital_human_service

router = APIRouter()


class GenerateOptimizedAvatarRequest(BaseModel):
    role_config: Dict
    use_federated_model: bool = True


class OptimizeModelRequest(BaseModel):
    training_data: List[Dict]
    role_id: str


@router.post("/federated-digital-human/generate-avatar")
async def generate_optimized_avatar(request: GenerateOptimizedAvatarRequest):
    """使用联邦学习优化的模型生成数字人形象"""
    try:
        avatar = federated_digital_human_service.generate_optimized_avatar(
            role_config=request.role_config,
            use_federated_model=request.use_federated_model
        )
        
        return {
            "success": True,
            "data": avatar
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成数字人形象失败: {str(e)}")


@router.post("/federated-digital-human/optimize-model")
async def optimize_voice_driven_model(request: OptimizeModelRequest):
    """使用联邦学习优化语音驱动模型"""
    try:
        result = federated_digital_human_service.optimize_voice_driven_model(
            training_data=request.training_data,
            role_id=request.role_id
        )
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"优化模型失败: {str(e)}")





