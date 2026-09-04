"""
联邦学习全局模型API
提供云端模型管理接口
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional
from app.services.globalmodelmanager import global_model_manager

router = APIRouter()


class InitializeModelRequest(BaseModel):
    """初始化模型请求"""
    model_type: str
    model_params: Dict
    training_data_info: Dict
    
    # 解决 Pydantic v2 命名空间冲突
    model_config = {"protected_namespaces": ()}


class RegisterClientRequest(BaseModel):
    """注册客户端请求"""
    client_id: str
    client_info: Dict


class UploadUpdateRequest(BaseModel):
    """上传参数更新请求"""
    client_id: str
    encrypted_update: Dict
    update_metadata: Dict


@router.post("/global-model/initialize")
async def initialize_base_model(request: InitializeModelRequest):
    """初始化基础模型"""
    try:
        version_id = global_model_manager.initialize_base_model(
            model_type=request.model_type,
            model_params=request.model_params,
            training_data_info=request.training_data_info
        )
        
        return {
            'success': True,
            'version_id': version_id,
            'message': '基础模型已初始化'
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/global-model/register-client")
async def register_client(request: RegisterClientRequest):
    """注册客户端"""
    try:
        result = global_model_manager.register_client(
            client_id=request.client_id,
            client_info=request.client_info
        )
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/global-model/download/{client_id}")
async def download_model(client_id: str):
    """下载全局模型"""
    try:
        model_info = global_model_manager.distribute_model(client_id)
        
        return {
            'success': True,
            'model': model_info
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/global-model/upload-update")
async def upload_update(request: UploadUpdateRequest):
    """上传参数更新"""
    try:
        result = global_model_manager.collect_update(
            client_id=request.client_id,
            encrypted_update=request.encrypted_update,
            update_metadata=request.update_metadata
        )
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/global-model/aggregate")
async def aggregate_updates(min_clients: int = 3):
    """聚合参数更新"""
    try:
        result = global_model_manager.aggregate_updates(min_clients=min_clients)
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/global-model/history")
async def get_model_history():
    """获取模型历史"""
    try:
        history = global_model_manager.get_model_history()
        
        return {
            'success': True,
            'history': history
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/global-model/clients")
async def get_client_statistics():
    """获取客户端统计"""
    try:
        stats = global_model_manager.get_client_statistics()
        
        return {
            'success': True,
            'statistics': stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

