"""
情感驱动回复API路由
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Dict, Optional
from app.services.emotiondrivenresponse import emotion_driven_response_service

router = APIRouter()


class EmotionDrivenRequest(BaseModel):
    question: str
    role_id: str
    text: Optional[str] = None
    facial_features: Optional[Dict] = None


@router.post("/emotion-driven/response")
async def generate_emotion_driven_response(
    request: EmotionDrivenRequest,
    audio: Optional[UploadFile] = File(None)
):
    """
    生成情感驱动的回复
    
    支持文本、语音、面部特征多模态输入
    """
    try:
        # 读取音频数据（如果有）
        audio_data = None
        if audio:
            audio_data = await audio.read()
        
        # 获取角色配置（简化实现）
        role_config = {
            "role_id": request.role_id,
            "personality": {},
            "profession": ""
        }
        
        # 生成情感驱动回复
        response = await emotion_driven_response_service.generate_response(
            question=request.question,
            role_config=role_config,
            text=request.text,
            audio_data=audio_data,
            facial_features=request.facial_features
        )
        
        return {
            "success": True,
            "data": response
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成情感驱动回复失败: {str(e)}")


@router.post("/emotion-driven/voice-emotion")
async def recognize_voice_emotion(
    audio: UploadFile = File(...)
):
    """识别语音情感"""
    try:
        from app.services.voiceemotionrecognition import voice_emotion_recognizer
        
        audio_data = await audio.read()
        result = voice_emotion_recognizer.recognize_emotion(audio_data)
        
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"语音情感识别失败: {str(e)}")





