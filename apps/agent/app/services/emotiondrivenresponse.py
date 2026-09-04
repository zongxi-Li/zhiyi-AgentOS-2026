"""
情感驱动的回复生成服务
根据用户情感动态调整回复内容和风格
"""
import logging
from typing import Dict, Optional, List
from app.services.emotionawareservice import EmotionAwareResponseGenerator
from app.services.voiceemotionrecognition import voice_emotion_recognizer

logger = logging.getLogger(__name__)


class EmotionDrivenResponseService:
    """情感驱动的回复生成服务"""
    
    def __init__(self):
        self.response_generator = EmotionAwareResponseGenerator()
    
    async def generate_response(
        self,
        question: str,
        role_config: Dict,
        text: Optional[str] = None,
        audio_data: Optional[bytes] = None,
        facial_features: Optional[Dict] = None
    ) -> Dict:
        """
        生成情感驱动的回复
        
        Args:
            question: 用户问题
            role_config: 角色配置
            text: 用户文本（可选）
            audio_data: 音频数据（可选）
            facial_features: 面部特征（可选）
        
        Returns:
            包含回复文本、动画、情感信息的完整响应
        """
        # 1. 识别用户情感
        user_emotion = await self._detect_user_emotion(
            text=text,
            audio_data=audio_data,
            facial_features=facial_features
        )
        
        # 2. 根据情感生成回复
        response = self.response_generator.generate_emotion_aware_response(
            question=question,
            user_emotion=user_emotion,
            base_role=role_config,
            text=text,
            audio_features=self._extract_audio_features(audio_data) if audio_data else None,
            facial_features=facial_features
        )
        
        # 3. 增强回复内容（根据情感强度）
        enhanced_response = self._enhance_response_by_emotion(
            response,
            user_emotion
        )
        
        return enhanced_response
    
    async def _detect_user_emotion(
        self,
        text: Optional[str] = None,
        audio_data: Optional[bytes] = None,
        facial_features: Optional[Dict] = None
    ) -> Dict:
        """检测用户情感"""
        emotions = []
        
        # 文本情感
        if text:
            text_emotion = self.response_generator.emotion_analyzer.analyze_text(text)
            text_emotion["modality"] = "text"
            emotions.append(text_emotion)
        
        # 语音情感
        if audio_data:
            voice_emotion_result = voice_emotion_recognizer.recognize_emotion(audio_data)
            voice_emotion = {
                "emotion": voice_emotion_result.get("emotion", "neutral"),
                "intensity": voice_emotion_result.get("intensity", 0.5),
                "confidence": voice_emotion_result.get("confidence", 0.7),
                "modality": "voice",
                "features": voice_emotion_result.get("features", {})
            }
            emotions.append(voice_emotion)
        
        # 面部情感
        if facial_features:
            face_emotion = self.response_generator.emotion_analyzer.analyze_face(facial_features)
            face_emotion["modality"] = "face"
            emotions.append(face_emotion)
        
        # 融合多模态情感
        if emotions:
            fused_emotion = self.response_generator.emotion_analyzer.fuse_emotions(emotions)
        else:
            fused_emotion = {"emotion": "neutral", "intensity": 0.5, "confidence": 0.5}
        
        return fused_emotion
    
    def _extract_audio_features(self, audio_data: bytes) -> Dict:
        """从音频数据提取特征"""
        try:
            result = voice_emotion_recognizer.recognize_emotion(audio_data)
            return result.get("features", {})
        except Exception as e:
            logger.error(f"提取音频特征失败: {e}")
            return {}
    
    def _enhance_response_by_emotion(self, response: Dict, user_emotion: Dict) -> Dict:
        """根据情感增强回复"""
        emotion_type = user_emotion.get("emotion", "neutral")
        intensity = user_emotion.get("intensity", 0.5)
        text = response.get("text", "")
        
        # 根据情感类型添加情感适配的内容
        enhancements = {
            "anxious": {
                "high": "请放心，我会仔细为您解答。",
                "medium": "不用担心，我来帮您。",
                "low": "让我来帮您解决这个问题。"
            },
            "sad": {
                "high": "我理解您的心情，希望我的回答能给您一些帮助。",
                "medium": "我理解您的感受，让我来帮助您。",
                "low": "希望我的回答对您有帮助。"
            },
            "angry": {
                "high": "我理解您的不满，让我们冷静地解决这个问题。",
                "medium": "我理解您的不满，让我来帮您解决。",
                "low": "让我来帮您解决这个问题。"
            },
            "excited": {
                "high": "很高兴看到您这么兴奋！",
                "medium": "很高兴为您解答！",
                "low": "让我来为您解答。"
            }
        }
        
        # 根据强度选择增强内容
        if emotion_type in enhancements:
            if intensity > 0.7:
                enhancement_key = "high"
            elif intensity > 0.4:
                enhancement_key = "medium"
            else:
                enhancement_key = "low"
            
            enhancement_text = enhancements[emotion_type].get(enhancement_key, "")
            if enhancement_text and not text.startswith(enhancement_text):
                # 在回复开头添加情感适配内容
                response["text"] = enhancement_text + " " + text
        
        return response


# 全局情感驱动回复服务实例
emotion_driven_response_service = EmotionDrivenResponseService()





