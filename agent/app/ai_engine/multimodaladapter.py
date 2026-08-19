"""
多模态服务适配器
支持通义千问多模态能力（图像理解、OCR、视觉问答等）
使用qwen-vl模型
"""
import logging
import base64
import httpx
from typing import Dict, Optional, List
from app.config import settings

logger = logging.getLogger(__name__)


class MultimodalAdapter:
    """多模态服务适配器（使用通义千问qwen-vl模型）"""
    
    def __init__(self, api_key: str):
        """
        初始化多模态适配器
        
        Args:
            api_key: DashScope API密钥（与通义千问共用）
        """
        self.api_key = api_key
        self.model = "qwen-vl-max"  # 通义千问多模态模型
        self.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self.client = httpx.AsyncClient(timeout=60.0)
        logger.info("多模态服务适配器初始化成功")
    
    async def process_image(
        self,
        image_data: bytes,
        task: str = "auto",
        question: Optional[str] = None
    ) -> Dict:
        """
        处理图像（OCR、图像描述、视觉问答）
        
        Args:
            image_data: 图像数据（字节流）
            task: 任务类型（ocr/caption/qa/auto）
            question: 问题（用于视觉问答）
        
        Returns:
            处理结果
        """
        try:
            # 将图像编码为base64
            image_base64 = base64.b64encode(image_data).decode('utf-8')
            image_url = f"data:image/jpeg;base64,{image_base64}"
            
            # 根据任务类型构建提示词
            if task == "ocr":
                prompt = "请识别并提取这张图片中的所有文字内容，包括中文、英文、数字等。"
            elif task == "caption":
                prompt = "请详细描述这张图片的内容，包括主要对象、场景、颜色、动作等。"
            elif task == "qa" and question:
                prompt = f"请回答关于这张图片的问题：{question}"
            else:
                # auto模式：自动判断任务类型
                prompt = "请分析这张图片，如果包含文字请提取文字，否则请描述图片内容。"
            
            # 构建消息（多模态格式）
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
            
            # 调用通义千问多模态API
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 2000
                }
            )
            
            response.raise_for_status()
            result = response.json()
            
            # 解析响应
            if result.get("choices") and len(result["choices"]) > 0:
                content = result["choices"][0].get("message", {}).get("content", "")
                
                logger.info(f"图像处理成功: task={task}, 结果长度={len(content)}")
                
                return {
                    "type": task,
                    "content": content,
                    "method": "qwen-vl",
                    "success": True,
                    "model": self.model
                }
            else:
                error_msg = result.get("message", "API返回格式错误")
                raise ValueError(f"多模态API错误: {error_msg}")
                
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_response = e.response.json()
                error_detail = error_response.get("message", str(e))
            except:
                error_detail = str(e)
            
            logger.error(f"多模态API HTTP错误: {error_detail}")
            raise Exception(f"多模态API调用失败: {error_detail}")
        except Exception as e:
            logger.error(f"多模态API调用异常: {e}", exc_info=True)
            raise
    
    async def extract_text_from_image(self, image_data: bytes) -> Dict:
        """
        从图像中提取文字（OCR）
        
        Args:
            image_data: 图像数据
        
        Returns:
            OCR结果
        """
        return await self.process_image(image_data, task="ocr")
    
    async def generate_image_caption(self, image_data: bytes) -> Dict:
        """
        生成图像描述
        
        Args:
            image_data: 图像数据
        
        Returns:
            图像描述
        """
        return await self.process_image(image_data, task="caption")
    
    async def answer_question_about_image(
        self,
        image_data: bytes,
        question: str
    ) -> Dict:
        """
        回答关于图像的问题（视觉问答）
        
        Args:
            image_data: 图像数据
            question: 问题
        
        Returns:
            答案
        """
        return await self.process_image(image_data, task="qa", question=question)
    
    async def close(self):
        """关闭客户端"""
        await self.client.aclose()


# 全局多模态适配器实例（延迟初始化）
_multimodal_adapter = None


async def get_multimodal_adapter() -> Optional[MultimodalAdapter]:
    """获取多模态适配器（延迟初始化）"""
    global _multimodal_adapter
    if _multimodal_adapter is None:
        try:
            api_key = getattr(settings, 'DASHSCOPE_API_KEY', '') or getattr(settings, 'QWEN_API_KEY', '')
            if api_key:
                _multimodal_adapter = MultimodalAdapter(api_key)
            else:
                logger.warning("未配置API密钥，多模态功能将使用简化实现")
                return None
        except Exception as e:
            logger.error(f"初始化多模态适配器失败: {e}", exc_info=True)
            return None
    return _multimodal_adapter

