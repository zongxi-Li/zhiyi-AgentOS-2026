"""
AIGC内容生成服务
支持文字、图像、视频等多模态内容生成
"""
import logging
import base64
import json
from typing import Dict, List, Optional, Any
from pathlib import Path
import hashlib
from datetime import datetime

logger = logging.getLogger(__name__)


class TextAIGCGenerator:
    """文字AIGC生成器"""
    
    def __init__(self):
        self.generation_cache = {}  # 生成结果缓存
    
    async def generate_text(
        self,
        prompt: str,
        style: str = "default",
        length: str = "medium",
        role_context: Optional[Dict] = None
    ) -> Dict:
        """
        生成文字内容
        
        Args:
            prompt: 生成提示
            style: 风格（default/creative/professional/casual）
            length: 长度（short/medium/long）
            role_context: 角色上下文（可选）
        
        Returns:
            生成结果
        """
        # 检查缓存
        cache_key = hashlib.md5(f"{prompt}_{style}_{length}".encode()).hexdigest()
        if cache_key in self.generation_cache:
            logger.info("使用缓存的文字生成结果")
            return self.generation_cache[cache_key]
        
        # 构建生成提示
        full_prompt = self._build_prompt(prompt, style, length, role_context)
        
        # 生成文字（使用通义千问文本生成）
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                generated_text = asyncio.create_task(self._generate_with_style(full_prompt, style, length))
                generated_text = loop.run_until_complete(generated_text)
            else:
                generated_text = loop.run_until_complete(self._generate_with_style(full_prompt, style, length))
        except RuntimeError:
            generated_text = asyncio.run(self._generate_with_style(full_prompt, style, length))
        
        result = {
            "text": generated_text,
            "style": style,
            "length": length,
            "word_count": len(generated_text),
            "timestamp": datetime.now().isoformat()
        }
        
        # 缓存结果
        self.generation_cache[cache_key] = result
        
        return result
    
    def _build_prompt(self, prompt: str, style: str, length: str, role_context: Optional[Dict]) -> str:
        """构建完整提示"""
        style_instructions = {
            "creative": "请用富有创意和想象力的方式",
            "professional": "请用专业、严谨的方式",
            "casual": "请用轻松、随意的方式",
            "default": "请用自然、流畅的方式"
        }
        
        length_instructions = {
            "short": "约100-200字",
            "medium": "约300-500字",
            "long": "约800-1000字"
        }
        
        instruction = f"{style_instructions.get(style, '')}，{length_instructions.get(length, '')}，生成以下内容：{prompt}"
        
        if role_context:
            role_personality = role_context.get("personality", "")
            if role_personality:
                instruction += f"\n角色特点：{role_personality}"
        
        return instruction
    
    async def _generate_with_style(self, prompt: str, style: str, length: str) -> str:
        """根据风格生成文字（使用通义千问文本生成）"""
        try:
            # 使用通义千问文本生成
            from app.ai_engine.kylin_sdk.client import KylinAIClient
            
            ai_client = KylinAIClient()
            result = await ai_client.generate_text(
                prompt=prompt,
                temperature=0.7 if style == "creative" else 0.5,
                max_tokens=2000 if length == "long" else (1000 if length == "medium" else 500)
            )
            
            generated_text = result.get("text", "")
            if generated_text and not generated_text.startswith("这是对"):
                logger.info(f"AIGC文字生成成功: {len(generated_text)} 字符")
                return generated_text
            else:
                # 如果返回模拟响应，使用降级方案
                logger.warning("通义千问返回模拟响应，使用简化生成")
                return self._fallback_text_generation(prompt, style, length)
                
        except Exception as e:
            logger.warning(f"使用通义千问生成文字失败: {e}，使用降级方案")
            return self._fallback_text_generation(prompt, style, length)
    
    def _fallback_text_generation(self, prompt: str, style: str, length: str) -> str:
        """降级文字生成（简化实现）"""
        logger.warning("使用简化的文字生成（降级方案）")
        
        base_text = f"根据提示'{prompt}'生成的内容。"
        
        if style == "creative":
            base_text = f"【创意风格】{base_text} 这里是一段富有创意和想象力的文字内容..."
        elif style == "professional":
            base_text = f"【专业风格】{base_text} 这里是一段专业、严谨的文字内容..."
        elif style == "casual":
            base_text = f"【轻松风格】{base_text} 这里是一段轻松、随意的文字内容..."
        
        # 根据长度调整
        if length == "long":
            base_text = base_text * 3
        elif length == "short":
            base_text = base_text[:100]
        
        return base_text


class ImageAIGCGenerator:
    """图像AIGC生成器（支持通义万相API）"""
    
    def __init__(self):
        self.generation_cache = {}
        self._ai_client = None  # AI客户端（延迟初始化）
    
    async def generate_image(
        self,
        prompt: str,
        style: str = "realistic",
        size: str = "1024*1024",
        aspect_ratio: str = "1:1"
    ) -> Dict:
        """
        生成图像（调用通义万相API）
        
        Args:
            prompt: 图像描述提示词
            style: 风格（realistic/anime/cartoon/artistic）
            size: 尺寸（1024*1024/1024*768/768*1024等）
            aspect_ratio: 宽高比（1:1/16:9/9:16等，用于计算size）
        
        Returns:
            生成结果（包含图像URL或base64数据）
        """
        # 根据aspect_ratio调整size
        if aspect_ratio != "1:1" and size == "1024*1024":
            if aspect_ratio == "16:9":
                size = "1024*576"
            elif aspect_ratio == "9:16":
                size = "576*1024"
            elif aspect_ratio == "4:3":
                size = "1024*768"
            elif aspect_ratio == "3:4":
                size = "768*1024"
        
        # 检查缓存
        cache_key = hashlib.md5(f"{prompt}_{style}_{size}".encode()).hexdigest()
        if cache_key in self.generation_cache:
            logger.info("使用缓存的图像生成结果")
            return self.generation_cache[cache_key]
        
        # 调用AI接口生成图像
        try:
            # 使用独立的图像生成服务
            from app.services.imagegenerationservice import image_generation_service
            
            result = await image_generation_service.generate_image(
                prompt=prompt,
                style=style,
                size=size
            )
            
            # 检查是否成功
            if result.get("success"):
                # 添加额外字段
                result["aspect_ratio"] = aspect_ratio
                result["timestamp"] = datetime.now().isoformat()
                # 缓存结果
                self.generation_cache[cache_key] = result
                logger.info(f"AI图像生成成功: prompt={prompt[:50]}...")
                return result
            else:
                # 如果生成失败，返回模拟结果
                logger.warning(f"图像生成失败: {result.get('error', '未知错误')}，返回模拟结果")
            result = {
                "image_url": f"generated_image_{cache_key}.png",
                "prompt": prompt,
                "style": style,
                "size": size,
                "aspect_ratio": aspect_ratio,
                "timestamp": datetime.now().isoformat(),
                "note": "这是模拟结果，请配置QWEN_API_KEY以使用真实AI图像生成"
            }
            self.generation_cache[cache_key] = result
            return result
            
        except Exception as e:
            logger.error(f"图像生成失败: {e}", exc_info=True)
            # 返回错误结果
            return {
                "image_url": "",
                "prompt": prompt,
                "style": style,
                "size": size,
                "aspect_ratio": aspect_ratio,
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
                "note": "图像生成失败，请检查API配置"
            }
    
    async def _get_ai_client(self):
        """获取AI客户端（延迟初始化，用于文本生成等其他功能）"""
        if self._ai_client is None:
            try:
                from app.ai_engine.kylin_sdk.client import KylinAIClient
                self._ai_client = KylinAIClient()
            except Exception as e:
                logger.error(f"初始化AI客户端失败: {e}", exc_info=True)
                return None
        return self._ai_client


class VideoAIGCGenerator:
    """视频AIGC生成器"""
    
    def __init__(self):
        self.generation_cache = {}
    
    def generate_video(
        self,
        prompt: str,
        duration: int = 10,
        fps: int = 24,
        style: str = "default"
    ) -> Dict:
        """
        生成视频
        
        Args:
            prompt: 视频描述
            duration: 时长（秒）
            fps: 帧率
            style: 风格
        
        Returns:
            生成结果
        """
        # 检查缓存
        cache_key = hashlib.md5(f"{prompt}_{duration}_{fps}_{style}".encode()).hexdigest()
        if cache_key in self.generation_cache:
            logger.info("使用缓存的视频生成结果")
            return self.generation_cache[cache_key]
        
        # 生成视频（简化实现：实际应该调用视频生成模型）
        logger.warning("使用简化的视频生成，建议集成专业视频生成模型（如Runway、Pika等）")
        
        result = {
            "video_url": f"generated_video_{cache_key}.mp4",
            "prompt": prompt,
            "duration": duration,
            "fps": fps,
            "style": style,
            "timestamp": datetime.now().isoformat(),
            "note": "这是模拟结果，实际应该调用视频生成API"
        }
        
        # 缓存结果
        self.generation_cache[cache_key] = result
        
        return result


class MultimodalAIGCService:
    """多模态AIGC协同服务"""
    
    def __init__(self):
        self.text_generator = TextAIGCGenerator()
        self.image_generator = ImageAIGCGenerator()
        self.video_generator = VideoAIGCGenerator()
    
    def generate_multimodal_content(
        self,
        request: Dict,
        role_context: Optional[Dict] = None
    ) -> Dict:
        """
        生成多模态内容
        
        Args:
            request: 生成请求
                {
                    "text": {"enabled": true, "prompt": "...", "style": "..."},
                    "image": {"enabled": true, "prompt": "...", "style": "..."},
                    "video": {"enabled": true, "prompt": "...", "duration": 10}
                }
            role_context: 角色上下文
        
        Returns:
            生成的多模态内容
        """
        results = {
            "text": None,
            "image": None,
            "video": None,
            "timestamp": datetime.now().isoformat()
        }
        
        # 生成文字
        if request.get("text", {}).get("enabled", False):
            text_config = request["text"]
            results["text"] = self.text_generator.generate_text(
                prompt=text_config.get("prompt", ""),
                style=text_config.get("style", "default"),
                length=text_config.get("length", "medium"),
                role_context=role_context
            )
        
        # 生成图像
        if request.get("image", {}).get("enabled", False):
            image_config = request["image"]
            results["image"] = self.image_generator.generate_image(
                prompt=image_config.get("prompt", ""),
                style=image_config.get("style", "realistic"),
                size=image_config.get("size", "512x512"),
                aspect_ratio=image_config.get("aspect_ratio", "1:1")
            )
        
        # 生成视频
        if request.get("video", {}).get("enabled", False):
            video_config = request["video"]
            results["video"] = self.video_generator.generate_video(
                prompt=video_config.get("prompt", ""),
                duration=video_config.get("duration", 10),
                fps=video_config.get("fps", 24),
                style=video_config.get("style", "default")
            )
        
        return results
    
    def create_presentation(
        self,
        text_content: str,
        images: List[Dict],
        narration: bool = True
    ) -> Dict:
        """
        创建演示内容（数字人展示）
        
        Args:
            text_content: 文字内容
            images: 图像列表
            narration: 是否朗读
        
        Returns:
            演示配置
        """
        presentation = {
            "text": text_content,
            "images": images,
            "narration": narration,
            "slides": []
        }
        
        # 创建幻灯片
        for i, image in enumerate(images):
            slide = {
                "slide_number": i + 1,
                "image": image,
                "text": text_content[i * 100:(i + 1) * 100] if len(text_content) > (i + 1) * 100 else text_content[i * 100:],
                "duration": 5.0  # 每张幻灯片5秒
            }
            presentation["slides"].append(slide)
        
        return presentation


# 全局AIGC服务实例
aigc_service = MultimodalAIGCService()





