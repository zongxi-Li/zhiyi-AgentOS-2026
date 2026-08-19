"""
模型选择API路由
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Optional
from app.services.modelselector import model_selector, ModelType

router = APIRouter()


class SelectModelRequest(BaseModel):
    priority: str = "balance"  # speed/quality/balance
    available_resources: float = 1.0
    task_type: Optional[str] = None
    use_performance_data: bool = True


class RecordPerformanceRequest(BaseModel):
    """记录模型性能请求"""
    model_type: str  # fast/balanced/advanced
    response_time: float
    quality_score: float = 0.5
    success: bool = True
    task_type: Optional[str] = None
    
    # 解决 Pydantic v2 命名空间冲突（model_type 与 protected namespace "model_" 冲突）
    model_config = {"protected_namespaces": ()}


@router.post("/model-selector/select")
async def select_model(request: SelectModelRequest):
    """
    选择最优模型
    
    示例：
    {
        "priority": "balance",
        "available_resources": 0.8,
        "task_type": "chat",
        "use_performance_data": true
    }
    """
    try:
        selected_model = model_selector.select_model(
            priority=request.priority,
            available_resources=request.available_resources,
            task_type=request.task_type,
            use_performance_data=request.use_performance_data
        )
        
        model_info = model_selector.get_model_info(selected_model)
        
        return {
            "success": True,
            "data": {
                "selected_model": selected_model.value,
                "model_info": model_info
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"模型选择失败: {str(e)}")


@router.post("/model-selector/performance")
async def record_performance(request: RecordPerformanceRequest):
    """
    记录模型性能
    
    示例：
    {
        "model_type": "balanced",
        "response_time": 1.2,
        "quality_score": 0.85,
        "success": true,
        "task_type": "chat"
    }
    """
    try:
        # 转换模型类型
        model_type_map = {
            "fast": ModelType.FAST,
            "balanced": ModelType.BALANCED,
            "advanced": ModelType.ADVANCED
        }
        
        model_type = model_type_map.get(request.model_type)
        if not model_type:
            raise ValueError(f"无效的模型类型: {request.model_type}")
        
        model_selector.record_performance(
            model_type=model_type,
            response_time=request.response_time,
            quality_score=request.quality_score,
            success=request.success,
            task_type=request.task_type
        )
        
        return {
            "success": True,
            "message": "性能数据已记录"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"记录性能失败: {str(e)}")


@router.get("/model-selector/statistics")
async def get_performance_statistics(model_type: Optional[str] = None):
    """
    获取性能统计
    
    参数：
    - model_type: 模型类型（可选，fast/balanced/advanced）
    """
    try:
        if model_type:
            model_type_map = {
                "fast": ModelType.FAST,
                "balanced": ModelType.BALANCED,
                "advanced": ModelType.ADVANCED
            }
            mt = model_type_map.get(model_type)
            if not mt:
                raise ValueError(f"无效的模型类型: {model_type}")
            stats = model_selector.get_performance_statistics(mt)
        else:
            stats = model_selector.get_performance_statistics()
        
        return {
            "success": True,
            "data": stats
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}")


@router.get("/model-selector/current")
async def get_current_model():
    """获取当前使用的模型"""
    try:
        current = model_selector.get_current_model()
        model_info = model_selector.get_model_info(current)
        
        return {
            "success": True,
            "data": {
                "current_model": current.value,
                "model_info": model_info
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取当前模型失败: {str(e)}")


@router.get("/model-selector/history")
async def get_switch_history(limit: int = 10):
    """获取模型切换历史"""
    try:
        history = model_selector.get_switch_history(limit)
        return {
            "success": True,
            "data": history
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取切换历史失败: {str(e)}")





