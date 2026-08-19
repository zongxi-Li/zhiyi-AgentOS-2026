"""
银河麒麟系统集成API路由
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Optional
from app.services.kylinosintegration import kylin_os_integration_service

router = APIRouter()


class ExecuteCommandRequest(BaseModel):
    command: str
    require_sudo: bool = False


class CreateShortcutRequest(BaseModel):
    name: str
    command: str
    icon: Optional[str] = None


@router.get("/kylin-os/system-info")
async def get_system_info():
    """获取系统信息"""
    try:
        info = kylin_os_integration_service.get_system_info()
        return {
            "success": True,
            "data": info
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取系统信息失败: {str(e)}")


@router.get("/kylin-os/resources")
async def monitor_resources():
    """监控系统资源"""
    try:
        resources = kylin_os_integration_service.monitor_system_resources()
        return {
            "success": True,
            "data": resources
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"监控系统资源失败: {str(e)}")


@router.get("/kylin-os/security")
async def get_security_status():
    """获取安全状态"""
    try:
        security = kylin_os_integration_service.get_security_status()
        return {
            "success": True,
            "data": security
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取安全状态失败: {str(e)}")


@router.post("/kylin-os/execute-command")
async def execute_command(request: ExecuteCommandRequest):
    """执行系统命令（需要谨慎使用）"""
    try:
        result = kylin_os_integration_service.execute_system_command(
            command=request.command,
            require_sudo=request.require_sudo
        )
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        return {
            "success": True,
            "data": result
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"执行命令失败: {str(e)}")


@router.post("/kylin-os/create-shortcut")
async def create_shortcut(request: CreateShortcutRequest):
    """创建系统级快捷方式"""
    try:
        result = kylin_os_integration_service.create_system_shortcut(
            name=request.name,
            command=request.command,
            icon=request.icon
        )
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建快捷方式失败: {str(e)}")





