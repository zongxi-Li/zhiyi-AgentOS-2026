"""
性能监控API路由
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Optional
from app.services.performancemonitor import performance_monitor, performance_optimizer

router = APIRouter()


class RecordMetricRequest(BaseModel):
    metric_name: str
    value: float
    tags: Optional[Dict] = None


@router.post("/performance/metric")
async def record_metric(request: RecordMetricRequest):
    """
    记录性能指标
    
    示例：
    {
        "metric_name": "response_time",
        "value": 1.5,
        "tags": {"endpoint": "/api/chat", "method": "POST"}
    }
    """
    try:
        performance_monitor.record_metric(
            metric_name=request.metric_name,
            value=request.value,
            tags=request.tags
        )
        return {
            "success": True,
            "message": "指标已记录"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"记录指标失败: {str(e)}")


@router.get("/performance/system")
async def get_system_metrics():
    """获取系统性能指标"""
    try:
        metrics = performance_monitor.get_system_metrics()
        return {
            "success": True,
            "data": metrics
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取系统指标失败: {str(e)}")


@router.get("/performance/metric/{metric_name}")
async def get_metric_statistics(metric_name: str, hours: int = 1):
    """
    获取指标统计
    
    参数：
    - metric_name: 指标名称
    - hours: 时间范围（小时）
    """
    try:
        stats = performance_monitor.get_metric_statistics(metric_name, hours)
        return {
            "success": True,
            "data": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取指标统计失败: {str(e)}")


@router.get("/performance/summary")
async def get_performance_summary():
    """获取性能摘要"""
    try:
        summary = performance_monitor.get_performance_summary()
        return {
            "success": True,
            "data": summary
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取性能摘要失败: {str(e)}")


@router.get("/performance/alerts")
async def get_recent_alerts(limit: int = 10):
    """获取最近的告警"""
    try:
        alerts = performance_monitor.get_recent_alerts(limit)
        return {
            "success": True,
            "data": alerts
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取告警失败: {str(e)}")


@router.get("/performance/suggestions")
async def get_optimization_suggestions():
    """获取优化建议"""
    try:
        suggestions = performance_optimizer.analyze_and_suggest()
        return {
            "success": True,
            "data": suggestions
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取优化建议失败: {str(e)}")


@router.post("/performance/cleanup")
async def cleanup_old_metrics(days: int = 7):
    """清理旧指标"""
    try:
        performance_monitor.clear_old_metrics(days)
        return {
            "success": True,
            "message": f"已清理{days}天前的指标"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清理指标失败: {str(e)}")





