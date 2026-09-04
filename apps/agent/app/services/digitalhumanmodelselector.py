"""
数字人模型选择服务
为数字人生成选择最优模型
"""
import logging
from typing import Dict, Optional, List
from app.services.modelselector import ModelSelector, ModelType
from app.services.digitalhumanservice import DigitalHumanGenerator

logger = logging.getLogger(__name__)


class DigitalHumanModelSelector:
    """数字人模型选择器"""
    
    def __init__(self):
        self.model_selector = ModelSelector()
        self.digital_human_generator = DigitalHumanGenerator()
        
        # 数字人专用模型配置
        self.digital_human_models = {
            "avatar_generation": {
                "fast": "avatar_fast_v1",
                "balanced": "avatar_balanced_v1",
                "quality": "avatar_quality_v1"
            },
            "animation": {
                "fast": "animation_fast_v1",
                "balanced": "animation_balanced_v1",
                "quality": "animation_quality_v1"
            },
            "emotion": {
                "fast": "emotion_fast_v1",
                "balanced": "emotion_balanced_v1",
                "quality": "emotion_quality_v1"
            }
        }
    
    def select_avatar_model(
        self,
        role_config: Dict,
        priority: str = "balanced",
        available_resources: float = 1.0
    ) -> str:
        """
        为数字人形象生成选择模型
        
        Args:
            role_config: 角色配置
            priority: 优先级（speed/quality/balance）
            available_resources: 可用资源（0-1）
        
        Returns:
            选中的模型名称
        """
        # 根据优先级和资源选择模型
        if priority == "speed" or available_resources < 0.3:
            model_name = self.digital_human_models["avatar_generation"]["fast"]
        elif priority == "quality" and available_resources > 0.7:
            model_name = self.digital_human_models["avatar_generation"]["quality"]
        else:
            model_name = self.digital_human_models["avatar_generation"]["balanced"]
        
        logger.info(f"为角色 {role_config.get('role_id')} 选择数字人模型: {model_name}")
        
        return model_name
    
    def select_animation_model(
        self,
        animation_type: str,
        priority: str = "balanced"
    ) -> str:
        """
        为动画生成选择模型
        
        Args:
            animation_type: 动画类型（lip_sync/gesture/expression）
            priority: 优先级
        
        Returns:
            选中的模型名称
        """
        if priority == "speed":
            model_name = self.digital_human_models["animation"]["fast"]
        elif priority == "quality":
            model_name = self.digital_human_models["animation"]["quality"]
        else:
            model_name = self.digital_human_models["animation"]["balanced"]
        
        return model_name
    
    def select_emotion_model(
        self,
        emotion_task: str,
        priority: str = "balanced"
    ) -> str:
        """
        为情感识别选择模型
        
        Args:
            emotion_task: 情感任务（recognition/expression）
            priority: 优先级
        
        Returns:
            选中的模型名称
        """
        if priority == "speed":
            model_name = self.digital_human_models["emotion"]["fast"]
        elif priority == "quality":
            model_name = self.digital_human_models["emotion"]["quality"]
        else:
            model_name = self.digital_human_models["emotion"]["balanced"]
        
        return model_name
    
    def generate_with_selected_model(
        self,
        role_config: Dict,
        task: str = "avatar",
        priority: str = "balanced"
    ) -> Dict:
        """
        使用选中的模型生成数字人内容
        
        Args:
            role_config: 角色配置
            task: 任务类型（avatar/animation/emotion）
            priority: 优先级
        
        Returns:
            生成结果和使用的模型信息
        """
        # 选择模型
        if task == "avatar":
            model_name = self.select_avatar_model(role_config, priority)
            result = self.digital_human_generator.generate_avatar(role_config)
        elif task == "animation":
            model_name = self.select_animation_model("gesture", priority)
            result = {"animation": "generated"}
        elif task == "emotion":
            model_name = self.select_emotion_model("recognition", priority)
            result = {"emotion": "detected"}
        else:
            model_name = "default"
            result = {}
        
        return {
            "result": result,
            "model_used": model_name,
            "task": task,
            "priority": priority
        }


# 全局数字人模型选择器实例
digital_human_model_selector = DigitalHumanModelSelector()





