"""
增强文档处理服务
集成easydoc、mineru等专业文档处理工具
"""
import logging
import io
from typing import Dict, Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)


class EnhancedDocumentProcessor:
    """增强文档处理器"""
    
    def __init__(self):
        self.supported_formats = {
            '.txt', '.md', '.json',
            '.pdf', '.docx', '.doc',
            '.xlsx', '.xls', '.pptx', '.ppt',
            '.html', '.htm', '.xml'
        }
        
        # 检查可用的文档处理库
        self.has_pypdf2 = self._check_library('PyPDF2')
        self.has_docx = self._check_library('docx')
        self.has_openpyxl = self._check_library('openpyxl')
        self.has_pandas = self._check_library('pandas')
        self.has_easydoc = self._check_library('easydoc')
        self.has_mineru = self._check_library('mineru')
    
    def _check_library(self, library_name: str) -> bool:
        """检查库是否可用"""
        try:
            __import__(library_name.lower().replace('-', '_'))
            return True
        except ImportError:
            return False
    
    def extract_text(
        self,
        file_data: bytes,
        filename: str,
        use_enhanced: bool = True
    ) -> Dict:
        """
        提取文档文本（增强版）
        
        Args:
            file_data: 文件数据
            filename: 文件名
            use_enhanced: 是否使用增强工具（easydoc、mineru）
        
        Returns:
            提取结果
        """
        file_ext = Path(filename).suffix.lower()
        
        if file_ext not in self.supported_formats:
            return {
                "success": False,
                "error": f"不支持的文件格式: {file_ext}",
                "text": ""
            }
        
        # 优先使用专业工具
        if use_enhanced:
            if file_ext == '.pdf' and self.has_mineru:
                return self._extract_with_mineru(file_data, filename)
            elif file_ext in ['.pdf', '.docx', '.doc'] and self.has_easydoc:
                return self._extract_with_easydoc(file_data, filename)
        
        # 回退到基础处理
        return self._extract_basic(file_data, filename, file_ext)
    
    def _extract_with_mineru(self, file_data: bytes, filename: str) -> Dict:
        """使用mineru提取PDF文本"""
        try:
            # mineru主要用于PDF解析
            # 实际使用时需要安装: pip install mineru
            import mineru
            
            # 创建临时文件
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                tmp_file.write(file_data)
                tmp_path = tmp_file.name
            
            # 使用mineru解析
            result = mineru.extract_text(tmp_path)
            
            # 清理临时文件
            Path(tmp_path).unlink()
            
            return {
                "success": True,
                "text": result.get("text", ""),
                "metadata": result.get("metadata", {}),
                "method": "mineru"
            }
        except ImportError:
            logger.warning("mineru未安装，使用基础PDF解析")
            return self._extract_basic(file_data, filename, '.pdf')
        except Exception as e:
            logger.error(f"mineru提取失败: {e}")
            return self._extract_basic(file_data, filename, '.pdf')
    
    def _extract_with_easydoc(self, file_data: bytes, filename: str) -> Dict:
        """使用easydoc提取文档文本"""
        try:
            # easydoc用于文档解析
            # 实际使用时需要安装: pip install easydoc
            import easydoc
            
            file_ext = Path(filename).suffix.lower()
            
            if file_ext == '.pdf':
                result = easydoc.extract_from_pdf(file_data)
            elif file_ext in ['.docx', '.doc']:
                result = easydoc.extract_from_word(file_data)
            else:
                return self._extract_basic(file_data, filename, file_ext)
            
            return {
                "success": True,
                "text": result.get("text", ""),
                "structure": result.get("structure", {}),
                "metadata": result.get("metadata", {}),
                "method": "easydoc"
            }
        except ImportError:
            logger.warning("easydoc未安装，使用基础解析")
            return self._extract_basic(file_data, filename, Path(filename).suffix.lower())
        except Exception as e:
            logger.error(f"easydoc提取失败: {e}")
            return self._extract_basic(file_data, filename, Path(filename).suffix.lower())
    
    def _extract_basic(self, file_data: bytes, filename: str, file_ext: str) -> Dict:
        """基础文本提取"""
        try:
            if file_ext in ['.txt', '.md']:
                text = file_data.decode('utf-8')
            elif file_ext == '.json':
                import json
                data = json.loads(file_data.decode('utf-8'))
                text = json.dumps(data, ensure_ascii=False)
            elif file_ext == '.pdf' and self.has_pypdf2:
                from PyPDF2 import PdfReader
                reader = PdfReader(io.BytesIO(file_data))
                text = "\n".join([page.extract_text() for page in reader.pages])
            elif file_ext == '.docx' and self.has_docx:
                from docx import Document
                doc = Document(io.BytesIO(file_data))
                text = "\n".join([para.text for para in doc.paragraphs])
            elif file_ext in ['.xlsx', '.xls'] and self.has_pandas:
                import pandas as pd
                df = pd.read_excel(io.BytesIO(file_data))
                text = df.to_string()
            elif file_ext in ['.html', '.htm']:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(file_data, 'html.parser')
                text = soup.get_text()
            else:
                text = f"[文档内容: {filename}，格式: {file_ext}]"
                logger.warning(f"使用占位符文本: {filename}")
            
            return {
                "success": True,
                "text": text,
                "method": "basic"
            }
        except Exception as e:
            logger.error(f"基础文本提取失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "text": ""
            }
    
    def extract_structure(self, file_data: bytes, filename: str) -> Dict:
        """提取文档结构"""
        file_ext = Path(filename).suffix.lower()
        
        try:
            if file_ext == '.pdf' and self.has_mineru:
                result = self._extract_with_mineru(file_data, filename)
                return result.get("structure", {})
            elif file_ext in ['.pdf', '.docx', '.doc'] and self.has_easydoc:
                result = self._extract_with_easydoc(file_data, filename)
                return result.get("structure", {})
            else:
                # 基础结构提取
                text_result = self._extract_basic(file_data, filename, file_ext)
                text = text_result.get("text", "")
                
                # 提取标题、段落等
                lines = text.split('\n')
                structure = {
                    "title": lines[0] if lines else "",
                    "paragraphs": [line for line in lines if line.strip()][:10],
                    "total_lines": len(lines)
                }
                
                return structure
        except Exception as e:
            logger.error(f"提取文档结构失败: {e}")
            return {}


# 全局增强文档处理器实例
enhanced_document_processor = EnhancedDocumentProcessor()





