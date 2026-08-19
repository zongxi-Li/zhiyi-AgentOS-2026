"""
数字人模型选择API路由
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Optional
from app.services.digitalhumanmodelselector import digital_human_model_selector

router = APIRouter()


class SelectModelRequest(BaseModel):
    role_config: Dict
    task: str = "avatar"  # avatar/animation/emotion
    priority: str = "balanced"  # speed/quality/balance


@router.post("/digital-human-model/select")
async def select_digital_human_model(request: SelectModelRequest):
    """为数字人任务选择模型"""
    try:
        if request.task == "avatar":
            model_name = digital_human_model_selector.select_avatar_model(
                role_config=request.role_config,
                priority=request.priority
            )
        elif request.task == "animation":
            model_name = digital_human_model_selector.select_animation_model(
                animation_type="gesture",
                priority=request.priority
            )
        elif request.task == "emotion":
            model_name = digital_human_model_selector.select_emotion_model(
                emotion_task="recognition",
                priority=request.priority
            )
        else:
            raise HTTPException(status_code=400, detail=f"不支持的任务类型: {request.task}")
        
        return {
            "success": True,
            "data": {
                "model_name": model_name,
                "task": request.task,
                "priority": request.priority
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"选择模型失败: {str(e)}")


@router.post("/digital-human-model/generate")
async def generate_with_selected_model(request: SelectModelRequest):
    """使用选中的模型生成数字人内容"""
    try:
        result = digital_human_model_selector.generate_with_selected_model(
            role_config=request.role_config,
            task=request.task,
            priority=request.priority
        )
        
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成内容失败: {str(e)}")





