"""
角色融合API路由
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional
from app.services.rolefusionservice import role_fusion_service

router = APIRouter()


class RoleInfo(BaseModel):
    role_id: str
    knowledge_domain: List[str]
    personality: Optional[str] = None


class RoleFusionRequest(BaseModel):
    question: str
    available_roles: List[RoleInfo]
    role_responses: Dict[str, str]  # {role_id: response}


@router.post("/role-fusion/fuse")
async def fuse_roles(request: RoleFusionRequest):
    """
    融合多个角色的回答
    
    示例：
    {
        "question": "我想创业，需要法律和商业建议",
        "available_roles": [
            {"role_id": "lawyer", "knowledge_domain": ["法律", "合同"]},
            {"role_id": "business", "knowledge_domain": ["商业", "策略"]}
        ],
        "role_responses": {
            "lawyer": "从法律角度，需要注意合同条款...",
            "business": "从商业角度，建议考虑市场策略..."
        }
    }
    """
    try:
        # 转换角色信息
        roles = []
        for role_info in request.available_roles:
            roles.append({
                "role_id": role_info.role_id,
                "knowledge_domain": role_info.knowledge_domain,
                "personality": role_info.personality or ""
            })
        
        # 执行角色融合
        fused_result = role_fusion_service.fuse_role_responses(
            question=request.question,
            available_roles=roles,
            role_responses=request.role_responses
        )
        
        return {
            "success": True,
            "data": fused_result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"角色融合失败: {str(e)}")


@router.post("/role-fusion/weights")
async def calculate_role_weights(
    question: str,
    available_roles: List[RoleInfo]
):
    """计算角色权重（不融合回答）"""
    try:
        roles = []
        for role_info in available_roles:
            roles.append({
                "role_id": role_info.role_id,
                "knowledge_domain": role_info.knowledge_domain,
                "personality": role_info.personality or ""
            })
        
        weights = role_fusion_service._calculate_role_weights(question, roles)
        
        return {
            "success": True,
            "data": {
                "weights": weights,
                "question": question
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"权重计算失败: {str(e)}")





