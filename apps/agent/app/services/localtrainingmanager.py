"""
本地训练管理器
管理客户端的本地训练流程
"""
import logging
import json
import requests
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)


class LocalTrainingManager:
    """本地训练管理器"""
    
    def __init__(
        self,
        client_id: str,
        server_url: str,
        local_data_dir: str = "data/local_training"
    ):
        self.client_id = client_id
        self.server_url = server_url
        self.local_data_dir = Path(local_data_dir)
        self.local_data_dir.mkdir(parents=True, exist_ok=True)
        
        # 当前模型
        self.current_model: Optional[Dict] = None
        self.current_version: Optional[str] = None
        
        # 本地私有数据
        self.private_data: List[Dict] = []
        
        # 本地RAG知识库
        self.local_rag = None
        
        logger.info(f"本地训练管理器已初始化,客户端ID: {client_id}")
    
    def register_to_server(self, client_info: Dict) -> Dict:
        """
        注册到服务器
        
        Args:
            client_info: 客户端信息
        
        Returns:
            注册结果
        """
        try:
            response = requests.post(
                f"{self.server_url}/ai/global-model/register-client",
                json={
                    'client_id': self.client_id,
                    'client_info': client_info
                }
            )
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"注册成功: {self.client_id}")
            
            # 下载初始模型
            if result.get('current_model_version'):
                self._download_model()
            
            return result
        except Exception as e:
            logger.error(f"注册失败: {e}")
            raise
    
    def _download_model(self) -> Dict:
        """下载全局模型"""
        try:
            response = requests.get(
                f"{self.server_url}/ai/global-model/download/{self.client_id}"
            )
            response.raise_for_status()
            result = response.json()
            
            model_info = result['model']
            self.current_model = model_info['model_params']
            self.current_version = model_info['version_id']
            
            # 保存到本地
            model_file = self.local_data_dir / f"model_{self.current_version}.json"
            with open(model_file, 'w') as f:
                json.dump(model_info, f, indent=2)
            
            logger.info(f"模型已下载: {self.current_version}")
            
            return model_info
        except Exception as e:
            logger.error(f"下载模型失败: {e}")
            raise
    
    def load_private_data(self, data_source: str) -> int:
        """
        加载本地私有数据
        
        Args:
            data_source: 数据源路径
        
        Returns:
            数据数量
        """
        try:
            # 加载私有数据(实际应该从数据库/文件系统读取)
            # 这里简化为JSON文件
            with open(data_source, 'r', encoding='utf-8') as f:
                self.private_data = json.load(f)
            
            logger.info(f"已加载{len(self.private_data)}条私有数据")
            
            return len(self.private_data)
        except Exception as e:
            logger.error(f"加载私有数据失败: {e}")
            raise
    
    def build_local_rag(self) -> Dict:
        """
        构建本地私有RAG知识库
        
        Returns:
            RAG构建结果
        """
        try:
            from app.services.ragservice import RAGService
            
            # 创建本地RAG实例
            self.local_rag = RAGService(
                data_dir=str(self.local_data_dir / "rag"),
                use_vector_db=True
            )
            
            # 处理私有数据并构建知识库
            for item in self.private_data:
                if 'text' in item:
                    # 上传文档到RAG
                    self.local_rag.upload_document(
                        file_data=item['text'].encode(),
                        filename=item.get('filename', 'document.txt'),
                        metadata=item.get('metadata', {})
                    )
            
            logger.info(f"本地RAG知识库已构建,文档数: {len(self.local_rag.documents)}")
            
            return {
                'success': True,
                'documents_count': len(self.local_rag.documents),
                'index_size': len(self.local_rag.index)
            }
        except Exception as e:
            logger.error(f"构建本地RAG失败: {e}")
            raise
    
    def train_local_model(
        self,
        epochs: int = 5,
        learning_rate: float = 0.001
    ) -> Dict:
        """
        在本地私有数据上训练模型
        
        Args:
            epochs: 训练轮次
            learning_rate: 学习率
        
        Returns:
            训练结果
        """
        if not self.current_model:
            raise ValueError("未加载全局模型,请先下载")
        
        if not self.private_data:
            raise ValueError("未加载私有数据")
        
        logger.info(f"开始本地训练,数据量: {len(self.private_data)}, epochs: {epochs}")
        
        # 这里简化实现:实际应该调用真实的训练流程
        # 示例:使用通义千问API进行few-shot学习
        
        # 1. 提取训练样本
        training_samples = [
            {
                'input': item.get('input', ''),
                'output': item.get('output', '')
            }
            for item in self.private_data
            if 'input' in item and 'output' in item
        ]
        
        # 2. 模拟训练(实际应该调用模型训练API)
        trained_model = self._simulate_training(
            base_model=self.current_model,
            training_data=training_samples,
            epochs=epochs,
            learning_rate=learning_rate
        )
        
        # 3. 提取参数更新
        param_updates = self._extract_parameter_updates(
            old_model=self.current_model,
            new_model=trained_model
        )
        
        logger.info("本地训练完成")
        
        return {
            'success': True,
            'param_updates': param_updates,
            'training_samples': len(training_samples),
            'epochs': epochs
        }
    
    def _simulate_training(
        self,
        base_model: Dict,
        training_data: List[Dict],
        epochs: int,
        learning_rate: float
    ) -> Dict:
        """
        模拟训练过程
        
        实际实现应该:
        1. 加载基础模型
        2. 在本地数据上微调
        3. 返回更新后的模型
        
        这里简化为添加少量随机扰动
        """
        trained_model = {}
        for key, value in base_model.items():
            if isinstance(value, list):
                # 添加少量随机更新(实际应该是真实的梯度更新)
                update = np.random.randn(*np.array(value).shape) * learning_rate
                trained_model[key] = (np.array(value) + update).tolist()
            else:
                trained_model[key] = value
        
        return trained_model
    
    def _extract_parameter_updates(
        self,
        old_model: Dict,
        new_model: Dict
    ) -> Dict:
        """提取参数更新(新模型 - 旧模型)"""
        updates = {}
        for key in old_model.keys():
            if isinstance(old_model[key], list):
                updates[key] = (
                    np.array(new_model[key]) - np.array(old_model[key])
                ).tolist()
            else:
                updates[key] = new_model[key]
        
        return updates
    
    def upload_update(
        self,
        param_updates: Dict,
        metadata: Dict
    ) -> Dict:
        """
        上传参数更新到服务器
        
        Args:
            param_updates: 参数更新
            metadata: 元数据(训练信息)
        
        Returns:
            上传结果
        """
        try:
            # 1. 添加差分隐私
            from app.services.encryptionservice import encryption_service
            noisy_updates = encryption_service.add_differential_privacy(
                parameters=param_updates,
                epsilon=1.0,
                delta=1e-5
            )
            
            # 2. 加密参数
            encrypted_updates = encryption_service.encrypt_parameters(
                parameters=noisy_updates
            )
            
            # 3. 上传到服务器
            response = requests.post(
                f"{self.server_url}/ai/global-model/upload-update",
                json={
                    'client_id': self.client_id,
                    'encrypted_update': encrypted_updates,
                    'update_metadata': {
                        **metadata,
                        'data_size': len(self.private_data),
                        'upload_time': datetime.now().isoformat()
                    }
                }
            )
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"参数更新已上传,待聚合数: {result.get('pending_updates_count')}")
            
            return result
        except Exception as e:
            logger.error(f"上传参数更新失败: {e}")
            raise
    
    def sync_global_model(self) -> Dict:
        """
        同步全局模型
        
        检查并下载新版本的全局模型
        """
        try:
            # 下载最新全局模型
            new_model = self._download_model()
            
            if new_model['version_id'] != self.current_version:
                logger.info(f"全局模型已更新: {self.current_version} -> {new_model['version_id']}")
                return {
                    'updated': True,
                    'old_version': self.current_version,
                    'new_version': new_model['version_id']
                }
            else:
                logger.info("全局模型未更新")
                return {
                    'updated': False,
                    'version': self.current_version
                }
        except Exception as e:
            logger.error(f"同步全局模型失败: {e}")
            raise
    
    def complete_training_cycle(
        self,
        epochs: int = 5,
        learning_rate: float = 0.001
    ) -> Dict:
        """
        完成一个完整的训练周期
        
        1. 下载全局模型
        2. 本地训练
        3. 上传参数更新
        4. 等待聚合
        5. 同步新模型
        
        Args:
            epochs: 训练轮次
            learning_rate: 学习率
        
        Returns:
            训练周期结果
        """
        results = {}
        
        # 1. 同步全局模型
        sync_result = self.sync_global_model()
        results['sync'] = sync_result
        
        # 2. 本地训练
        train_result = self.train_local_model(epochs=epochs, learning_rate=learning_rate)
        results['training'] = train_result
        
        # 3. 上传参数更新
        upload_result = self.upload_update(
            param_updates=train_result['param_updates'],
            metadata={
                'epochs': epochs,
                'learning_rate': learning_rate,
                'training_samples': train_result['training_samples']
            }
        )
        results['upload'] = upload_result
        
        logger.info("训练周期完成")
        
        return {
            'success': True,
            'client_id': self.client_id,
            'cycle_results': results,
            'timestamp': datetime.now().isoformat()
        }

