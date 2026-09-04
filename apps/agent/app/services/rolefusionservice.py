"""
智能角色融合技术服务
实现多角色协同对话，融合不同角色的专业知识和对话风格
"""
import logging
from typing import Dict, List, Optional, Any
import numpy as np

logger = logging.getLogger(__name__)


class RoleFusionService:
    """角色融合服务"""
    
    def __init__(self):
        self.role_knowledge_domains = {}  # 角色知识领域映射
        
    def fuse_role_responses(
        self,
        question: str,
        available_roles: List[Dict],
        role_responses: Dict[str, str]
    ) -> Dict:
        """
        融合多个角色的回答
        
        Args:
            question: 用户问题
            available_roles: 可用角色列表
            role_responses: 各角色的回答 {role_id: response}
        
        Returns:
            融合后的回答
        """
        # 1. 计算角色权重
        weights = self._calculate_role_weights(question, available_roles)
        
        # 2. 提取各角色的核心观点
        role_points = {}
        for role_id, response in role_responses.items():
            points = self._extract_core_points(response, role_id)
            role_points[role_id] = points
        
        # 3. 融合回答
        fused_response = self._fuse_responses(role_points, weights)
        
        # 4. 平衡风格
        balanced_style = self._balance_style(available_roles, weights)
        
        return {
            "response": fused_response,
            "style": balanced_style,
            "weights": weights,
            "sources": {role_id: role_responses[role_id] for role_id in weights.keys()}
        }
    
    def _calculate_role_weights(self, question: str, roles: List[Dict]) -> Dict[str, float]:
        """
        根据问题内容，计算各角色的权重
        
        Args:
            question: 用户问题
            roles: 角色列表
        
        Returns:
            角色权重字典 {role_id: weight}
        """
        question_keywords = self._extract_keywords(question)
        weights = {}
        
        for role in roles:
            role_id = role.get("role_id")
            knowledge_domain = role.get("knowledge_domain", [])
            
            # 计算相关性得分
            relevance = self._calculate_relevance(question_keywords, knowledge_domain)
            weights[role_id] = relevance
        
        # 归一化权重
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}
        else:
            # 如果无法计算权重，均匀分配
            weights = {role.get("role_id"): 1.0 / len(roles) for role in roles}
        
        logger.info(f"角色权重计算完成: {weights}")
        return weights
    
    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        # 使用jieba分词（如果可用）或简单分词
        try:
            import jieba
            words = jieba.cut(text)
            keywords = [w for w in words if len(w) > 1 and w.strip()]
        except ImportError:
            # 回退到简单分词
            words = text.split()
            keywords = [w for w in words if len(w) > 1]
        
        # 停用词过滤
        stop_words = {"的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好", "自己", "这"}
        keywords = [w for w in keywords if w not in stop_words]
        
        return keywords[:15]  # 增加关键词数量
    
    def _calculate_relevance(self, question_keywords: List[str], knowledge_domain: List[str]) -> float:
        """计算问题与知识领域的相关性"""
        if not question_keywords or not knowledge_domain:
            return 0.0
        
        # 计算关键词匹配度
        matches = 0
        for keyword in question_keywords:
            for domain in knowledge_domain:
                if keyword.lower() in domain.lower() or domain.lower() in keyword.lower():
                    matches += 1
                    break
        
        relevance = matches / len(question_keywords) if question_keywords else 0.0
        return relevance
    
    def _extract_core_points(self, response: str, role_id: str) -> Dict:
        """提取回答的核心观点"""
        # 改进实现：提取关键句子和要点
        sentences = response.replace('。', '。\n').replace('！', '！\n').replace('？', '？\n').split('\n')
        important_sentences = []
        
        # 识别重要句子（包含关键词、较长、有数字等）
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # 重要性评分
            score = 0
            if len(sentence) > 15:  # 长度
                score += 1
            if any(char.isdigit() for char in sentence):  # 包含数字
                score += 1
            if any(keyword in sentence for keyword in ["建议", "应该", "需要", "可以", "注意", "重要"]):  # 关键词
                score += 1
            if sentence.startswith(("首先", "其次", "最后", "另外", "此外")):  # 结构词
                score += 1
            
            if score >= 1 or len(sentence) > 10:
                important_sentences.append((sentence, score))
        
        # 按重要性排序
        important_sentences.sort(key=lambda x: x[1], reverse=True)
        main_points = [s[0] for s in important_sentences[:5]]  # 最多5个要点
        
        return {
            "main_points": main_points,
            "full_response": response,
            "role_id": role_id,
            "point_count": len(main_points)
        }
    
    def _fuse_responses(self, role_points: Dict[str, Dict], weights: Dict[str, float]) -> str:
        """融合多个角色的回答"""
        fused_parts = []
        
        # 按权重排序
        sorted_roles = sorted(weights.items(), key=lambda x: x[1], reverse=True)
        
        # 提取主要观点（带权重信息）
        main_points = []
        seen_points = set()  # 用于去重
        
        for role_id, weight in sorted_roles:
            if role_id in role_points:
                points = role_points[role_id]["main_points"]
                for point in points:
                    # 使用简化的文本相似度去重
                    point_normalized = point[:50]  # 取前50个字符作为标识
                    if point_normalized not in seen_points:
                        seen_points.add(point_normalized)
                        main_points.append({
                            "point": point,
                            "weight": weight,
                            "role_id": role_id
                        })
                        if len(main_points) >= 8:  # 增加要点数量
                            break
                if len(main_points) >= 8:
                    break
        
        # 组织融合后的回答
        if main_points:
            fused_parts.append("综合多个专业角度的分析：\n\n")
            
            # 按权重分组组织
            high_weight_points = [p for p in main_points if p["weight"] > 0.3]
            medium_weight_points = [p for p in main_points if 0.15 < p["weight"] <= 0.3]
            
            if high_weight_points:
                fused_parts.append("【核心观点】\n")
                for i, point_data in enumerate(high_weight_points[:3], 1):
                    fused_parts.append(f"{i}. {point_data['point']}\n")
            
            if medium_weight_points:
                fused_parts.append("\n【补充建议】\n")
                for i, point_data in enumerate(medium_weight_points[:3], 1):
                    fused_parts.append(f"{i}. {point_data['point']}\n")
        else:
            # 如果没有提取到要点，使用加权融合
            fused_parts.append(self._weighted_fusion(role_points, weights))
        
        return "".join(fused_parts)
    
    def _weighted_fusion(self, role_points: Dict[str, Dict], weights: Dict[str, float]) -> str:
        """加权融合回答"""
        parts = []
        sorted_roles = sorted(weights.items(), key=lambda x: x[1], reverse=True)
        
        for role_id, weight in sorted_roles:
            if role_id in role_points and weight > 0.2:  # 只包含权重>0.2的角色
                response = role_points[role_id]["full_response"]
                parts.append(f"【权重{weight:.1%}】{response[:200]}...\n")
        
        return "\n".join(parts) if parts else "暂无相关信息。"
    
    def _balance_style(self, roles: List[Dict], weights: Dict[str, float]) -> Dict:
        """平衡多个角色的对话风格"""
        style_features = []
        style_weights = []
        
        for role in roles:
            role_id = role.get("role_id")
            if role_id in weights:
                personality = role.get("personality", "")
                style = self._extract_style_features(personality)
                style_features.append(style)
                style_weights.append(weights[role_id])
        
        if not style_features:
            return {"formality": 0.5, "warmth": 0.5, "technical_level": 0.5}
        
        # 加权平均
        balanced_style = {
            "formality": self._weighted_average([s.get("formality", 0.5) for s in style_features], style_weights),
            "warmth": self._weighted_average([s.get("warmth", 0.5) for s in style_features], style_weights),
            "technical_level": max([s.get("technical_level", 0.5) for s in style_features])  # 取最大值
        }
        
        return balanced_style
    
    def _extract_style_features(self, personality: str) -> Dict:
        """从性格描述中提取风格特征"""
        personality_lower = personality.lower()
        
        # 正式度
        formality = 0.5
        if "正式" in personality or "严谨" in personality:
            formality = 0.8
        elif "随意" in personality or "轻松" in personality:
            formality = 0.3
        
        # 温暖度
        warmth = 0.5
        if "温和" in personality or "亲切" in personality or "耐心" in personality:
            warmth = 0.8
        elif "严肃" in personality or "严格" in personality:
            warmth = 0.3
        
        # 技术性
        technical_level = 0.5
        if "专业" in personality or "技术" in personality:
            technical_level = 0.8
        elif "通俗" in personality or "简单" in personality:
            technical_level = 0.3
        
        return {
            "formality": formality,
            "warmth": warmth,
            "technical_level": technical_level
        }
    
    def _weighted_average(self, values: List[float], weights: List[float]) -> float:
        """计算加权平均"""
        if not values or not weights or len(values) != len(weights):
            return 0.5
        
        total_weight = sum(weights)
        if total_weight == 0:
            return sum(values) / len(values) if values else 0.5
        
        weighted_sum = sum(v * w for v, w in zip(values, weights))
        return weighted_sum / total_weight


# 全局角色融合服务实例
role_fusion_service = RoleFusionService()

