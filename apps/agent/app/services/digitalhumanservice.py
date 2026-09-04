"""
智能数字人角色系统服务
实现数字人形象生成、语音驱动、表情动作等功能
"""
import logging
import json
from typing import Dict, Optional, List, Any
from pathlib import Path
import numpy as np
import base64
import os
import uuid
from datetime import datetime

from app.paths import DIGITAL_HUMAN_IMAGE_DIR, DIGITAL_HUMAN_METADATA_DIR

logger = logging.getLogger(__name__)


class DigitalHumanGenerator:
    """数字人形象生成器（AIGC）"""
    
    # 类级别标志，避免重复日志
    _init_logged = False
    
    def __init__(self):
        self.avatar_cache = {}  # 数字人形象缓存
        self._ai_client = None  # AI客户端（延迟初始化）
        self.avatar_image_dir = DIGITAL_HUMAN_IMAGE_DIR
        self.avatar_image_dir.mkdir(parents=True, exist_ok=True)
        
        # 只在第一次初始化时记录日志
        if not DigitalHumanGenerator._init_logged:
            logger.info(f"数字人图像保存目录: {self.avatar_image_dir.absolute()}")
            DigitalHumanGenerator._init_logged = True
        
    async def generate_avatar(self, role_config: Dict, avatar_id: Optional[str] = None) -> Dict:
        """
        为角色生成数字人形象（调用AI接口生成图像）
        
        Args:
            role_config: 角色配置，包含personality、profession、style等
            avatar_id: 形象ID（可选，不提供则自动生成）
        
        Returns:
            数字人形象数据，包含avatar_id、avatar、expressions、animations、image_url等
        """
        role_id = role_config.get("role_id")
        
        # 生成唯一形象ID
        if not avatar_id:
            avatar_id = str(uuid.uuid4())
        
        # 检查缓存
        if role_id in self.avatar_cache:
            logger.info(f"使用缓存的数字人形象: {role_id}")
            return self.avatar_cache[role_id]
        
        # 检查本地文件是否存在（避免重复生成）
        existing_avatar_data = self._load_avatar_data_from_file(role_id)
        if existing_avatar_data:
            # 检查图像文件是否存在（支持带时间戳的文件名）
            style = role_config.get("style", "realistic")
            image_file = None
            for img_file in self.avatar_image_dir.glob(f"{role_id}_*.png"):
                if img_file.exists():
                    image_file = img_file
                    break
            
            if image_file and image_file.exists():
                logger.info(f"✅ 发现已存在的数字人形象: {role_id}，跳过生成")
                # 更新本地图像路径
                existing_avatar_data["local_image_path"] = str(image_file)
                image_filename = image_file.name
                existing_avatar_data["local_image_url"] = f"/ai/digital-human/image/{image_filename}"
                existing_avatar_data["avatar"] = f"/ai/digital-human/image/{image_filename}"
                existing_avatar_data["image_url"] = f"/ai/digital-human/image/{image_filename}"
                # 更新缓存
                self.avatar_cache[role_id] = existing_avatar_data
                return existing_avatar_data
        
        # 提取角色特征
        role_features = {
            "personality": role_config.get("personality", ""),
            "profession": role_config.get("profession", ""),
            "style": role_config.get("style", "realistic")
        }
        
        # 构建专业的数字人形象生成提示词（无论是否生成图像都需要）
        image_prompt = self._build_digital_human_prompt(role_features)
        
        # 检查图像文件是否已存在（避免重复生成图像）
        style = role_features.get("style", "realistic")
        # 查找该角色的图像文件（支持带时间戳的文件名）
        image_file = None
        for img_file in self.avatar_image_dir.glob(f"{role_id}_*.png"):
            if img_file.exists():
                image_file = img_file
                break
        
        if image_file and image_file.exists():
            logger.info(f"✅ 图像文件已存在: {image_file}，跳过AI生成")
            # 使用已存在的图像
            image_filename = image_file.name
            image_result = {
                "image_url": f"/ai/digital-human/image/{image_filename}",
                "image_base64": "",
                "success": True,
                "local_path": str(image_file)  # 添加本地路径，确保后续能正确生成URL
            }
        else:
            # 调用AI接口生成数字人形象图像
            image_result = None
            try:
                image_result = await self._generate_avatar_image(image_prompt, role_features)
                logger.info(f"AI图像生成成功: role_id={role_id}")
            except Exception as e:
                logger.error(f"AI图像生成失败: {e}，将使用默认配置", exc_info=True)
                # 如果AI生成失败，使用默认配置
        
        # AIGC生成基础形象配置
        base_avatar = self._generate_base_avatar(role_features)
        
        # 应用角色风格
        styled_avatar = self._apply_role_style(base_avatar, role_features)
        
        # 生成表情库
        expressions = self._generate_expressions(styled_avatar)
        
        # 生成动画
        animations = self._generate_animations(styled_avatar)
        
        # 生成模型URL（根据风格选择不同的占位符或实际模型路径）
        model_url = self._generate_model_url(role_id, role_features.get("style", "realistic"))
        
        avatar_data = {
            "avatar_id": avatar_id,  # 添加唯一形象ID
            "avatar_config": styled_avatar,  # 改为avatar_config，避免与图像URL字段冲突
            "expressions": expressions,
            "animations": animations,
            "role_id": role_id,
            "modelUrl": model_url,  # 添加模型URL，供前端加载3D模型
            "modelPath": model_url,  # 兼容字段
            "style": role_features.get("style", "realistic"),
            "status": "ready" if image_result else "default",  # 状态：ready/loading/error/default
            "created_at": self._get_timestamp(),
            "image_prompt": image_prompt,  # 保存使用的提示词
            "name": role_config.get("name", f"形象_{datetime.now().strftime('%Y%m%d_%H%M%S')}"),  # 形象名称
            "description": role_config.get("description", ""),  # 形象描述
        }
        
        # 如果AI生成成功或图像已存在，添加图像信息并保存到本地
        if image_result:
            image_url = image_result.get("image_url", "")
            image_base64 = image_result.get("image_base64", "")
            
            # 如果图像文件已存在，直接使用已有路径；否则保存到本地
            local_image_path = image_result.get("local_path")
            if not local_image_path:
                local_image_path = self._save_avatar_image(avatar_id, image_url, image_base64, role_features.get("style", "realistic"))
            
            # 确保 local_image_url 和 avatar 字段正确设置（avatar字段用于前端显示）
            if local_image_path:
                image_filename = Path(local_image_path).name
                # 使用API路由而不是静态文件服务，避免403问题
                image_url_full = f"/ai/digital-human/image/{image_filename}"
                avatar_data["image_url"] = image_url  # 保留原始URL
                avatar_data["image_base64"] = image_base64  # 保留base64（如果可用）
                avatar_data["local_image_path"] = local_image_path  # 本地保存路径
                avatar_data["local_image_url"] = image_url_full  # 前端可访问的URL
                avatar_data["avatar"] = image_url_full  # avatar字段设置为图像URL，供前端直接使用
                avatar_data["status"] = "ready"
                logger.info(f"✅ 数字人图像URL已设置: avatar={image_url_full}, local_image_url={image_url_full}")
            else:
                logger.warning(f"无法获取图像路径: role_id={role_id}")
        else:
            logger.warning(f"没有图像结果: role_id={role_id}")
        
        # 保存到本地JSON文件（持久化）
        self._save_avatar_data_to_file(avatar_id, avatar_data)
        
        # 更新缓存（使用avatar_id作为key）
        cache_key = f"{role_id}:{avatar_id}"
        self.avatar_cache[cache_key] = avatar_data
        
        logger.info(f"数字人形象生成成功: role_id={role_id}, avatar_id={avatar_id}, modelUrl={model_url}, has_image={image_result is not None}, local_image={avatar_data.get('local_image_path')}")
        return avatar_data
    
    def _generate_model_url(self, role_id: str, style: str) -> str:
        """
        生成模型URL
        
        Args:
            role_id: 角色ID
            style: 风格 (realistic/cartoon/anime)
        
        Returns:
            模型URL（可以是占位符URL或实际模型路径）
        """
        # 根据风格生成不同的模型标识
        style_map = {
            "realistic": "realistic",
            "cartoon": "cartoon",
            "anime": "anime"
        }
        style_key = style_map.get(style, "realistic")
        
        # 生成模型URL（实际项目中应该返回真实的3D模型路径）
        # 这里返回一个标识符，前端可以根据这个标识符加载对应的模型
        model_url = f"/models/digital-human/{style_key}/{role_id}.glb"
        
        # 或者返回一个占位符URL（如果还没有实际模型）
        # model_url = f"/static/digital-human-placeholder-{style_key}.glb"
        
        return model_url
    
    def _get_timestamp(self) -> str:
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()
    
    def _generate_base_avatar(self, features: Dict) -> Dict:
        """生成基础数字人形象"""
        # 简化实现：根据角色特征生成配置
        avatar_config = {
            "model_type": "humanoid",
            "gender": self._infer_gender(features.get("profession", "")),
            "age_range": self._infer_age(features.get("profession", "")),
            "appearance": {
                "hair_style": "professional",
                "clothing": self._infer_clothing(features.get("profession", "")),
                "accessories": []
            }
        }
        return avatar_config
    
    def _apply_role_style(self, base_avatar: Dict, features: Dict) -> Dict:
        """应用角色风格"""
        style = features.get("style", "realistic")
        
        if style == "cartoon":
            base_avatar["render_style"] = "cartoon"
            base_avatar["exaggeration"] = 1.2
        elif style == "anime":
            base_avatar["render_style"] = "anime"
            base_avatar["exaggeration"] = 1.5
        else:  # realistic
            base_avatar["render_style"] = "realistic"
            base_avatar["exaggeration"] = 1.0
        
        return base_avatar
    
    def _generate_expressions(self, avatar: Dict) -> Dict:
        """生成表情库"""
        expressions = {
            "neutral": {"intensity": 0.0},
            "happy": {"intensity": 0.8, "mouth": "smile", "eyes": "bright"},
            "sad": {"intensity": 0.6, "mouth": "frown", "eyes": "down"},
            "angry": {"intensity": 0.7, "mouth": "tight", "eyes": "narrow"},
            "surprised": {"intensity": 0.8, "mouth": "open", "eyes": "wide"},
            "confused": {"intensity": 0.6, "mouth": "slight_open", "eyes": "squint"}
        }
        return expressions
    
    def _generate_animations(self, avatar: Dict) -> Dict:
        """生成动画库"""
        animations = {
            "idle": {"duration": 2.0, "loop": True},
            "speaking": {"duration": 0.1, "loop": True},
            "nodding": {"duration": 1.0, "loop": False},
            "gesturing": {"duration": 1.5, "loop": False}
        }
        return animations
    
    def _infer_gender(self, profession: str) -> str:
        """根据职业推断性别（简化实现）"""
        # 根据职业特征推断性别（实际应该使用更智能的方法）
        # 这里使用中性，让AI自由生成
        return "neutral"
    
    def _infer_age(self, profession: str) -> str:
        """根据职业推断年龄"""
        if "律师" in profession or "医生" in profession:
            return "30-40"
        elif "教师" in profession:
            return "25-35"
        else:
            return "25-35"
    
    def _infer_clothing(self, profession: str) -> str:
        """根据职业推断服装"""
        if "律师" in profession:
            return "suit"
        elif "医生" in profession:
            return "white_coat"
        elif "教师" in profession:
            return "casual_professional"
        else:
            return "casual"
    
    def _build_digital_human_prompt(self, role_features: Dict) -> str:
        """
        构建专业的数字人形象生成提示词
        
        Args:
            role_features: 角色特征，包含personality、profession、style等
        
        Returns:
            完整的图像生成提示词
        """
        profession = role_features.get("profession", "")
        personality = role_features.get("personality", "")
        style = role_features.get("style", "realistic")
        
        # 根据职业推断性别和年龄
        gender = self._infer_gender(profession)
        age_range = self._infer_age(profession)
        
        # 根据职业推断服装和外观
        clothing = self._infer_clothing(profession)
        
        # 构建基础描述
        base_description = []
        
        # 年龄和性别
        if gender == "female":
            base_description.append(f"一位{age_range}岁的女性")
        elif gender == "male":
            base_description.append(f"一位{age_range}岁的男性")
        else:
            base_description.append(f"一位{age_range}岁的专业人士")
        
        # 职业特征
        profession_descriptions = {
            "律师": "专业律师，穿着正式西装，表情严肃认真，眼神坚定",
            "教师": "温和的教师，穿着休闲职业装，面带微笑，眼神亲切",
            "程序员": "技术专家，穿着休闲T恤或衬衫，表情专注，眼神敏锐",
            "作家": "文艺工作者，穿着文艺风格服装，表情温和，眼神深邃",
            "医生": "专业医生，穿着白大褂，表情温和专业，眼神关切"
        }
        
        if profession in profession_descriptions:
            base_description.append(profession_descriptions[profession])
        else:
            base_description.append(f"{profession}专业人士")
        
        # 性格特征
        if personality:
            personality_map = {
                "严谨": "表情严肃，姿态端正",
                "专业": "专业形象，自信姿态",
                "温和": "温和表情，亲切姿态",
                "耐心": "耐心表情，温和眼神",
                "创意": "富有创意，表情生动",
                "技术": "专注表情，专业姿态"
            }
            personality_traits = []
            for trait in personality.split("、") if "、" in personality else [personality]:
                trait = trait.strip()
                if trait in personality_map:
                    personality_traits.append(personality_map[trait])
            if personality_traits:
                base_description.append("，".join(personality_traits))
        
        # 风格设置
        style_prompts = {
            "realistic": "写实风格，高清渲染，细节丰富，真实感强，专业摄影",
            "cartoon": "卡通风格，色彩鲜艳，线条简洁，可爱生动，动画风格",
            "anime": "二次元风格，日式动漫风格，大眼睛，精致五官，动漫渲染"
        }
        style_prompt = style_prompts.get(style, style_prompts["realistic"])
        
        # 组合完整提示词
        full_prompt = f"{'，'.join(base_description)}，{style_prompt}，全身像，正面视角，背景简洁，高质量，4K分辨率"
        
        logger.debug(f"构建的数字人提示词: {full_prompt}")
        return full_prompt
    
    async def _generate_avatar_image(self, prompt: str, role_features: Dict) -> Optional[Dict]:
        """
        调用AI接口生成数字人形象图像
        
        Args:
            prompt: 图像生成提示词
            role_features: 角色特征
        
        Returns:
            包含image_url、image_base64等的字典，如果失败返回None
        """
        try:
            # 使用独立的图像生成服务
            from app.services.imagegenerationservice import image_generation_service
            
            style = role_features.get("style", "realistic")
            size = "1024*1024"  # 默认尺寸
            
            result = await image_generation_service.generate_image(
                prompt=prompt,
                style=style,
                size=size
            )
            
            # 检查是否成功
            if result.get("success"):
                return result
            else:
                error_msg = result.get("error", "未知错误")
                logger.warning(f"图像生成失败: {error_msg}")
                return None
            
        except Exception as e:
            logger.error(f"生成数字人形象图像失败: {e}", exc_info=True)
            return None
    
    async def _get_ai_client(self):
        """获取AI客户端（延迟初始化，用于其他功能）"""
        if self._ai_client is None:
            try:
                from app.ai_engine.kylin_sdk.client import KylinAIClient
                self._ai_client = KylinAIClient()
            except Exception as e:
                logger.error(f"初始化AI客户端失败: {e}", exc_info=True)
                return None
        return self._ai_client
    
    def _save_avatar_image(self, avatar_id: str, image_url: str, image_base64: str, style: str) -> Optional[str]:
        """
        保存数字人图像到本地文件系统
        
        Args:
            avatar_id: 形象ID
            image_url: 远程图像URL
            image_base64: base64编码的图像数据
            style: 风格
        
        Returns:
            本地保存路径，如果失败返回None
        """
        try:
            # 检查文件是否已存在（避免重复生成，使用avatar_id作为文件名）
            existing_file = None
            for img_file in self.avatar_image_dir.glob(f"{avatar_id}_*.png"):
                if img_file.exists():
                    existing_file = img_file
                    break
            
            if existing_file:
                logger.info(f"✅ 图像文件已存在，跳过保存: {existing_file}")
                return str(existing_file)
            
            # 生成新的文件名（使用avatar_id和时间戳）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{avatar_id}_{timestamp}.png"
            local_path = self.avatar_image_dir / filename
            
            # 优先使用base64数据
            if image_base64:
                try:
                    image_data = base64.b64decode(image_base64)
                    with open(local_path, 'wb') as f:
                        f.write(image_data)
                    logger.info(f"✅ 数字人图像已保存到本地: {local_path}")
                    return str(local_path)
                except Exception as e:
                    logger.warning(f"使用base64保存图像失败: {e}，尝试下载远程URL")
            
            # 如果base64不可用，尝试下载远程URL
            if image_url and image_url.startswith("http"):
                try:
                    import httpx
                    with httpx.Client(timeout=30.0) as client:
                        response = client.get(image_url)
                        response.raise_for_status()
                        with open(local_path, 'wb') as f:
                            f.write(response.content)
                    logger.info(f"✅ 数字人图像已从远程下载并保存: {local_path}")
                    return str(local_path)
                except Exception as e:
                    logger.warning(f"下载远程图像失败: {e}")
            
            return None
        except Exception as e:
            logger.error(f"保存数字人图像失败: {e}", exc_info=True)
            return None
    
    def _save_avatar_data_to_file(self, avatar_id: str, avatar_data: Dict):
        """
        保存数字人数据到本地JSON文件（持久化）
        
        Args:
            avatar_id: 形象ID
            avatar_data: 数字人数据
        """
        try:
            data_dir = DIGITAL_HUMAN_METADATA_DIR
            data_dir.mkdir(parents=True, exist_ok=True)
            
            # 使用avatar_id作为文件名
            file_path = data_dir / f"{avatar_id}.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(avatar_data, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ 数字人数据已保存到本地: {file_path}")
        except Exception as e:
            logger.warning(f"保存数字人数据到文件失败: {e}")
    
    def _load_avatar_data_from_file(self, avatar_id: str) -> Optional[Dict]:
        """
        从本地JSON文件加载数字人数据
        
        Args:
            avatar_id: 形象ID
        
        Returns:
            数字人数据，如果不存在返回None
        """
        try:
            data_dir = DIGITAL_HUMAN_METADATA_DIR
            file_path = data_dir / f"{avatar_id}.json"
            
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    avatar_data = json.load(f)
                logger.info(f"✅ 从本地文件加载数字人数据: {file_path}")
                return avatar_data
        except Exception as e:
            logger.warning(f"从本地文件加载数字人数据失败: {e}")
        return None
    
    def list_avatars_by_role(self, role_id: str) -> List[Dict]:
        """
        列出角色的所有数字人形象
        
        Args:
            role_id: 角色ID
        
        Returns:
            形象列表
        """
        avatars = []
        try:
            data_dir = DIGITAL_HUMAN_METADATA_DIR
            
            if data_dir.exists():
                # 遍历所有JSON文件，查找属于该角色的形象
                for json_file in data_dir.glob("*.json"):
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            avatar_data = json.load(f)
                            if avatar_data.get("role_id") == role_id:
                                avatars.append(avatar_data)
                    except Exception as e:
                        logger.warning(f"加载形象文件失败: {json_file}, {e}")
            
            # 也检查缓存
            for cache_key, avatar_data in self.avatar_cache.items():
                if isinstance(avatar_data, dict) and avatar_data.get("role_id") == role_id:
                    if avatar_data not in avatars:
                        avatars.append(avatar_data)
        except Exception as e:
            logger.error(f"列出角色形象失败: {e}", exc_info=True)
        
        # 按创建时间排序（最新的在前）
        avatars.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return avatars


class VoiceDrivenDigitalHuman:
    """实时语音驱动数字人"""
    
    def __init__(self, avatar: Dict):
        self.avatar = avatar
        self.lip_sync_enabled = True
        self.face_animation_enabled = True
        
    def drive_by_voice(self, audio_stream: bytes, text: str) -> Dict:
        """
        实时语音驱动数字人
        
        Args:
            audio_stream: 音频流
            text: 对应的文本
        
        Returns:
            动画数据
        """
        # 分析音频特征
        audio_features = self._analyze_audio(audio_stream)
        
        # 口型同步
        lip_poses = self._generate_lip_sync(audio_stream, text)
        
        # 情感表情
        emotion = self._detect_emotion_from_audio(audio_stream)
        facial_expressions = self._generate_facial_expressions(emotion, audio_features)
        
        # 身体动作
        body_gestures = self._generate_gestures(audio_features, emotion, text)
        
        # 合成动画
        animation = self._combine_animations(lip_poses, facial_expressions, body_gestures)
        
        return animation
    
    def _analyze_audio(self, audio_stream: bytes) -> Dict:
        """分析音频特征（使用专业音频分析服务）"""
        try:
            from app.services.audioanalysisservice import audio_analysis_service
            return audio_analysis_service.analyze_audio(
                audio_data=audio_stream,
                sample_rate=16000
            )
        except Exception as e:
            logger.warning(f"使用音频分析服务失败: {e}，使用简化实现")
            return {
                "intensity": 0.7,
                "rhythm": 0.6,
                "pitch": 0.5,
                "duration": len(audio_stream) / 16000,
                "method": "fallback"
            }
    
    def _generate_lip_sync(self, audio: bytes, text: str) -> List[Dict]:
        """生成口型同步数据（增强实现）"""
        # 根据文本和音频生成口型同步
        phonemes = self._text_to_phonemes(text)
        lip_poses = []
        
        # 分析音频特征（简化实现）
        audio_duration = len(audio) / 16000  # 假设16kHz采样率
        phoneme_duration = audio_duration / len(phonemes) if phonemes else 0.1
        
        for i, phoneme in enumerate(phonemes):
            lip_pose = self._phoneme_to_lip_pose(phoneme)
            lip_pose["timestamp"] = i * phoneme_duration
            lip_pose["duration"] = phoneme_duration
            lip_poses.append(lip_pose)
        
        return lip_poses
    
    def _text_to_phonemes(self, text: str) -> List[str]:
        """文本转音素（使用音频分析服务）"""
        try:
            from app.services.audioanalysisservice import audio_analysis_service
            return audio_analysis_service._text_to_phonemes(text)
        except Exception as e:
            logger.warning(f"使用音频分析服务音素转换失败: {e}，使用简化实现")
            # 降级到简化实现
            phonemes = []
            for char in text:
                if char.isalpha():
                    phonemes.append(char.lower())
                elif char in ["，", "。", "！", "？", ",", ".", "!", "?"]:
                    phonemes.append("pause")
            return phonemes if phonemes else list(text)
    
    def _phoneme_to_lip_pose(self, phoneme: str) -> Dict:
        """音素转口型（增强实现）"""
        # 扩展的口型映射
        lip_map = {
            # 元音
            "a": {"mouth_open": 0.8, "mouth_width": 0.6, "lip_protrusion": 0.0},
            "o": {"mouth_open": 0.7, "mouth_width": 0.5, "lip_protrusion": 0.3},
            "e": {"mouth_open": 0.6, "mouth_width": 0.5, "lip_protrusion": 0.0},
            "i": {"mouth_open": 0.3, "mouth_width": 0.4, "lip_protrusion": 0.0},
            "u": {"mouth_open": 0.5, "mouth_width": 0.3, "lip_protrusion": 0.5},
            "v": {"mouth_open": 0.4, "mouth_width": 0.3, "lip_protrusion": 0.4},  # ü
            # 辅音
            "b": {"mouth_open": 0.0, "mouth_width": 0.5, "lip_protrusion": 0.2},
            "p": {"mouth_open": 0.0, "mouth_width": 0.5, "lip_protrusion": 0.3},
            "m": {"mouth_open": 0.0, "mouth_width": 0.5, "lip_protrusion": 0.1},
            "f": {"mouth_open": 0.2, "mouth_width": 0.3, "lip_protrusion": 0.1},
            # 停顿
            "pause": {"mouth_open": 0.1, "mouth_width": 0.4, "lip_protrusion": 0.0}
        }
        
        # 默认口型
        default_pose = {"mouth_open": 0.5, "mouth_width": 0.5, "lip_protrusion": 0.0}
        
        return lip_map.get(phoneme.lower(), default_pose)
    
    def _detect_emotion_from_audio(self, audio: bytes) -> Dict:
        """从音频检测情感（增强实现，使用音频分析服务）"""
        try:
            from app.services.audioanalysisservice import audio_analysis_service
            from app.services.voiceemotionrecognition import VoiceEmotionRecognizer
            
            # 使用音频分析服务提取特征
            audio_features = audio_analysis_service.analyze_audio(
                audio_data=audio,
                sample_rate=16000
            )
            
            # 使用语音情感识别服务
            emotion_recognizer = VoiceEmotionRecognizer()
            emotion_result = emotion_recognizer.recognize_emotion(audio)
            
            # 结合音频特征和情感识别结果
            emotion = emotion_result.get("emotion", "neutral")
            intensity = emotion_result.get("intensity", audio_features.get("intensity", 0.5))
            confidence = emotion_result.get("confidence", 0.7)
            
            # 根据音调和节奏调整情感强度
            pitch = audio_features.get("pitch", 0.5)
            if pitch > 0.7:
                intensity = min(1.0, intensity * 1.2)  # 高音调增强情感
            elif pitch < 0.3:
                intensity = max(0.0, intensity * 0.8)  # 低音调减弱情感
            
            return {
                "emotion": emotion,
                "intensity": float(intensity),
                "confidence": float(confidence),
                "audio_features": audio_features,
                "method": "enhanced"
            }
        except Exception as e:
            logger.warning(f"使用音频分析服务检测情感失败: {e}，使用简化实现")
            # 降级到简化实现
            return {
                "emotion": "neutral",
                "intensity": 0.5,
                "confidence": 0.7,
                "method": "simplified"
            }
    
    def _generate_facial_expressions(self, emotion: Dict, audio_features: Dict) -> List[Dict]:
        """生成面部表情"""
        expressions = []
        intensity = emotion.get("intensity", 0.5)
        
        expression = {
            "type": emotion.get("emotion", "neutral"),
            "intensity": intensity,
            "duration": audio_features.get("duration", 1.0)
        }
        expressions.append(expression)
        
        return expressions
    
    def _generate_gestures(self, audio_features: Dict, emotion: Dict, text: str) -> List[Dict]:
        """生成身体动作（增强实现）"""
        gestures = []
        
        emotion_type = emotion.get("emotion", "neutral")
        intensity = emotion.get("intensity", 0.5)
        rhythm = audio_features.get("rhythm", 0.5)
        
        # 根据情感生成手势（增强版）
        tempo = audio_features.get("tempo", 0.0)
        duration = audio_features.get("duration", 1.0)
        
        emotion_gestures_map = {
            "excited": {
                "type": "energetic_gesture",
                "intensity": min(1.0, intensity * 1.2),
                "duration": 1.0,
                "frequency": "high"
            },
            "happy": {
                "type": "welcoming_gesture",
                "intensity": intensity * 0.8,
                "duration": 0.8,
                "frequency": "medium"
            },
            "sad": {
                "type": "subdued_gesture",
                "intensity": intensity * 0.6,
                "duration": 1.2,
                "frequency": "low"
            },
            "angry": {
                "type": "emphatic_gesture",
                "intensity": min(1.0, intensity * 1.1),
                "duration": 0.6,
                "frequency": "high"
            },
            "neutral": {
                "type": "natural_gesture",
                "intensity": 0.5,
                "duration": 1.0,
                "frequency": "medium"
            }
        }
        
        # 根据情感选择手势
        base_gesture = emotion_gestures_map.get(emotion_type, emotion_gestures_map["neutral"])
        
        # 根据节奏调整手势频率
        if rhythm > 0.7:
            gesture_count = max(2, int(duration * 2))
        elif rhythm < 0.3:
            gesture_count = max(1, int(duration * 0.5))
        else:
            gesture_count = max(1, int(duration))
        
        # 根据tempo调整手势时长
        if tempo > 0:
            gesture_duration = base_gesture["duration"] * (120.0 / max(tempo, 60.0))
        else:
            gesture_duration = base_gesture["duration"]
        
        # 生成多个手势
        for i in range(gesture_count):
            gesture = {
                "type": base_gesture["type"],
                "intensity": float(base_gesture["intensity"]),
                "duration": float(gesture_duration),
                "timestamp": i * (duration / gesture_count) if gesture_count > 1 else 0.0,
                "rhythm_sync": rhythm > 0.5,
                "emotion": emotion_type
            }
            gestures.append(gesture)
        
        # 根据音频节奏生成额外手势
        if rhythm > 0.6:
            gestures.append({
                "type": "rhythmic_hand_gesture",
                "intensity": rhythm,
                "duration": 0.5,
                "frequency": 2.0,
                "timestamp": duration * 0.5
            })
        
        # 根据文本长度生成点头动作
        if len(text) > 50:
            gestures.append({
                "type": "nodding",
                "intensity": 0.5,
                "duration": 0.3,
                "count": min(len(text) // 20, 3),
                "timestamp": duration * 0.3
            })
        
        return gestures
    
    def _combine_animations(self, lip_poses: List, facial_expressions: List, body_gestures: List) -> Dict:
        """合成完整动画"""
        return {
            "lip_sync": lip_poses,
            "facial_expressions": facial_expressions,
            "body_gestures": body_gestures,
            "duration": max(
                len(lip_poses) * 0.1,
                sum(e.get("duration", 0) for e in facial_expressions),
                sum(g.get("duration", 0) for g in body_gestures)
            )
        }


class DigitalHumanService:
    """数字人服务主类"""
    
    def __init__(self):
        self.generator = DigitalHumanGenerator()
        self.avatar_metadata_dir = DIGITAL_HUMAN_METADATA_DIR
        self.active_avatars = {}  # 当前激活的数字人
    
    def _update_local_image_path(self, avatar_data: Dict):
        """
        更新数字人数据的本地图像路径（如果本地文件存在）
        
        Args:
            avatar_data: 数字人数据（必须是非空字典）
        """
        if not avatar_data or not isinstance(avatar_data, dict):
            return
        
        avatar_id = avatar_data.get("avatar_id")
        if not avatar_id:
            return
        
        try:
            image_dir = DIGITAL_HUMAN_IMAGE_DIR
            if image_dir.exists():
                # 查找该形象的图像文件（使用avatar_id）
                for image_file in image_dir.glob(f"{avatar_id}_*.png"):
                    if image_file.exists():
                        local_path = str(image_file)
                        image_filename = image_file.name
                        # 使用API路由而不是静态文件服务，避免403问题
                        image_url_full = f"/ai/digital-human/image/{image_filename}"
                        avatar_data["local_image_path"] = local_path
                        avatar_data["local_image_url"] = image_url_full
                        avatar_data["avatar"] = image_url_full  # 添加avatar字段，供前端直接使用
                        avatar_data["image_url"] = image_url_full  # 确保image_url也设置
                        logger.info(f"✅ 找到本地图像文件并更新路径: {local_path}, URL: {image_url_full}")
                        return
        except Exception as e:
            logger.warning(f"更新本地图像路径失败: {e}", exc_info=True)
        
    async def create_digital_human(self, role_config: Dict, avatar_id: Optional[str] = None) -> Dict:
        """
        创建数字人（异步，支持AI图像生成）
        
        Args:
            role_config: 角色配置
            avatar_id: 形象ID（可选，不提供则自动生成）
        
        Returns:
            数字人数据
        """
        avatar_data = await self.generator.generate_avatar(role_config, avatar_id)
        avatar_id = avatar_data.get("avatar_id")
        role_id = role_config.get("role_id")
        
        # 创建语音驱动实例（使用avatar_config而不是avatar，因为avatar现在是图像URL）
        avatar_config = avatar_data.get("avatar_config", avatar_data.get("avatar", {}))
        if isinstance(avatar_config, str):
            # 如果avatar是字符串（图像URL），使用默认配置
            avatar_config = {}
        voice_driver = VoiceDrivenDigitalHuman(avatar_config)
        
        # 使用avatar_id作为key，支持一个角色有多个形象
        active_key = f"{role_id}:{avatar_id}"
        self.active_avatars[active_key] = {
            "avatar_data": avatar_data,
            "voice_driver": voice_driver
        }
        
        return avatar_data
    
    def update_digital_human_animation(self, role_id: str, audio: bytes, text: str) -> Dict:
        """
        更新数字人动画（语音驱动）
        
        Args:
            role_id: 角色ID
            audio: 音频流
            text: 文本
        
        Returns:
            动画数据
        """
        if role_id not in self.active_avatars:
            raise ValueError(f"数字人不存在: {role_id}")
        
        voice_driver = self.active_avatars[role_id]["voice_driver"]
        animation = voice_driver.drive_by_voice(audio, text)
        
        return animation
    
    def get_digital_human(self, role_id: str, avatar_id: Optional[str] = None) -> Optional[Dict]:
        """
        获取数字人信息（用于加载已创建的数字人）
        
        Args:
            role_id: 角色ID
            avatar_id: 形象ID（可选，不提供则返回该角色的第一个形象）
        
        Returns:
            数字人数据，如果不存在返回None
        """
        try:
            # 如果没有指定avatar_id，获取该角色的第一个形象
            if not avatar_id:
                avatars = self.list_avatars_by_role(role_id)
                if avatars:
                    avatar_data = avatars[0]
                    self._update_local_image_path(avatar_data)
                    return avatar_data
                return None
            
            # 先检查激活的数字人
            active_key = f"{role_id}:{avatar_id}"
            if active_key in self.active_avatars:
                avatar_data = self.active_avatars[active_key].get("avatar_data", {})
                if avatar_data:
                    self._update_local_image_path(avatar_data)
                    return avatar_data
            
            # 检查缓存
            cache_key = f"{role_id}:{avatar_id}"
            if cache_key in self.generator.avatar_cache:
                avatar_data = self.generator.avatar_cache[cache_key]
                if avatar_data:
                    self._update_local_image_path(avatar_data)
                    return avatar_data
            
            # 尝试从本地文件系统加载
            avatar_data = self.generator._load_avatar_data_from_file(avatar_id)
            if avatar_data and avatar_data.get("role_id") == role_id:
                # 更新缓存
                self.generator.avatar_cache[cache_key] = avatar_data
                self._update_local_image_path(avatar_data)
                return avatar_data
        except Exception as e:
            logger.error(f"获取数字人信息失败: {e}", exc_info=True)
            # 不抛出异常，返回None让API返回404
        
        return None
    
    def list_avatars_by_role(self, role_id: str) -> List[Dict]:
        """
        列出角色的所有数字人形象
        
        Args:
            role_id: 角色ID
        
        Returns:
            形象列表
        """
        return self.generator.list_avatars_by_role(role_id)
    
    def delete_avatar(self, avatar_id: str) -> bool:
        """
        删除数字人形象
        
        Args:
            avatar_id: 形象ID
        
        Returns:
            是否删除成功
        """
        try:
            # 从缓存中删除
            keys_to_remove = [k for k in self.generator.avatar_cache.keys() if k.endswith(f":{avatar_id}")]
            for key in keys_to_remove:
                del self.generator.avatar_cache[key]
            
            # 从激活列表中删除
            keys_to_remove = [k for k in self.active_avatars.keys() if k.endswith(f":{avatar_id}")]
            for key in keys_to_remove:
                del self.active_avatars[key]
            
            # 删除本地文件
            data_dir = DIGITAL_HUMAN_METADATA_DIR
            json_file = data_dir / f"{avatar_id}.json"
            if json_file.exists():
                json_file.unlink()
            
            # 删除图像文件
            image_dir = DIGITAL_HUMAN_IMAGE_DIR
            for image_file in image_dir.glob(f"{avatar_id}_*.png"):
                if image_file.exists():
                    image_file.unlink()
            
            logger.info(f"✅ 删除数字人形象成功: {avatar_id}")
            return True
        except Exception as e:
            logger.error(f"删除数字人形象失败: {e}", exc_info=True)
            return False
    
    def update_avatar_settings(self, avatar_id: str, settings: Dict) -> bool:
        """
        更新形象显示设置
        
        Args:
            avatar_id: 形象ID
            settings: 显示设置（颜色、大小、背景、位置等）
        
        Returns:
            是否更新成功
        """
        try:
            # 加载形象数据
            avatar_data = self.generator._load_avatar_data_from_file(avatar_id)
            if not avatar_data:
                # 尝试从缓存加载
                for cache_key, cached_data in self.generator.avatar_cache.items():
                    if cached_data.get("avatar_id") == avatar_id:
                        avatar_data = cached_data
                        break
            
            if not avatar_data:
                logger.warning(f"形象不存在，无法更新设置: {avatar_id}")
                return False
            
            # 更新设置
            avatar_data["display_settings"] = settings
            
            # 保存到文件
            self.generator._save_avatar_data_to_file(avatar_id, avatar_data)
            
            # 更新缓存
            role_id = avatar_data.get("role_id")
            if role_id:
                cache_key = f"{role_id}:{avatar_id}"
                self.generator.avatar_cache[cache_key] = avatar_data
            
            logger.info(f"✅ 形象设置已更新: {avatar_id}")
            return True
        except Exception as e:
            logger.error(f"更新形象设置失败: {e}", exc_info=True)
            return False
    
    def switch_avatar_style(self, role_id: str, new_style: str) -> Dict:
        """
        切换数字人风格
        
        Args:
            role_id: 角色ID
            new_style: 新风格（realistic/cartoon/anime）
        
        Returns:
            更新后的数字人数据
        """
        if role_id not in self.active_avatars:
            raise ValueError(f"数字人不存在: {role_id}")
        
        avatar_data = self.active_avatars[role_id]["avatar_data"]
        # 使用avatar_config而不是avatar，因为avatar现在是图像URL
        avatar = avatar_data.get("avatar_config", {})
        
        # 应用新风格
        avatar["render_style"] = new_style
        if new_style == "cartoon":
            avatar["exaggeration"] = 1.2
        elif new_style == "anime":
            avatar["exaggeration"] = 1.5
        else:
            avatar["exaggeration"] = 1.0
        
        return avatar_data


# 全局数字人服务实例
digital_human_service = DigitalHumanService()

