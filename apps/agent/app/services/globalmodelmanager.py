"""
全局模型管理服务
管理联邦学习的全局模型,包括版本控制、分发、聚合
"""
import logging
import hashlib
import json
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)


class ModelVersion:
    """模型版本"""
    def __init__(self, version_id: str, model_params: Dict, metadata: Dict):
        self.version_id = version_id
        self.model_params = model_params
        self.metadata = metadata
        self.created_at = datetime.now()
        self.clients_count = 0
        self.performance_metrics = {}


class GlobalModelManager:
    """全局模型管理器"""
    
    def __init__(self, model_storage_dir: str = "data/global_models"):
        self.storage_dir = Path(model_storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # 当前全局模型
        self.current_model: Optional[ModelVersion] = None
        
        # 模型版本历史
        self.version_history: List[ModelVersion] = []
        
        # 已注册客户端
        self.registered_clients: Dict[str, Dict] = {}
        
        # 待聚合的参数更新
        self.pending_updates: List[Dict] = []
        
        # 只在第一次初始化时记录日志
        if not hasattr(GlobalModelManager, '_init_logged'):
            logger.info("✅ 全局模型管理器已初始化")
            GlobalModelManager._init_logged = True
    
    def initialize_base_model(
        self,
        model_type: str,
        model_params: Dict,
        training_data_info: Dict
    ) -> str:
        """
        初始化基础模型
        
        Args:
            model_type: 模型类型(text_generation/rag/digital_human)
            model_params: 模型参数
            training_data_info: 训练数据信息
        
        Returns:
            模型版本ID
        """
        version_id = self._generate_version_id(model_params)
        
        metadata = {
            'model_type': model_type,
            'training_data': training_data_info,
            'created_at': datetime.now().isoformat(),
            'version': '1.0.0'
        }
        
        self.current_model = ModelVersion(version_id, model_params, metadata)
        self.version_history.append(self.current_model)
        
        # 保存到磁盘
        self._save_model(self.current_model)
        
        logger.info(f"基础模型已初始化: {version_id}")
        return version_id
    
    def register_client(
        self,
        client_id: str,
        client_info: Dict
    ) -> Dict:
        """
        注册客户端
        
        Args:
            client_id: 客户端ID
            client_info: 客户端信息(名称、机构、数据规模等)
        
        Returns:
            注册信息(包含当前全局模型版本)
        """
        if client_id in self.registered_clients:
            logger.warning(f"客户端已注册: {client_id}")
        
        self.registered_clients[client_id] = {
            'client_id': client_id,
            'info': client_info,
            'registered_at': datetime.now().isoformat(),
            'current_model_version': self.current_model.version_id if self.current_model else None,
            'upload_count': 0,
            'last_upload': None
        }
        
        logger.info(f"客户端已注册: {client_id}")
        
        return {
            'success': True,
            'client_id': client_id,
            'current_model_version': self.current_model.version_id if self.current_model else None,
            'model_params': self.current_model.model_params if self.current_model else None
        }
    
    def distribute_model(
        self,
        client_id: str
    ) -> Dict:
        """
        分发全局模型到客户端
        
        Args:
            client_id: 客户端ID
        
        Returns:
            模型信息
        """
        if client_id not in self.registered_clients:
            raise ValueError(f"客户端未注册: {client_id}")
        
        if not self.current_model:
            raise ValueError("全局模型未初始化")
        
        logger.info(f"分发模型 {self.current_model.version_id} 到客户端 {client_id}")
        
        return {
            'version_id': self.current_model.version_id,
            'model_params': self.current_model.model_params,
            'metadata': self.current_model.metadata,
            'download_time': datetime.now().isoformat()
        }
    
    def collect_update(
        self,
        client_id: str,
        encrypted_update: Dict,
        update_metadata: Dict
    ) -> Dict:
        """
        收集客户端参数更新
        
        Args:
            client_id: 客户端ID
            encrypted_update: 加密的参数更新
            update_metadata: 更新元数据(训练轮次、数据量等)
        
        Returns:
            收集结果
        """
        if client_id not in self.registered_clients:
            raise ValueError(f"客户端未注册: {client_id}")
        
        # 存储待聚合的更新
        self.pending_updates.append({
            'client_id': client_id,
            'update': encrypted_update,
            'metadata': update_metadata,
            'timestamp': datetime.now().isoformat()
        })
        
        # 更新客户端统计
        self.registered_clients[client_id]['upload_count'] += 1
        self.registered_clients[client_id]['last_upload'] = datetime.now().isoformat()
        
        logger.info(f"收集到客户端 {client_id} 的参数更新")
        
        return {
            'success': True,
            'client_id': client_id,
            'pending_updates_count': len(self.pending_updates),
            'ready_to_aggregate': len(self.pending_updates) >= self._get_aggregation_threshold()
        }
    
    def aggregate_updates(
        self,
        min_clients: int = 3
    ) -> Dict:
        """
        聚合客户端参数更新
        
        Args:
            min_clients: 最小客户端数量
        
        Returns:
            聚合结果
        """
        if len(self.pending_updates) < min_clients:
            raise ValueError(f"参数更新数量不足,需要至少{min_clients}个")
        
        logger.info(f"开始聚合{len(self.pending_updates)}个客户端的参数更新")
        
        # 1. 解密参数(使用加密服务)
        from app.services.encryptionservice import encryption_service
        decrypted_updates = []
        for update_info in self.pending_updates:
            decrypted = encryption_service.decrypt_parameters(
                update_info['update']
            )
            decrypted_updates.append({
                'client_id': update_info['client_id'],
                'params': decrypted,
                'metadata': update_info['metadata']
            })
        
        # 2. 计算权重(基于数据量)
        total_data_size = sum(
            u['metadata'].get('data_size', 1.0) 
            for u in decrypted_updates
        )
        weights = [
            u['metadata'].get('data_size', 1.0) / total_data_size
            for u in decrypted_updates
        ]
        
        # 3. 聚合参数(使用联邦学习服务)
        from app.services.federatedlearning import federated_learning_service
        aggregated_params = federated_learning_service.aggregate_parameters(
            client_parameters=[u['params'] for u in decrypted_updates],
            weights=weights
        )
        
        # 4. 更新全局模型
        new_model_params = {}
        for key in self.current_model.model_params.keys():
            if key in aggregated_params:
                # 加权更新: θ_new = θ_old + α * Δθ
                learning_rate = 0.1
                new_model_params[key] = (
                    np.array(self.current_model.model_params[key]) + 
                    learning_rate * np.array(aggregated_params[key])
                ).tolist()
            else:
                new_model_params[key] = self.current_model.model_params[key]
        
        # 5. 创建新版本
        new_version_id = self._generate_version_id(new_model_params)
        new_metadata = {
            **self.current_model.metadata,
            'version': self._increment_version(self.current_model.metadata['version']),
            'aggregation_info': {
                'clients_count': len(decrypted_updates),
                'client_ids': [u['client_id'] for u in decrypted_updates],
                'aggregated_at': datetime.now().isoformat()
            }
        }
        
        new_model = ModelVersion(new_version_id, new_model_params, new_metadata)
        new_model.clients_count = len(decrypted_updates)
        
        # 6. 更新当前模型
        self.current_model = new_model
        self.version_history.append(new_model)
        
        # 7. 保存模型
        self._save_model(new_model)
        
        # 8. 清空待聚合更新
        self.pending_updates.clear()
        
        logger.info(f"参数聚合完成,新模型版本: {new_version_id}")
        
        return {
            'success': True,
            'new_version_id': new_version_id,
            'version': new_metadata['version'],
            'clients_participated': len(decrypted_updates),
            'aggregated_at': datetime.now().isoformat()
        }
    
    def get_model_history(self) -> List[Dict]:
        """获取模型版本历史"""
        return [
            {
                'version_id': v.version_id,
                'version': v.metadata.get('version'),
                'created_at': v.created_at.isoformat(),
                'clients_count': v.clients_count,
                'performance': v.performance_metrics
            }
            for v in self.version_history
        ]
    
    def get_client_statistics(self) -> Dict:
        """获取客户端统计信息"""
        return {
            'total_clients': len(self.registered_clients),
            'active_clients': sum(
                1 for c in self.registered_clients.values()
                if c['upload_count'] > 0
            ),
            'clients': list(self.registered_clients.values())
        }
    
    def _generate_version_id(self, model_params: Dict) -> str:
        """生成模型版本ID"""
        params_str = json.dumps(model_params, sort_keys=True)
        return hashlib.sha256(params_str.encode()).hexdigest()[:16]
    
    def _increment_version(self, version: str) -> str:
        """递增版本号"""
        parts = version.split('.')
        parts[-1] = str(int(parts[-1]) + 1)
        return '.'.join(parts)
    
    def _get_aggregation_threshold(self) -> int:
        """获取聚合阈值"""
        # 可配置:当收集到足够多的更新时触发聚合
        return 3
    
    def _save_model(self, model: ModelVersion):
        """保存模型到磁盘"""
        model_file = self.storage_dir / f"{model.version_id}.json"
        with open(model_file, 'w') as f:
            json.dump({
                'version_id': model.version_id,
                'params': model.model_params,
                'metadata': model.metadata,
                'created_at': model.created_at.isoformat()
            }, f, indent=2)
        logger.info(f"模型已保存: {model_file}")


# 全局实例
global_model_manager = GlobalModelManager()

