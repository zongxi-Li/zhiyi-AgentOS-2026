"""
数字人API路由
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Dict, Optional
import logging
from app.paths import DIGITAL_HUMAN_IMAGE_DIR
from app.services.digitalhumanservice import digital_human_service

logger = logging.getLogger(__name__)
router = APIRouter()


class CreateDigitalHumanRequest(BaseModel):
    role_id: str
    personality: Optional[str] = None
    profession: Optional[str] = None
    style: Optional[str] = "realistic"
    name: Optional[str] = None  # 形象名称
    description: Optional[str] = None  # 形象描述
    avatar_id: Optional[str] = None  # 形象ID（可选，不提供则自动生成）


class UpdateAnimationRequest(BaseModel):
    role_id: str
    audio: bytes
    text: str


class SwitchStyleRequest(BaseModel):
    role_id: str
    new_style: str  # realistic/cartoon/anime


class UpdateAvatarSettingsRequest(BaseModel):
    avatar_id: str
    settings: Dict  # 形象显示设置（颜色、大小、背景、位置等）


@router.post("/digital-human/create")
async def create_digital_human(request: CreateDigitalHumanRequest):
    """
    创建数字人（调用AI接口生成形象）
    
    注意：此接口会调用通义万相API生成数字人形象图像，需要配置QWEN_API_KEY
    """
    try:
        role_config = {
            "role_id": request.role_id,
            "personality": request.personality or "",
            "profession": request.profession or "",
            "style": request.style,
            "name": request.name,
            "description": request.description
        }
        avatar_data = await digital_human_service.create_digital_human(role_config, request.avatar_id)
        return {"success": True, "data": avatar_data}
    except Exception as e:
        logger.error(f"创建数字人失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/digital-human/animation")
async def update_animation(request: UpdateAnimationRequest):
    """更新数字人动画"""
    try:
        animation = digital_human_service.update_digital_human_animation(
            role_id=request.role_id,
            audio=request.audio,
            text=request.text
        )
        return {"success": True, "data": animation}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/digital-human/style")
async def switch_style(request: SwitchStyleRequest):
    """切换数字人风格"""
    try:
        avatar_data = digital_human_service.switch_avatar_style(
            role_id=request.role_id,
            new_style=request.new_style
        )
        return {"success": True, "data": avatar_data}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/digital-human/{role_id}")
async def get_digital_human(role_id: str, avatar_id: Optional[str] = None):
    """获取数字人信息（用于加载已创建的数字人）"""
    try:
        avatar_data = digital_human_service.get_digital_human(role_id, avatar_id)
        if avatar_data:
            return {"success": True, "data": avatar_data}
        else:
            raise HTTPException(status_code=404, detail=f"数字人不存在: {role_id}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/digital-human/{role_id}/avatars")
async def list_role_avatars(role_id: str):
    """列出角色的所有数字人形象"""
    try:
        avatars = digital_human_service.list_avatars_by_role(role_id)
        return {"success": True, "data": avatars, "count": len(avatars)}
    except Exception as e:
        logger.error(f"列出角色形象失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/digital-human/avatar/{avatar_id}")
async def delete_avatar(avatar_id: str):
    """删除数字人形象"""
    try:
        success = digital_human_service.delete_avatar(avatar_id)
        if success:
            return {"success": True, "message": "形象删除成功"}
        else:
            raise HTTPException(status_code=404, detail=f"形象不存在: {avatar_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除形象失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/digital-human/{role_id}/images")
async def list_digital_human_images(role_id: str, style: Optional[str] = None):
    """列出数字人的所有图像文件"""
    try:
        generator = digital_human_service.generator
        images = generator.list_avatar_images(role_id=role_id, style=style)
        return {"success": True, "data": images, "count": len(images)}
    except Exception as e:
        logger.error(f"列出数字人图像失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/digital-human/image/{filename:path}")
async def get_digital_human_image(filename: str):
    """
    直接获取数字人图像文件（用于解决403问题）
    
    Args:
        filename: 图像文件名，例如: eb1f87f8-bb20-4de4-8cb7-9251a472576a_20260103_043838.png
    """
    from fastapi.responses import FileResponse
    from pathlib import Path
    
    try:
        image_path = DIGITAL_HUMAN_IMAGE_DIR / filename
        
        # 安全检查：确保文件在允许的目录内
        allowed_dir = DIGITAL_HUMAN_IMAGE_DIR
        try:
            image_path.resolve().relative_to(allowed_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="访问被拒绝：文件路径不安全")
        
        if not image_path.exists():
            raise HTTPException(status_code=404, detail=f"图像文件不存在: {filename}")
        
        # 返回文件
        return FileResponse(
            path=str(image_path),
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=31536000",
                "Access-Control-Allow-Origin": "*"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取数字人图像失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/digital-human/images/all")
async def list_all_digital_human_images(style: Optional[str] = None):
    """列出所有数字人图像文件"""
    try:
        generator = digital_human_service.generator
        images = generator.list_avatar_images(role_id=None, style=style)
        return {"success": True, "data": images, "count": len(images)}
    except Exception as e:
        logger.error(f"列出所有数字人图像失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/digital-human/avatar/{avatar_id}/settings")
async def update_avatar_settings(avatar_id: str, request: UpdateAvatarSettingsRequest):
    """更新形象显示设置"""
    try:
        success = digital_human_service.update_avatar_settings(avatar_id, request.settings)
        if success:
            return {"success": True, "message": "设置已保存"}
        else:
            raise HTTPException(status_code=404, detail=f"形象不存在: {avatar_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新形象设置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))





