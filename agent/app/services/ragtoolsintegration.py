"""
RAG工具集成服务
集成 ragflow、qanything、fastgpt 等RAG工具
提供统一的接口和智能选择策略
"""
import logging
from typing import Dict, Optional, List, Any
from pathlib import Path
import httpx

logger = logging.getLogger(__name__)


class RAGToolsIntegration:
    """RAG工具集成服务"""
    
    def __init__(self):
        """初始化RAG工具集成服务"""
        self.available_tools = self._detect_available_tools()
        self.selected_tool = self._select_default_tool()
        
        logger.info(f"RAG工具集成服务初始化完成")
        logger.info(f"可用工具: {', '.join(self.available_tools.keys())}")
        logger.info(f"默认工具: {self.selected_tool}")
    
    def _detect_available_tools(self) -> Dict[str, Dict]:
        """检测可用的RAG工具"""
        tools = {}
        
        # 1. 检测 RagFlow
        try:
            import ragflow
            tools['ragflow'] = {
                'available': True,
                'library': 'ragflow',
                'version': getattr(ragflow, '__version__', 'unknown')
            }
            logger.debug("RagFlow 可用")
        except ImportError:
            tools['ragflow'] = {
                'available': False,
                'install_cmd': 'pip install ragflow'
            }
            logger.debug("RagFlow 不可用，可运行: pip install ragflow")
        
        # 2. 检测 QAnything
        try:
            import qanything
            tools['qanything'] = {
                'available': True,
                'library': 'qanything',
                'version': getattr(qanything, '__version__', 'unknown')
            }
            logger.debug("QAnything 可用")
        except ImportError:
            tools['qanything'] = {
                'available': False,
                'install_cmd': 'pip install qanything'
            }
            logger.debug("QAnything 不可用，可运行: pip install qanything")
        
        # 3. 检测 FastGPT（通常作为服务运行，通过API访问）
        try:
            # FastGPT通常是服务部署，检测配置
            from app.config import settings
            fastgpt_url = getattr(settings, 'FASTGPT_API_URL', None)
            fastgpt_key = getattr(settings, 'FASTGPT_API_KEY', None)
            
            if fastgpt_url and fastgpt_key:
                tools['fastgpt'] = {
                    'available': True,
                    'api_url': fastgpt_url,
                    'type': 'api_service'
                }
                logger.debug("FastGPT API 已配置")
            else:
                tools['fastgpt'] = {
                    'available': False,
                    'type': 'api_service',
                    'note': '需要配置 FASTGPT_API_URL 和 FASTGPT_API_KEY'
                }
                logger.debug("FastGPT API 未配置")
        except Exception as e:
            tools['fastgpt'] = {
                'available': False,
                'error': str(e)
            }
        
        # 4. 内置RAG服务（作为回退选项）
        tools['builtin'] = {
            'available': True,
            'library': 'builtin',
            'note': '内置RAG服务（ChromaDB + Embedding）'
        }
        
        return tools
    
    def _select_default_tool(self) -> str:
        """选择默认RAG工具（优先级：ragflow > qanything > fastgpt > builtin）"""
        if self.available_tools.get('ragflow', {}).get('available'):
            return 'ragflow'
        elif self.available_tools.get('qanything', {}).get('available'):
            return 'qanything'
        elif self.available_tools.get('fastgpt', {}).get('available'):
            return 'fastgpt'
        else:
            return 'builtin'
    
    async def search(
        self,
        query: str,
        top_k: int = 5,
        tool: Optional[str] = None,
        role_id: Optional[str] = None,
        **kwargs
    ) -> List[Dict]:
        """
        使用RAG工具搜索
        
        Args:
            query: 查询文本
            top_k: 返回结果数量
            tool: 指定使用的工具（ragflow/qanything/fastgpt/builtin）
            role_id: 角色ID（用于过滤）
            **kwargs: 其他参数
        
        Returns:
            搜索结果列表
        """
        selected_tool = tool or self.selected_tool
        
        try:
            if selected_tool == 'ragflow' and self.available_tools['ragflow']['available']:
                return await self._search_ragflow(query, top_k, role_id, **kwargs)
            elif selected_tool == 'qanything' and self.available_tools['qanything']['available']:
                return await self._search_qanything(query, top_k, role_id, **kwargs)
            elif selected_tool == 'fastgpt' and self.available_tools['fastgpt']['available']:
                return await self._search_fastgpt(query, top_k, role_id, **kwargs)
            else:
                # 回退到内置RAG服务
                return await self._search_builtin(query, top_k, role_id, **kwargs)
        except Exception as e:
            logger.error(f"RAG搜索失败({selected_tool}): {e}", exc_info=True)
            # 降级到内置服务
            if selected_tool != 'builtin':
                logger.warning(f"降级到内置RAG服务")
                return await self._search_builtin(query, top_k, role_id, **kwargs)
            return []
    
    async def _search_ragflow(
        self,
        query: str,
        top_k: int,
        role_id: Optional[str] = None,
        **kwargs
    ) -> List[Dict]:
        """使用RagFlow搜索"""
        try:
            import ragflow
            
            # RagFlow的使用方法（根据实际API调整）
            # 假设ragflow提供了search方法
            results = ragflow.search(
                query=query,
                top_k=top_k,
                collection=f"role_{role_id}" if role_id else "default",
                **kwargs
            )
            
            # 转换结果格式
            formatted_results = []
            for result in results:
                formatted_results.append({
                    "doc_id": result.get('id', ''),
                    "filename": result.get('filename', ''),
                    "score": result.get('score', 0.0),
                    "content": result.get('content', ''),
                    "metadata": result.get('metadata', {}),
                    "role_id": role_id,
                    "method": "ragflow"
                })
            
            logger.debug(f"RagFlow搜索完成: {len(formatted_results)} 个结果")
            return formatted_results
        except Exception as e:
            logger.error(f"RagFlow搜索失败: {e}")
            raise
    
    async def _search_qanything(
        self,
        query: str,
        top_k: int,
        role_id: Optional[str] = None,
        **kwargs
    ) -> List[Dict]:
        """使用QAnything搜索"""
        try:
            import qanything
            
            # QAnything的使用方法（根据实际API调整）
            results = qanything.search(
                query=query,
                top_k=top_k,
                filter_metadata={'role_id': role_id} if role_id else None,
                **kwargs
            )
            
            # 转换结果格式
            formatted_results = []
            for result in results:
                formatted_results.append({
                    "doc_id": result.get('id', ''),
                    "filename": result.get('filename', ''),
                    "score": result.get('score', 0.0),
                    "content": result.get('content', ''),
                    "metadata": result.get('metadata', {}),
                    "role_id": role_id,
                    "method": "qanything"
                })
            
            logger.debug(f"QAnything搜索完成: {len(formatted_results)} 个结果")
            return formatted_results
        except Exception as e:
            logger.error(f"QAnything搜索失败: {e}")
            raise
    
    async def _search_fastgpt(
        self,
        query: str,
        top_k: int,
        role_id: Optional[str] = None,
        **kwargs
    ) -> List[Dict]:
        """使用FastGPT API搜索"""
        try:
            from app.config import settings
            api_url = getattr(settings, 'FASTGPT_API_URL', '')
            api_key = getattr(settings, 'FASTGPT_API_KEY', '')
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{api_url}/api/v1/search",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "query": query,
                        "top_k": top_k,
                        "role_id": role_id,
                        **kwargs
                    }
                )
                
                response.raise_for_status()
                result_data = response.json()
                
                # 转换结果格式
                results = result_data.get('results', [])
                formatted_results = []
                for result in results:
                    formatted_results.append({
                        "doc_id": result.get('id', ''),
                        "filename": result.get('filename', ''),
                        "score": result.get('score', 0.0),
                        "content": result.get('content', ''),
                        "metadata": result.get('metadata', {}),
                        "role_id": role_id,
                        "method": "fastgpt"
                    })
                
                logger.debug(f"FastGPT搜索完成: {len(formatted_results)} 个结果")
                return formatted_results
        except Exception as e:
            logger.error(f"FastGPT搜索失败: {e}")
            raise
    
    async def _search_builtin(
        self,
        query: str,
        top_k: int,
        role_id: Optional[str] = None,
        **kwargs
    ) -> List[Dict]:
        """使用内置RAG服务搜索"""
        try:
            from app.services.ragservice import RAGService
            
            # 创建或获取RAG服务实例
            rag_service = RAGService(use_vector_db=True)
            
            # 执行搜索
            results = rag_service.search(
                query=query,
                top_k=top_k,
                role_id=role_id,
                use_vector_search=True,
                **kwargs
            )
            
            logger.debug(f"内置RAG搜索完成: {len(results)} 个结果")
            return results
        except Exception as e:
            logger.error(f"内置RAG搜索失败: {e}")
            raise
    
    async def upload_document(
        self,
        file_data: bytes,
        filename: str,
        metadata: Optional[Dict] = None,
        role_id: Optional[str] = None,
        tool: Optional[str] = None
    ) -> str:
        """
        上传文档到知识库
        
        Args:
            file_data: 文件数据
            filename: 文件名
            metadata: 元数据
            role_id: 角色ID
            tool: 指定使用的工具
        
        Returns:
            文档ID
        """
        selected_tool = tool or self.selected_tool
        
        try:
            if selected_tool == 'ragflow' and self.available_tools['ragflow']['available']:
                return await self._upload_ragflow(file_data, filename, metadata, role_id)
            elif selected_tool == 'qanything' and self.available_tools['qanything']['available']:
                return await self._upload_qanything(file_data, filename, metadata, role_id)
            elif selected_tool == 'fastgpt' and self.available_tools['fastgpt']['available']:
                return await self._upload_fastgpt(file_data, filename, metadata, role_id)
            else:
                return await self._upload_builtin(file_data, filename, metadata, role_id)
        except Exception as e:
            logger.error(f"文档上传失败({selected_tool}): {e}", exc_info=True)
            # 降级到内置服务
            if selected_tool != 'builtin':
                logger.warning(f"降级到内置RAG服务")
                return await self._upload_builtin(file_data, filename, metadata, role_id)
            raise
    
    async def _upload_ragflow(
        self,
        file_data: bytes,
        filename: str,
        metadata: Optional[Dict],
        role_id: Optional[str]
    ) -> str:
        """上传到RagFlow"""
        import ragflow
        
        doc_id = ragflow.upload(
            file_data=file_data,
            filename=filename,
            collection=f"role_{role_id}" if role_id else "default",
            metadata=metadata or {}
        )
        
        logger.info(f"文档已上传到RagFlow: {filename} (ID: {doc_id})")
        return doc_id
    
    async def _upload_qanything(
        self,
        file_data: bytes,
        filename: str,
        metadata: Optional[Dict],
        role_id: Optional[str]
    ) -> str:
        """上传到QAnything"""
        import qanything
        
        doc_metadata = metadata or {}
        if role_id:
            doc_metadata['role_id'] = role_id
        
        doc_id = qanything.upload(
            file_data=file_data,
            filename=filename,
            metadata=doc_metadata
        )
        
        logger.info(f"文档已上传到QAnything: {filename} (ID: {doc_id})")
        return doc_id
    
    async def _upload_fastgpt(
        self,
        file_data: bytes,
        filename: str,
        metadata: Optional[Dict],
        role_id: Optional[str]
    ) -> str:
        """上传到FastGPT"""
        from app.config import settings
        api_url = getattr(settings, 'FASTGPT_API_URL', '')
        api_key = getattr(settings, 'FASTGPT_API_KEY', '')
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {'file': (filename, file_data)}
            data = {
                'metadata': metadata or {},
                'role_id': role_id or ''
            }
            
            response = await client.post(
                f"{api_url}/api/v1/upload",
                headers={"Authorization": f"Bearer {api_key}"},
                files=files,
                data=data
            )
            
            response.raise_for_status()
            result = response.json()
            doc_id = result.get('doc_id', '')
            
            logger.info(f"文档已上传到FastGPT: {filename} (ID: {doc_id})")
            return doc_id
    
    async def _upload_builtin(
        self,
        file_data: bytes,
        filename: str,
        metadata: Optional[Dict],
        role_id: Optional[str]
    ) -> str:
        """上传到内置RAG服务"""
        from app.services.ragservice import RAGService
        
        rag_service = RAGService(use_vector_db=True)
        doc_id = rag_service.upload_document(
            file_data=file_data,
            filename=filename,
            metadata=metadata,
            role_id=role_id
        )
        
        logger.info(f"文档已上传到内置RAG服务: {filename} (ID: {doc_id})")
        return doc_id


# 全局RAG工具集成服务实例
rag_tools_integration = RAGToolsIntegration()

