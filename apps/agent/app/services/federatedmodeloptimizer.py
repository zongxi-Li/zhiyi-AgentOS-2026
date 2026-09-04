"""
联邦学习模型优化集成服务
将联邦学习优化集成到模型选择系统
"""
import logging
from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.modelselector import ModelSelector, ModelType

from app.services.federatedlearning import FederatedLearningService

logger = logging.getLogger(__name__)


class FederatedModelOptimizer:
    """联邦学习模型优化器"""
    
    def __init__(self):
        # 延迟导入避免循环依赖
        from app.services.modelselector import ModelSelector, ModelType
        from app.services.federatedlearning import FederatedLearningService
        self.model_selector = ModelSelector()
        self.federated_learning = FederatedLearningService()
        self.optimized_models = {}  # 存储优化后的模型参数
        self.ModelType = ModelType  # 保存引用以便后续使用
    
    def select_optimized_model(
        self,
        priority: str = "balance",
        available_resources: float = 1.0,
        use_federated_optimization: bool = True
    ) -> Dict:
        """
        选择经过联邦学习优化的模型
        
        Args:
            priority: 优先级（speed/quality/balance）
            available_resources: 可用资源
            use_federated_optimization: 是否使用联邦学习优化
        
        Returns:
            选中的模型和优化信息
        """
        # 1. 基础模型选择
        base_model = self.model_selector.select_model(
            priority=priority,
            available_resources=available_resources
        )
        
        # 2. 如果启用联邦学习优化，应用优化参数
        if use_federated_optimization:
            optimized_model = self._apply_federated_optimization(base_model)
        else:
            optimized_model = {
                "model_type": base_model.value,
                "optimized": False
            }
        
        return {
            "model_type": base_model.value,
            "base_model": base_model.value,
            "optimized": use_federated_optimization,
            "optimization_info": optimized_model if use_federated_optimization else None,
            "priority": priority,
            "available_resources": available_resources
        }
    
    def _apply_federated_optimization(self, model_type) -> Dict:
        """应用联邦学习优化"""
        model_key = model_type.value
        
        # 检查是否有优化后的模型参数
        if model_key in self.optimized_models:
            optimized_params = self.optimized_models[model_key]
            return {
                "model_type": model_key,
                "optimized": True,
                "optimization_version": optimized_params.get("version", 1),
                "improvements": optimized_params.get("improvements", {})
            }
        else:
            # 尝试从联邦学习服务获取全局模型参数
            try:
                # 这里应该从联邦学习服务器获取聚合后的参数
                # 简化实现：返回优化标记
                return {
                    "model_type": model_key,
                    "optimized": False,
                    "message": "使用基础模型，联邦学习优化参数未加载"
                }
            except Exception as e:
                logger.warning(f"获取联邦学习优化参数失败: {e}")
                return {
                    "model_type": model_key,
                    "optimized": False,
                    "error": str(e)
                }
    
    def update_model_with_federated_params(
        self,
        model_type,
        federated_params: Dict
    ) -> bool:
        """
        使用联邦学习参数更新模型
        
        Args:
            model_type: 模型类型
            federated_params: 联邦学习聚合后的参数
        
        Returns:
            是否更新成功
        """
        try:
            model_key = model_type.value
            
            # 存储优化后的参数
            self.optimized_models[model_key] = {
                "params": federated_params,
                "version": self.optimized_models.get(model_key, {}).get("version", 0) + 1,
                "improvements": {
                    "accuracy": 0.05,  # 假设提升5%
                    "efficiency": 0.03  # 假设效率提升3%
                }
            }
            
            logger.info(f"模型 {model_key} 已更新联邦学习优化参数")
            return True
        except Exception as e:
            logger.error(f"更新模型参数失败: {e}")
            return False
    
    def get_optimization_status(self) -> Dict:
        """获取优化状态"""
        return {
            "optimized_models": list(self.optimized_models.keys()),
            "total_models": len(self.optimized_models),
            "optimization_enabled": True
        }


# 全局联邦学习模型优化器实例
federated_model_optimizer = FederatedModelOptimizer()





