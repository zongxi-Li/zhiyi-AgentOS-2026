"""
语音合成API
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from app.services.aiservice import AIService

router = APIRouter()

# 依赖注入AI服务
ai_service = AIService()

class TtsRequest(BaseModel):
    """语音合成请求"""
    text: str
    voice: str = "default"
    speed: float = 1.0
    pitch: float = 1.0

@router.post("/tts")
async def text_to_speech(request: TtsRequest):
    """
    文本转语音
    
    Args:
        request: 语音合成请求，包含文本、语音类型、语速、音调
    
    Returns:
        音频流（WAV格式）
    """
    from fastapi.responses import StreamingResponse
    import io
    
    audio_data = await ai_service.synthesize_speech(
        text=request.text,
        voice=request.voice,
        speed=request.speed,
        pitch=request.pitch
    )
    
    # 返回音频流而不是JSON
    return StreamingResponse(
        io.BytesIO(audio_data),
        media_type="audio/wav",
        headers={
            "Content-Disposition": f'attachment; filename="tts_audio.wav"',
            "Cache-Control": "no-cache"
        }
    )
