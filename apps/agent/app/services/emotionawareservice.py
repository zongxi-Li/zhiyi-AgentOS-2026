"""
情感感知数字人对话服务
实现多模态情感识别和情感驱动的对话生成
"""
import logging
import re
from typing import Dict, Optional, List, Any
import numpy as np

logger = logging.getLogger(__name__)


class MultiModalEmotionAnalyzer:
    """多模态情感分析器"""
    
    def __init__(self):
        # 情感关键词库
        self.emotion_keywords = {
            "happy": ["高兴", "开心", "快乐", "兴奋", "愉快", "满意"],
            "sad": ["难过", "悲伤", "沮丧", "失望", "痛苦", "失落"],
            "angry": ["生气", "愤怒", "恼火", "烦躁", "不满", "气愤"],
            "anxious": ["焦虑", "担心", "紧张", "不安", "忧虑", "害怕"],
            "confused": ["困惑", "迷茫", "不解", "疑惑", "不明白"],
            "excited": ["激动", "兴奋", "期待", "期待", "期待"],
            "neutral": []
        }
        
    def analyze_text(self, text: str) -> Dict:
        """
        分析文本情感（增强实现）
        
        Args:
            text: 文本内容
        
        Returns:
            情感分析结果
        """
        if not text:
            return {"emotion": "neutral", "intensity": 0.5, "confidence": 0.5}
        
        text_lower = text.lower()
        emotion_scores = {}
        
        # 计算各情感得分
        for emotion, keywords in self.emotion_keywords.items():
            if emotion == "neutral":
                continue
            
            score = 0
            keyword_matches = 0
            
            for keyword in keywords:
                count = text_lower.count(keyword)
                if count > 0:
                    keyword_matches += 1
                    score += count * 0.15  # 提高关键词权重
            
            # 检查情感强度词
            intensity_words = {
                "非常": 1.8,
                "很": 1.5,
                "特别": 1.6,
                "极其": 2.0,
                "超级": 1.7,
                "十分": 1.4,
                "相当": 1.3
            }
            
            intensity_multiplier = 1.0
            for intensity_word, multiplier in intensity_words.items():
                if intensity_word in text:
                    intensity_multiplier = max(intensity_multiplier, multiplier)
            
            score *= intensity_multiplier
            
            # 检查否定词（降低情感强度）
            negation_words = ["不", "没", "非", "无", "别"]
            negation_count = sum(1 for word in negation_words if word in text_lower)
            if negation_count > 0:
                score *= (1.0 - negation_count * 0.2)  # 每个否定词降低20%
            
            # 检查问号（可能表示困惑）
            if "?" in text or "？" in text:
                if emotion == "confused":
                    score += 0.2
            
            # 检查感叹号（可能表示强烈情感）
            if "!" in text or "！" in text:
                score *= 1.3
            
            emotion_scores[emotion] = score
        
        # 选择得分最高的情感
        if emotion_scores and max(emotion_scores.values()) > 0:
            max_emotion = max(emotion_scores, key=emotion_scores.get)
            max_score = emotion_scores[max_emotion]
            
            # 归一化强度（0-1）
            intensity = min(max_score / 3.0, 1.0)  # 调整归一化因子
            confidence = min(max_score / 2.0, 1.0)
            
            # 如果得分太低，认为是中性
            if max_score < 0.1:
                return {"emotion": "neutral", "intensity": 0.5, "confidence": 0.5}
            
            return {
                "emotion": max_emotion,
                "intensity": intensity,
                "confidence": confidence,
                "all_scores": emotion_scores
            }
        else:
            return {"emotion": "neutral", "intensity": 0.5, "confidence": 0.5}
    
    def analyze_voice(self, audio_features: Dict) -> Dict:
        """
        分析语音情感
        
        Args:
            audio_features: 音频特征（pitch、energy、tempo等）
        
        Returns:
            情感分析结果
        """
        pitch = audio_features.get("pitch", 0.5)
        energy = audio_features.get("energy", 0.5)
        tempo = audio_features.get("tempo", 0.5)
        
        # 根据音频特征推断情感
        if pitch > 0.7 and energy > 0.7:
            emotion = "excited"
            intensity = (pitch + energy) / 2
        elif pitch < 0.3 and energy < 0.3:
            emotion = "sad"
            intensity = 1.0 - (pitch + energy) / 2
        elif energy > 0.7 and tempo > 0.7:
            emotion = "angry"
            intensity = (energy + tempo) / 2
        elif pitch > 0.6 and energy < 0.4:
            emotion = "anxious"
            intensity = (pitch + (1 - energy)) / 2
        else:
            emotion = "neutral"
            intensity = 0.5
        
        return {
            "emotion": emotion,
            "intensity": intensity,
            "confidence": 0.7,
            "audio_features": audio_features
        }
    
    def analyze_face(self, facial_features: Dict) -> Dict:
        """
        分析面部表情情感
        
        Args:
            facial_features: 面部特征（表情、动作单元等）
        
        Returns:
            情感分析结果
        """
        # 简化实现：根据表情类型推断情感
        expression = facial_features.get("expression", "neutral")
        
        expression_to_emotion = {
            "smile": "happy",
            "frown": "sad",
            "angry_face": "angry",
            "surprised": "excited",
            "worried": "anxious"
        }
        
        emotion = expression_to_emotion.get(expression, "neutral")
        intensity = facial_features.get("intensity", 0.5)
        
        return {
            "emotion": emotion,
            "intensity": intensity,
            "confidence": 0.8,
            "facial_features": facial_features
        }
    
    def fuse_emotions(self, emotions: List[Dict]) -> Dict:
        """
        融合多模态情感
        
        Args:
            emotions: 多个情感分析结果列表
        
        Returns:
            融合后的情感结果
        """
        if not emotions:
            return {"emotion": "neutral", "intensity": 0.5, "confidence": 0.5}
        
        # 按模态权重融合
        weights = {"text": 0.5, "voice": 0.3, "face": 0.2}
        
        emotion_scores = {}
        total_confidence = 0
        
        for emotion_data in emotions:
            emotion = emotion_data.get("emotion", "neutral")
            intensity = emotion_data.get("intensity", 0.5)
            confidence = emotion_data.get("confidence", 0.5)
            
            # 确定模态权重
            modality = emotion_data.get("modality", "text")
            weight = weights.get(modality, 0.33)
            
            if emotion not in emotion_scores:
                emotion_scores[emotion] = 0
            
            emotion_scores[emotion] += intensity * confidence * weight
            total_confidence += confidence * weight
        
        # 选择得分最高的情感
        if emotion_scores:
            max_emotion = max(emotion_scores, key=emotion_scores.get)
            max_score = emotion_scores[max_emotion]
            
            # 归一化
            intensity = min(max_score / total_confidence if total_confidence > 0 else 0.5, 1.0)
            confidence = min(total_confidence, 1.0)
            
            return {
                "emotion": max_emotion,
                "intensity": intensity,
                "confidence": confidence,
                "all_scores": emotion_scores
            }
        else:
            return {"emotion": "neutral", "intensity": 0.5, "confidence": 0.5}


class EmotionAwareResponseGenerator:
    """情感感知的回复生成器"""
    
    def __init__(self):
        self.emotion_analyzer = MultiModalEmotionAnalyzer()
        
    def generate_emotion_aware_response(
        self,
        question: str,
        user_emotion: Dict,
        base_role: Dict,
        text: Optional[str] = None,
        audio_features: Optional[Dict] = None,
        facial_features: Optional[Dict] = None
    ) -> Dict:
        """
        根据用户情感生成回复
        
        Args:
            question: 用户问题
            user_emotion: 用户情感（如果已分析）
            base_role: 基础角色配置
            text: 用户文本（可选）
            audio_features: 音频特征（可选）
            facial_features: 面部特征（可选）
        
        Returns:
            包含文本回复、数字人动画、情感信息的完整响应
        """
        # 如果没有提供用户情感，进行多模态分析
        if not user_emotion:
            emotions = []
            
            if text:
                text_emotion = self.emotion_analyzer.analyze_text(text)
                text_emotion["modality"] = "text"
                emotions.append(text_emotion)
            
            if audio_features:
                voice_emotion = self.emotion_analyzer.analyze_voice(audio_features)
                voice_emotion["modality"] = "voice"
                emotions.append(voice_emotion)
            
            if facial_features:
                face_emotion = self.emotion_analyzer.analyze_face(facial_features)
                face_emotion["modality"] = "face"
                emotions.append(face_emotion)
            
            if emotions:
                user_emotion = self.emotion_analyzer.fuse_emotions(emotions)
            else:
                user_emotion = {"emotion": "neutral", "intensity": 0.5}
        
        # 根据用户情感调整角色
        adjusted_role = self._adjust_role_for_emotion(base_role, user_emotion)
        
        # 生成情感适配的文本回复
        text_response = self._generate_text_response(question, adjusted_role, user_emotion)
        
        # 确定数字人应该表达的情感
        digital_human_emotion = self._determine_response_emotion(user_emotion, text_response)
        
        # 生成数字人动画配置
        animation_config = self._generate_animation_config(digital_human_emotion, text_response)
        
        return {
            "text": text_response,
            "animation": animation_config,
            "emotion": digital_human_emotion,
            "user_emotion": user_emotion
        }
    
    def _adjust_role_for_emotion(self, role: Dict, emotion: Dict) -> Dict:
        """根据情绪调整角色参数"""
        emotion_type = emotion.get("emotion", "neutral")
        intensity = emotion.get("intensity", 0.5)
        
        adjustments = {
            "anxious": {
                "warmth": +0.3 * intensity,
                "patience": +0.5 * intensity,
                "reassurance": True,
                "tone": "gentle"
            },
            "sad": {
                "warmth": +0.4 * intensity,
                "empathy": +0.5 * intensity,
                "supportive": True,
                "tone": "comforting"
            },
            "angry": {
                "calmness": +0.4 * intensity,
                "professional": +0.3 * intensity,
                "solution_focused": True,
                "tone": "calm"
            },
            "excited": {
                "enthusiasm": +0.3 * intensity,
                "energy": +0.2 * intensity,
                "tone": "enthusiastic"
            },
            "confused": {
                "patience": +0.4 * intensity,
                "clarity": +0.3 * intensity,
                "step_by_step": True,
                "tone": "explanatory"
            }
        }
        
        if emotion_type in adjustments:
            adj = adjustments[emotion_type]
            adjusted_role = role.copy()
            
            # 应用调整
            for key, value in adj.items():
                if isinstance(value, bool):
                    adjusted_role[key] = value
                elif isinstance(value, (int, float)):
                    original_value = adjusted_role.get(key, 0.5)
                    adjusted_role[key] = min(max(original_value + value, 0.0), 1.0)
                else:
                    adjusted_role[key] = value
            
            return adjusted_role
        
        return role
    
    def _generate_text_response(self, question: str, role: Dict, emotion: Dict) -> str:
        """生成文本回复（增强实现）"""
        emotion_type = emotion.get("emotion", "neutral")
        intensity = emotion.get("intensity", 0.5)
        
        # 根据情感和强度生成更丰富的回复前缀
        emotion_prefixes = {
            "anxious": {
                "high": "我完全理解你的担心和焦虑，",
                "medium": "我理解你的担心，",
                "low": "我注意到你有些担心，"
            },
            "sad": {
                "high": "我深深感受到你的难过，",
                "medium": "我感受到你的难过，",
                "low": "我注意到你有些低落，"
            },
            "angry": {
                "high": "我明白你非常不满，",
                "medium": "我明白你的不满，",
                "low": "我注意到你有些不满，"
            },
            "excited": {
                "high": "很高兴看到你这么兴奋和激动，",
                "medium": "很高兴看到你这么兴奋，",
                "low": "我注意到你有些兴奋，"
            },
            "confused": {
                "high": "让我来帮你详细理清思路，",
                "medium": "让我来帮你理清思路，",
                "low": "让我来帮你理解一下，"
            },
            "happy": {
                "high": "看到你这么开心我也很高兴，",
                "medium": "看到你开心我也很高兴，",
                "low": "我注意到你心情不错，"
            }
        }
        
        # 根据强度选择前缀
        intensity_level = "high" if intensity > 0.7 else ("medium" if intensity > 0.4 else "low")
        prefix_dict = emotion_prefixes.get(emotion_type, {})
        prefix = prefix_dict.get(intensity_level, prefix_dict.get("medium", ""))
        
        # 根据角色调整回复风格
        role_personality = role.get("personality", "")
        if "专业" in role_personality or "严谨" in role_personality:
            response = f"{prefix}从专业角度来说，关于你的问题：{question}，我会为你提供详细的解答。"
        elif "耐心" in role_personality or "温和" in role_personality:
            response = f"{prefix}关于你的问题，我会耐心地为你解答。"
        else:
            response = f"{prefix}关于你的问题，我会尽力帮助你。"
        
        return response
    
    def _determine_response_emotion(self, user_emotion: Dict, response_text: str) -> Dict:
        """确定数字人应该表达的情感"""
        user_emotion_type = user_emotion.get("emotion", "neutral")
        
        # 情感映射：用户情感 -> 数字人情感
        emotion_mapping = {
            "anxious": {"emotion": "understanding", "intensity": 0.7},
            "sad": {"emotion": "compassionate", "intensity": 0.8},
            "angry": {"emotion": "calm", "intensity": 0.6},
            "excited": {"emotion": "enthusiastic", "intensity": 0.7},
            "confused": {"emotion": "patient", "intensity": 0.7},
            "neutral": {"emotion": "friendly", "intensity": 0.5}
        }
        
        return emotion_mapping.get(user_emotion_type, {"emotion": "friendly", "intensity": 0.5})
    
    def _generate_animation_config(self, emotion: Dict, text: str) -> Dict:
        """生成数字人动画配置"""
        emotion_type = emotion.get("emotion", "friendly")
        intensity = emotion.get("intensity", 0.5)
        
        animation_map = {
            "understanding": {"expression": "gentle_smile", "gesture": "nodding"},
            "compassionate": {"expression": "warm_smile", "gesture": "open_arms"},
            "calm": {"expression": "neutral", "gesture": "calm_hands"},
            "enthusiastic": {"expression": "bright_smile", "gesture": "energetic"},
            "patient": {"expression": "gentle", "gesture": "explaining"},
            "friendly": {"expression": "smile", "gesture": "welcoming"}
        }
        
        config = animation_map.get(emotion_type, {"expression": "smile", "gesture": "neutral"})
        config["intensity"] = intensity
        config["duration"] = len(text) * 0.1  # 根据文本长度估算时长
        
        return config


# 全局情感感知服务实例
emotion_aware_service = EmotionAwareResponseGenerator()

