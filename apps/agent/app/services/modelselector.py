"""
智能模型选择服务
根据性能、速度、资源等因素选择最优模型
支持性能评估和实时切换
"""
import logging
import time
from typing import Dict, Optional, List
from enum import Enum
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 尝试导入联邦学习优化器
FEDERATED_OPTIMIZATION_AVAILABLE = False
federated_model_optimizer = None

try:
    from app.services.federatedmodeloptimizer import federated_model_optimizer
    if federated_model_optimizer is not None:
        FEDERATED_OPTIMIZATION_AVAILABLE = True
except (ImportError, AttributeError, Exception) as e:
    FEDERATED_OPTIMIZATION_AVAILABLE = False
    # 只在DEBUG模式下显示详细错误，避免生产环境日志过多
    logger.debug(f"联邦学习优化器不可用: {e}")

class ModelType(Enum):
    """模型类型"""
    FAST = "fast"      # 快速模型
    BALANCED = "balanced"  # 平衡模型
    ADVANCED = "advanced"  # 高级模型

class ModelSelector:
    """模型选择器"""
    
    def __init__(self):
        self.models = {
            ModelType.FAST: {
                "name": "fast-model",
                "speed": 0.9,
                "quality": 0.6,
                "resource": 0.3,
                "cost": 0.2
            },
            ModelType.BALANCED: {
                "name": "balanced-model",
                "speed": 0.7,
                "quality": 0.8,
                "resource": 0.6,
                "cost": 0.5
            },
            ModelType.ADVANCED: {
                "name": "advanced-model",
                "speed": 0.4,
                "quality": 0.95,
                "resource": 0.9,
                "cost": 0.9
            }
        }
        
        # 性能评估数据
        self.performance_metrics = defaultdict(list)  # {model_type: [metrics]}
        self.current_model = ModelType.BALANCED
        self.switch_history = []  # 切换历史
    
    def select_model(
        self,
        priority: str = "balance",
        available_resources: float = 1.0,
        task_type: Optional[str] = None,
        use_performance_data: bool = True,
        use_federated_optimization: bool = True
    ) -> ModelType:
        """
        选择模型
        
        Args:
            priority: 优先级 (speed/quality/balance)
            available_resources: 可用资源 (0.0-1.0)
            task_type: 任务类型（可选）
            use_performance_data: 是否使用性能数据
        
        Returns:
            选择的模型类型
        """
        # 如果使用性能数据，先评估
        if use_performance_data and self.performance_metrics:
            best_model = self._select_based_on_performance(priority, task_type)
            if best_model:
                self.current_model = best_model
                return best_model
        
        # 基于优先级和资源选择
        if priority == "speed":
            selected = ModelType.FAST
        elif priority == "quality":
            if available_resources > 0.7:
                selected = ModelType.ADVANCED
            else:
                selected = ModelType.BALANCED
        else:  # balance
            if available_resources > 0.5:
                selected = ModelType.BALANCED
            else:
                selected = ModelType.FAST
        
        # 如果启用联邦学习优化，尝试应用优化
        if use_federated_optimization and FEDERATED_OPTIMIZATION_AVAILABLE and federated_model_optimizer is not None:
            try:
                optimized_info = federated_model_optimizer.select_optimized_model(
                    priority=priority,
                    available_resources=available_resources,
                    use_federated_optimization=True
                )
                if optimized_info.get("optimized"):
                    logger.info(f"使用联邦学习优化的模型: {selected.value}")
            except Exception as e:
                logger.debug(f"联邦学习优化失败（使用基础模型）: {e}")
        
        # 检查是否需要切换
        if selected != self.current_model:
            self._switch_model(self.current_model, selected, reason=f"priority={priority}")
        
        self.current_model = selected
        return selected
    
    def _select_based_on_performance(self, priority: str, task_type: Optional[str]) -> Optional[ModelType]:
        """基于性能数据选择模型"""
        if not self.performance_metrics:
            return None
        
        # 计算各模型的综合得分
        model_scores = {}
        
        for model_type in ModelType:
            metrics = self.performance_metrics.get(model_type, [])
            if not metrics:
                continue
            
            # 计算平均性能
            recent_metrics = metrics[-10:] if len(metrics) > 10 else metrics  # 最近10次
            
            avg_response_time = sum(m.get("response_time", 1.0) for m in recent_metrics) / len(recent_metrics)
            avg_quality = sum(m.get("quality_score", 0.5) for m in recent_metrics) / len(recent_metrics)
            avg_success_rate = sum(m.get("success", 1) for m in recent_metrics) / len(recent_metrics)
            
            # 根据优先级计算得分
            if priority == "speed":
                score = (1.0 / avg_response_time) * 0.7 + avg_success_rate * 0.3
            elif priority == "quality":
                score = avg_quality * 0.7 + avg_success_rate * 0.3
            else:  # balance
                score = (1.0 / avg_response_time) * 0.4 + avg_quality * 0.4 + avg_success_rate * 0.2
            
            model_scores[model_type] = score
        
        if model_scores:
            best_model = max(model_scores, key=model_scores.get)
            return best_model
        
        return None
    
    def record_performance(
        self,
        model_type: ModelType,
        response_time: float,
        quality_score: float = 0.5,
        success: bool = True,
        task_type: Optional[str] = None
    ):
        """
        记录模型性能
        
        Args:
            model_type: 模型类型
            response_time: 响应时间（秒）
            quality_score: 质量得分（0-1）
            success: 是否成功
            task_type: 任务类型
        """
        metric = {
            "response_time": response_time,
            "quality_score": quality_score,
            "success": 1 if success else 0,
            "task_type": task_type,
            "timestamp": datetime.now().isoformat()
        }
        
        self.performance_metrics[model_type].append(metric)
        
        # 限制历史记录数量（保留最近1000条）
        if len(self.performance_metrics[model_type]) > 1000:
            self.performance_metrics[model_type] = self.performance_metrics[model_type][-1000:]
        
        logger.debug(f"记录模型性能: {model_type.value}, 响应时间={response_time:.2f}s, 质量={quality_score:.2f}")
    
    def _switch_model(self, from_model: ModelType, to_model: ModelType, reason: str = ""):
        """切换模型"""
        switch_record = {
            "from": from_model.value,
            "to": to_model.value,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        }
        
        self.switch_history.append(switch_record)
        
        # 限制历史记录数量
        if len(self.switch_history) > 100:
            self.switch_history = self.switch_history[-100:]
        
        logger.info(f"模型切换: {from_model.value} -> {to_model.value}, 原因: {reason}")
    
    def get_performance_statistics(self, model_type: Optional[ModelType] = None) -> Dict:
        """获取性能统计"""
        if model_type:
            models_to_check = [model_type]
        else:
            models_to_check = list(ModelType)
        
        stats = {}
        
        for model in models_to_check:
            metrics = self.performance_metrics.get(model, [])
            if not metrics:
                stats[model.value] = {
                    "total_requests": 0,
                    "avg_response_time": 0,
                    "avg_quality": 0,
                    "success_rate": 0
                }
                continue
            
            total = len(metrics)
            avg_response_time = sum(m.get("response_time", 0) for m in metrics) / total
            avg_quality = sum(m.get("quality_score", 0) for m in metrics) / total
            success_rate = sum(m.get("success", 0) for m in metrics) / total
            
            stats[model.value] = {
                "total_requests": total,
                "avg_response_time": avg_response_time,
                "avg_quality": avg_quality,
                "success_rate": success_rate,
                "recent_performance": self._get_recent_performance(model)
            }
        
        return stats
    
    def _get_recent_performance(self, model_type: ModelType, hours: int = 1) -> Dict:
        """获取最近N小时的性能"""
        metrics = self.performance_metrics.get(model_type, [])
        if not metrics:
            return {}
        
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent_metrics = [
            m for m in metrics
            if datetime.fromisoformat(m["timestamp"]) > cutoff_time
        ]
        
        if not recent_metrics:
            return {}
        
        return {
            "count": len(recent_metrics),
            "avg_response_time": sum(m.get("response_time", 0) for m in recent_metrics) / len(recent_metrics),
            "avg_quality": sum(m.get("quality_score", 0) for m in recent_metrics) / len(recent_metrics),
            "success_rate": sum(m.get("success", 0) for m in recent_metrics) / len(recent_metrics)
        }
    
    def get_model_info(self, model_type: ModelType) -> Dict:
        """获取模型信息"""
        info = self.models.get(model_type, {}).copy()
        
        # 添加性能统计
        stats = self.get_performance_statistics(model_type)
        if model_type.value in stats:
            info["performance"] = stats[model_type.value]
        
        return info
    
    def get_current_model(self) -> ModelType:
        """获取当前使用的模型"""
        return self.current_model
    
    def get_switch_history(self, limit: int = 10) -> List[Dict]:
        """获取切换历史"""
        return self.switch_history[-limit:] if limit > 0 else self.switch_history

# 全局模型选择器实例
model_selector = ModelSelector()

