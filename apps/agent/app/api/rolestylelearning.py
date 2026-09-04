"""
角色风格学习API路由
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional
from app.services.rolestylelearningservice import role_style_learning_service

router = APIRouter()


class StyleExample(BaseModel):
    user: str
    role: str


class LearnRoleStyleRequest(BaseModel):
    role_id: str
    description: Optional[str] = None
    style_examples: Optional[List[StyleExample]] = None


@router.post("/role-style-learning/learn")
async def learn_role_style(request: LearnRoleStyleRequest):
    """
    学习角色风格
    
    示例：
    {
        "role_id": "custom_role_1",
        "description": "一位耐心的心理咨询师，擅长倾听和引导",
        "style_examples": [
            {
                "user": "我最近很焦虑",
                "role": "我理解你的感受，能详细说说是什么让你感到焦虑吗？"
            },
            {
                "user": "工作压力大",
                "role": "工作压力确实会影响我们的情绪，你平时是如何缓解压力的呢？"
            }
        ]
    }
    """
    try:
        # 转换示例格式
        examples = None
        if request.style_examples:
            examples = [{"user": ex.user, "role": ex.role} for ex in request.style_examples]
        
        learned_style = role_style_learning_service.learn_role_style(
            role_id=request.role_id,
            description=request.description,
            style_examples=examples
        )
        
        return {
            "success": True,
            "data": learned_style
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"学习角色风格失败: {str(e)}")


@router.get("/role-style-learning/{role_id}")
async def get_learned_style(role_id: str):
    """获取学习到的角色风格"""
    try:
        learned_style = role_style_learning_service.style_learner.get_learned_style(role_id)
        
        if not learned_style:
            return {
                "success": False,
                "message": f"角色 {role_id} 尚未学习风格"
            }
        
        return {
            "success": True,
            "data": learned_style
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取学习风格失败: {str(e)}")


@router.post("/role-style-learning/parse-description")
async def parse_description(description: str):
    """解析角色描述"""
    try:
        parsed = role_style_learning_service.description_parser.parse_description(description)
        return {
            "success": True,
            "data": parsed
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析描述失败: {str(e)}")





