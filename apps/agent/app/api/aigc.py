"""
AIGC内容生成API路由
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional
import logging
from app.services.aigcservice import aigc_service

logger = logging.getLogger(__name__)
router = APIRouter()


class TextGenerationRequest(BaseModel):
    prompt: str
    style: str = "default"  # default/creative/professional/casual
    length: str = "medium"  # short/medium/long
    role_context: Optional[Dict] = None


class ImageGenerationRequest(BaseModel):
    prompt: str
    style: str = "realistic"  # realistic/anime/cartoon/artistic
    size: str = "1280*1280"  # 通义万相格式：1280*1280/1024*1024/1024*768/768*1024等
    aspect_ratio: str = "1:1"  # 1:1/16:9/9:16/4:3/3:4
    negative_prompt: Optional[str] = ""  # 负面提示词（新API支持）
    prompt_extend: bool = True  # 是否自动扩展提示词（新API支持，默认true）
    watermark: bool = False  # 是否添加水印（新API支持，默认false）
    n: int = 1  # 生成数量（新API支持，默认1）
    seed: Optional[int] = None  # 随机种子（可选）


class VideoGenerationRequest(BaseModel):
    prompt: str
    duration: int = 10
    fps: int = 24
    style: str = "default"


class MultimodalGenerationRequest(BaseModel):
    text: Optional[Dict] = None  # {enabled, prompt, style, length}
    image: Optional[Dict] = None  # {enabled, prompt, style, size, aspect_ratio}
    video: Optional[Dict] = None  # {enabled, prompt, duration, fps, style}
    role_context: Optional[Dict] = None


@router.post("/aigc/text")
async def generate_text(request: TextGenerationRequest):
    """
    生成文字内容（使用通义千问文本生成）
    
    注意：需要配置DASHSCOPE_API_KEY或QWEN_API_KEY
    
    示例：
    {
        "prompt": "写一篇关于春天的散文",
        "style": "creative",
        "length": "medium"
    }
    """
    try:
        result = await aigc_service.text_generator.generate_text(
            prompt=request.prompt,
            style=request.style,
            length=request.length,
            role_context=request.role_context
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"文字生成失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"文字生成失败: {str(e)}")


@router.post("/aigc/image")
async def generate_image(request: ImageGenerationRequest):
    """
    生成图像（调用通义万相API）
    
    注意：此接口会调用通义万相API生成图像，需要配置DASHSCOPE_API_KEY或QWEN_API_KEY
    使用最新的多模态生成API（wan2.6-t2i），支持更多参数
    
    示例：
    {
        "prompt": "一间有着精致窗户的花店，漂亮的木质门，摆放着花朵",
        "style": "realistic",
        "size": "1280*1280",
        "aspect_ratio": "1:1",
        "negative_prompt": "",
        "prompt_extend": true,
        "watermark": false,
        "n": 1
    }
    """
    try:
        # 构建额外参数
        extra_params = {}
        if request.negative_prompt:
            extra_params["negative_prompt"] = request.negative_prompt
        if request.prompt_extend is not None:
            extra_params["prompt_extend"] = request.prompt_extend
        if request.watermark is not None:
            extra_params["watermark"] = request.watermark
        if request.n > 1:
            extra_params["n"] = request.n
        if request.seed is not None:
            extra_params["seed"] = request.seed
        
        result = await aigc_service.image_generator.generate_image(
            prompt=request.prompt,
            style=request.style,
            size=request.size,
            aspect_ratio=request.aspect_ratio,
            **extra_params
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"图像生成失败: {str(e)}")


@router.post("/aigc/video")
async def generate_video(request: VideoGenerationRequest):
    """
    生成视频
    
    示例：
    {
        "prompt": "一个春天的动画场景",
        "duration": 15,
        "fps": 24
    }
    """
    try:
        result = aigc_service.video_generator.generate_video(
            prompt=request.prompt,
            duration=request.duration,
            fps=request.fps,
            style=request.style
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"视频生成失败: {str(e)}")


@router.post("/aigc/multimodal")
async def generate_multimodal(request: MultimodalGenerationRequest):
    """
    生成多模态内容（支持AI图像生成）
    
    注意：图像生成会调用通义万相API，需要配置QWEN_API_KEY
    
    示例：
    {
        "text": {
            "enabled": true,
            "prompt": "写一篇关于春天的文章",
            "style": "creative"
        },
        "image": {
            "enabled": true,
            "prompt": "春天的风景，高清，写实风格",
            "style": "realistic",
            "size": "1024*1024"
        },
        "video": {
            "enabled": false
        }
    }
    """
    try:
        request_dict = {
            "text": request.text or {},
            "image": request.image or {},
            "video": request.video or {}
        }
        
        # 如果启用了图像生成，需要异步处理
        if request_dict.get("image", {}).get("enabled", False):
            image_config = request_dict["image"]
            image_result = await aigc_service.image_generator.generate_image(
                prompt=image_config.get("prompt", ""),
                style=image_config.get("style", "realistic"),
                size=image_config.get("size", "1024*1024"),
                aspect_ratio=image_config.get("aspect_ratio", "1:1")
            )
            request_dict["image"]["result"] = image_result
        
        result = aigc_service.generate_multimodal_content(
            request=request_dict,
            role_context=request.role_context
        )
        
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"多模态生成失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"多模态生成失败: {str(e)}")


@router.post("/aigc/presentation")
async def create_presentation(
    text_content: str,
    images: List[Dict],
    narration: bool = True
):
    """
    创建演示内容（数字人展示）
    
    示例：
    {
        "text_content": "这是演示的文字内容...",
        "images": [
            {"image_url": "image1.png"},
            {"image_url": "image2.png"}
        ],
        "narration": true
    }
    """
    try:
        result = aigc_service.create_presentation(
            text_content=text_content,
            images=images,
            narration=narration
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建演示失败: {str(e)}")





