"""
自适应学习API路由
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Optional
from app.services.adaptivelearningservice import adaptive_learning_service

router = APIRouter()


class FeedbackRequest(BaseModel):
    role_id: str
    conversation_id: str
    feedback_type: str  # quality/relevance/helpfulness/satisfaction
    feedback_value: float  # 0.0-1.0
    user_id: Optional[str] = None
    context: Optional[Dict] = None


class AdjustParametersRequest(BaseModel):
    role_id: str
    base_role_config: Dict


@router.post("/adaptive-learning/feedback")
async def submit_feedback(request: FeedbackRequest):
    """
    提交用户反馈
    
    示例：
    {
        "role_id": "lawyer",
        "conversation_id": "conv_123",
        "feedback_type": "quality",
        "feedback_value": 0.8,
        "user_id": "user_123"
    }
    """
    try:
        # 验证反馈值范围
        if not 0.0 <= request.feedback_value <= 1.0:
            raise ValueError("反馈值必须在0.0-1.0之间")
        
        # 验证反馈类型
        valid_types = ["quality", "relevance", "helpfulness", "satisfaction"]
        if request.feedback_type not in valid_types:
            raise ValueError(f"反馈类型必须是: {', '.join(valid_types)}")
        
        adaptive_learning_service.collect_feedback(
            role_id=request.role_id,
            conversation_id=request.conversation_id,
            feedback_type=request.feedback_type,
            feedback_value=request.feedback_value,
            user_id=request.user_id,
            context=request.context
        )
        
        return {
            "success": True,
            "message": "反馈已收集"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"提交反馈失败: {str(e)}")


@router.post("/adaptive-learning/adjust")
async def adjust_parameters(request: AdjustParametersRequest):
    """
    根据反馈调整角色参数
    
    示例：
    {
        "role_id": "lawyer",
        "base_role_config": {
            "personality": "严谨、专业",
            "response_length": 0.7,
            "detail_level": 0.6
        }
    }
    """
    try:
        adjusted_config = adaptive_learning_service.adjust_role_parameters(
            role_id=request.role_id,
            base_role_config=request.base_role_config
        )
        
        return {
            "success": True,
            "data": {
                "role_id": request.role_id,
                "adjusted_config": adjusted_config
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"参数调整失败: {str(e)}")


@router.get("/adaptive-learning/statistics/{role_id}")
async def get_learning_statistics(role_id: str):
    """获取角色学习统计信息"""
    try:
        stats = adaptive_learning_service.get_learning_statistics(role_id)
        return {
            "success": True,
            "data": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


@router.post("/adaptive-learning/reset/{role_id}")
async def reset_learning(role_id: str):
    """重置角色的学习数据"""
    try:
        adaptive_learning_service.reset_role_learning(role_id)
        return {
            "success": True,
            "message": f"角色 {role_id} 的学习数据已重置"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重置失败: {str(e)}")





