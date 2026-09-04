"""
角色风格学习服务
从角色描述和对话示例中学习角色风格
"""
import logging
import re
from typing import Dict, List, Optional
from collections import defaultdict
import json

logger = logging.getLogger(__name__)


class RoleDescriptionParser:
    """角色描述解析器"""
    
    def __init__(self):
        self.style_keywords = {
            "formal": ["正式", "严谨", "专业", "规范", "标准"],
            "casual": ["随意", "轻松", "自然", "亲切", "友好"],
            "warm": ["温和", "温暖", "耐心", "体贴", "关怀"],
            "professional": ["专业", "技术", "专家", "资深", "经验丰富"],
            "creative": ["创意", "创新", "富有想象力", "独特", "新颖"],
            "humorous": ["幽默", "风趣", "有趣", "诙谐", "轻松"],
            "serious": ["严肃", "认真", "严格", "严谨", "庄重"]
        }
    
    def parse_description(self, description: str) -> Dict:
        """
        解析角色描述
        
        Args:
            description: 角色描述文本
        
        Returns:
            解析结果，包含风格特征、知识领域、性格特点等
        """
        if not description:
            return {
                "style_features": {},
                "knowledge_domains": [],
                "personality_traits": [],
                "tone": "neutral"
            }
        
        # 提取风格特征
        style_features = self._extract_style_features(description)
        
        # 提取知识领域
        knowledge_domains = self._extract_knowledge_domains(description)
        
        # 提取性格特点
        personality_traits = self._extract_personality_traits(description)
        
        # 确定语调
        tone = self._determine_tone(style_features, personality_traits)
        
        return {
            "style_features": style_features,
            "knowledge_domains": knowledge_domains,
            "personality_traits": personality_traits,
            "tone": tone,
            "original_description": description
        }
    
    def _extract_style_features(self, description: str) -> Dict:
        """提取风格特征"""
        features = {}
        description_lower = description.lower()
        
        for style, keywords in self.style_keywords.items():
            score = 0
            for keyword in keywords:
                if keyword in description_lower:
                    score += 1
            
            if score > 0:
                features[style] = min(score / len(keywords), 1.0)
        
        return features
    
    def _extract_knowledge_domains(self, description: str) -> List[str]:
        """提取知识领域"""
        domains = []
        
        # 常见知识领域关键词
        domain_keywords = {
            "法律": ["法律", "法规", "合同", "纠纷", "诉讼", "律师"],
            "教育": ["教育", "教学", "学习", "知识", "课程", "学生"],
            "技术": ["技术", "编程", "代码", "开发", "软件", "系统"],
            "医疗": ["医疗", "健康", "疾病", "治疗", "医生", "医院"],
            "商业": ["商业", "市场", "营销", "管理", "企业", "创业"],
            "艺术": ["艺术", "创作", "设计", "美学", "文化", "文学"]
        }
        
        description_lower = description.lower()
        for domain, keywords in domain_keywords.items():
            for keyword in keywords:
                if keyword in description_lower:
                    if domain not in domains:
                        domains.append(domain)
                    break
        
        return domains
    
    def _extract_personality_traits(self, description: str) -> List[str]:
        """提取性格特点"""
        traits = []
        
        trait_keywords = {
            "耐心": ["耐心", "细致", "认真"],
            "热情": ["热情", "积极", "主动"],
            "冷静": ["冷静", "理性", "客观"],
            "幽默": ["幽默", "风趣", "有趣"],
            "严谨": ["严谨", "严格", "认真"],
            "温和": ["温和", "温柔", "亲切"]
        }
        
        description_lower = description.lower()
        for trait, keywords in trait_keywords.items():
            for keyword in keywords:
                if keyword in description_lower:
                    if trait not in traits:
                        traits.append(trait)
                    break
        
        return traits
    
    def _determine_tone(self, style_features: Dict, personality_traits: List[str]) -> str:
        """确定语调"""
        if "formal" in style_features and style_features["formal"] > 0.5:
            return "formal"
        elif "casual" in style_features and style_features["casual"] > 0.5:
            return "casual"
        elif "warm" in style_features and style_features["warm"] > 0.5:
            return "warm"
        elif "humorous" in style_features and style_features["humorous"] > 0.5:
            return "humorous"
        else:
            return "neutral"


class StyleExampleLearner:
    """对话风格示例学习器"""
    
    def __init__(self):
        self.learned_patterns = {}  # 学习到的模式
    
    def learn_from_examples(
        self,
        examples: List[Dict],
        role_id: str
    ) -> Dict:
        """
        从对话示例中学习风格
        
        Args:
            examples: 对话示例列表 [{"user": "...", "role": "..."}]
            role_id: 角色ID
        
        Returns:
            学习到的风格特征
        """
        if not examples:
            return {}
        
        # 分析对话模式
        patterns = self._analyze_conversation_patterns(examples)
        
        # 提取语言特征
        language_features = self._extract_language_features(examples)
        
        # 提取回复结构
        response_structure = self._analyze_response_structure(examples)
        
        learned_style = {
            "patterns": patterns,
            "language_features": language_features,
            "response_structure": response_structure,
            "example_count": len(examples)
        }
        
        # 保存学习结果
        self.learned_patterns[role_id] = learned_style
        
        logger.info(f"从 {len(examples)} 个示例中学习角色风格: {role_id}")
        
        return learned_style
    
    def _analyze_conversation_patterns(self, examples: List[Dict]) -> Dict:
        """分析对话模式"""
        patterns = {
            "greeting_style": [],
            "question_handling": [],
            "explanation_style": [],
            "closing_style": []
        }
        
        for example in examples:
            role_response = example.get("role", "")
            
            # 问候语风格
            if any(word in role_response for word in ["你好", "您好", "hello", "hi"]):
                patterns["greeting_style"].append(role_response[:50])
            
            # 问题处理方式
            if "?" in role_response or "？" in role_response:
                patterns["question_handling"].append(role_response)
            
            # 解释风格
            if any(word in role_response for word in ["因为", "所以", "首先", "其次", "最后"]):
                patterns["explanation_style"].append(role_response)
            
            # 结束语风格
            if any(word in role_response for word in ["希望", "如果", "还有", "需要"]):
                patterns["closing_style"].append(role_response[-50:])
        
        return patterns
    
    def _extract_language_features(self, examples: List[Dict]) -> Dict:
        """提取语言特征"""
        all_responses = [ex.get("role", "") for ex in examples]
        combined_text = " ".join(all_responses)
        
        features = {
            "avg_length": sum(len(r) for r in all_responses) / len(all_responses) if all_responses else 0,
            "sentence_count": len(re.findall(r'[。！？]', combined_text)),
            "question_count": len(re.findall(r'[？?]', combined_text)),
            "exclamation_count": len(re.findall(r'[！!]', combined_text)),
            "formal_words": len(re.findall(r'[您|请|建议|应当|必须]', combined_text)),
            "casual_words": len(re.findall(r'[你|可以|试试|建议]', combined_text))
        }
        
        return features
    
    def _analyze_response_structure(self, examples: List[Dict]) -> Dict:
        """分析回复结构"""
        structures = {
            "direct_answer": 0,  # 直接回答
            "step_by_step": 0,   # 分步骤
            "with_examples": 0,   # 带示例
            "with_questions": 0   # 带反问
        }
        
        for example in examples:
            role_response = example.get("role", "")
            
            # 直接回答（开头就是答案）
            if len(role_response) > 0 and not role_response[0] in ["首先", "关于", "对于"]:
                structures["direct_answer"] += 1
            
            # 分步骤（包含序号或步骤词）
            if re.search(r'[一二三四五六七八九十]|首先|其次|最后|第一步|第二步', role_response):
                structures["step_by_step"] += 1
            
            # 带示例（包含"例如"、"比如"等）
            if re.search(r'例如|比如|举例|比如', role_response):
                structures["with_examples"] += 1
            
            # 带反问（包含问号）
            if "?" in role_response or "？" in role_response:
                structures["with_questions"] += 1
        
        # 归一化
        total = len(examples)
        if total > 0:
            for key in structures:
                structures[key] = structures[key] / total
        
        return structures
    
    def get_learned_style(self, role_id: str) -> Optional[Dict]:
        """获取学习到的风格"""
        return self.learned_patterns.get(role_id)


class RoleStyleLearningService:
    """角色风格学习服务"""
    
    def __init__(self):
        self.description_parser = RoleDescriptionParser()
        self.style_learner = StyleExampleLearner()
    
    def learn_role_style(
        self,
        role_id: str,
        description: Optional[str] = None,
        style_examples: Optional[List[Dict]] = None
    ) -> Dict:
        """
        学习角色风格
        
        Args:
            role_id: 角色ID
            description: 角色描述
            style_examples: 风格示例列表
        
        Returns:
            学习到的完整风格特征
        """
        learned_features = {
            "role_id": role_id,
            "from_description": {},
            "from_examples": {},
            "combined_style": {}
        }
        
        # 从描述中学习
        if description:
            parsed = self.description_parser.parse_description(description)
            learned_features["from_description"] = parsed
        
        # 从示例中学习
        if style_examples:
            learned = self.style_learner.learn_from_examples(style_examples, role_id)
            learned_features["from_examples"] = learned
        
        # 合并风格特征
        learned_features["combined_style"] = self._combine_styles(
            learned_features["from_description"],
            learned_features["from_examples"]
        )
        
        return learned_features
    
    def _combine_styles(self, from_description: Dict, from_examples: Dict) -> Dict:
        """合并风格特征"""
        combined = {
            "style_features": {},
            "tone": "neutral",
            "response_pattern": "direct"
        }
        
        # 合并风格特征
        desc_features = from_description.get("style_features", {})
        for style, score in desc_features.items():
            combined["style_features"][style] = score * 0.6  # 描述权重0.6
        
        # 从示例中提取风格（如果有）
        example_features = from_examples.get("language_features", {})
        if example_features.get("formal_words", 0) > example_features.get("casual_words", 0):
            combined["style_features"]["formal"] = combined["style_features"].get("formal", 0) + 0.4
        else:
            combined["style_features"]["casual"] = combined["style_features"].get("casual", 0) + 0.4
        
        # 确定语调
        combined["tone"] = from_description.get("tone", "neutral")
        
        # 确定回复模式
        response_structure = from_examples.get("response_structure", {})
        if response_structure.get("step_by_step", 0) > 0.5:
            combined["response_pattern"] = "step_by_step"
        elif response_structure.get("with_examples", 0) > 0.5:
            combined["response_pattern"] = "with_examples"
        else:
            combined["response_pattern"] = "direct"
        
        return combined


# 全局角色风格学习服务实例
role_style_learning_service = RoleStyleLearningService()





