"""
语音对话API（统一语音相关接口）
"""
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import logging
import io
from app.services.aiservice import AIService

logger = logging.getLogger(__name__)
router = APIRouter()

# 依赖注入AI服务
ai_service = AIService()


class TtsRequest(BaseModel):
    """语音合成请求"""
    text: str
    voice: str = "default"
    speed: float = 1.0
    pitch: float = 1.0


@router.post("/voice/chat")
async def voice_chat(
    audio: UploadFile = File(...),
    roleId: Optional[str] = Form(None),
    contextId: Optional[str] = Form(None)
):
    """
    语音对话（语音识别 + 文本生成回复）
    
    Args:
        audio: 音频文件
        roleId: 角色ID
        contextId: 上下文ID
    
    Returns:
        文本回复、识别文本、置信度
    """
    try:
        # 读取音频数据
        audio_data = await audio.read()
        
        # 语音识别
        recognition_result = await ai_service.recognize_speech(audio_data)
        recognized_text = recognition_result.get("text", "")
        confidence = recognition_result.get("confidence", 0.0)
        
        if not recognized_text:
            raise HTTPException(status_code=400, detail="语音识别失败")
        
        logger.info(f"语音识别结果: {recognized_text} (置信度: {confidence})")
        
        # 根据识别的文本生成回复
        chat_response = await ai_service.generate_text(
            text=recognized_text,
            role_id=roleId or "default"
        )
        
        response_text = chat_response.get("text", "")
        
        return {
            "text": response_text,
            "recognizedText": recognized_text,
            "confidence": confidence,
            "contextId": contextId or ""
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"语音对话处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/voice/tts")
async def text_to_speech(request: TtsRequest):
    """
    文本转语音（TTS）
    
    Args:
        request: 语音合成请求
    
    Returns:
        音频流（WAV格式）
    """
    try:
        # 调用语音合成服务
        audio_data = await ai_service.synthesize_speech(
            text=request.text,
            voice=request.voice,
            speed=request.speed,
            pitch=request.pitch
        )
        
        if not audio_data:
            raise HTTPException(status_code=500, detail="语音合成失败")
        
        # 返回音频流
        return StreamingResponse(
            io.BytesIO(audio_data),
            media_type="audio/wav",
            headers={
                "Content-Disposition": f'attachment; filename="tts_audio.wav"',
                "Cache-Control": "no-cache"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"语音合成失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/voice/recognize")
async def voice_recognize(audio: UploadFile = File(...)):
    """
    语音识别（ASR）
    
    Args:
        audio: 音频文件
    
    Returns:
        识别的文本和置信度
    """
    try:
        audio_data = await audio.read()
        result = await ai_service.recognize_speech(audio_data)
        
        return {
            "text": result.get("text", ""),
            "confidence": result.get("confidence", 0.0)
        }
    except Exception as e:
        logger.error(f"语音识别失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

