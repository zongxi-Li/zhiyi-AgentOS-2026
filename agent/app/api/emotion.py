"""
情感感知API路由
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Optional
from app.services.emotionawareservice import emotion_aware_service

router = APIRouter()


class EmotionAnalyzeRequest(BaseModel):
    text: Optional[str] = None
    audio_features: Optional[Dict] = None
    facial_features: Optional[Dict] = None


class EmotionAwareResponseRequest(BaseModel):
    question: str
    base_role: Dict
    text: Optional[str] = None
    audio_features: Optional[Dict] = None
    facial_features: Optional[Dict] = None
    user_emotion: Optional[Dict] = None


@router.post("/emotion/analyze")
async def analyze_emotion(request: EmotionAnalyzeRequest):
    """多模态情感分析"""
    try:
        from app.services.emotionawareservice import MultiModalEmotionAnalyzer
        
        analyzer = MultiModalEmotionAnalyzer()
        emotions = []
        
        if request.text:
            text_emotion = analyzer.analyze_text(request.text)
            text_emotion["modality"] = "text"
            emotions.append(text_emotion)
        
        if request.audio_features:
            voice_emotion = analyzer.analyze_voice(request.audio_features)
            voice_emotion["modality"] = "voice"
            emotions.append(voice_emotion)
        
        if request.facial_features:
            face_emotion = analyzer.analyze_face(request.facial_features)
            face_emotion["modality"] = "face"
            emotions.append(face_emotion)
        
        if emotions:
            fused_emotion = analyzer.fuse_emotions(emotions)
            return {"success": True, "data": fused_emotion}
        else:
            return {"success": True, "data": {"emotion": "neutral", "intensity": 0.5}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/emotion/response")
async def generate_emotion_aware_response(request: EmotionAwareResponseRequest):
    """生成情感感知回复"""
    try:
        response = emotion_aware_service.generate_emotion_aware_response(
            question=request.question,
            user_emotion=request.user_emotion,
            base_role=request.base_role,
            text=request.text,
            audio_features=request.audio_features,
            facial_features=request.facial_features
        )
        return {"success": True, "data": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))





