"""
多模态融合API路由
"""
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Dict, List, Optional
import base64
from app.services.multimodalservice import multimodal_fusion_service

router = APIRouter()


class MultimodalInput(BaseModel):
    type: str  # text/image/document/audio
    data: Optional[str] = None  # Base64编码的数据或文本内容
    filename: Optional[str] = None
    task: Optional[str] = "auto"  # 对于图像：ocr/caption/qa/auto


class MultimodalRequest(BaseModel):
    inputs: List[MultimodalInput]


@router.post("/multimodal/process")
async def process_multimodal(request: MultimodalRequest):
    """
    处理多模态输入
    
    示例：
    {
        "inputs": [
            {
                "type": "text",
                "data": "这是一段文本"
            },
            {
                "type": "image",
                "data": "base64_encoded_image_data",
                "task": "ocr"
            },
            {
                "type": "document",
                "data": "base64_encoded_document_data",
                "filename": "document.pdf"
            }
        ]
    }
    """
    try:
        # 转换输入格式
        inputs = []
        for input_item in request.inputs:
            input_data = input_item.data
            
            # 如果是Base64字符串，解码
            if input_item.type in ["image", "document", "audio"] and input_data:
                try:
                    input_data = base64.b64decode(input_data)
                except Exception as e:
                    raise ValueError(f"无效的Base64数据: {str(e)}")
            
            inputs.append({
                "type": input_item.type,
                "data": input_data,
                "filename": input_item.filename,
                "task": input_item.task or "auto"
            })
        
        # 处理多模态输入
        result = multimodal_fusion_service.process_multimodal_input(inputs)
        
        return {
            "success": True,
            "data": result
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"多模态处理失败: {str(e)}")


@router.post("/multimodal/image")
async def process_image(
    file: UploadFile = File(...),
    task: str = "auto",
    question: Optional[str] = None
):
    """
    处理图像上传（支持真实多模态API）
    
    支持任务类型：
    - ocr: 文字识别（使用通义千问qwen-vl）
    - caption: 图像描述（使用通义千问qwen-vl）
    - qa: 视觉问答（使用通义千问qwen-vl）
    - auto: 自动检测
    
    注意：需要配置DASHSCOPE_API_KEY或QWEN_API_KEY
    """
    try:
        image_data = await file.read()
        result = await multimodal_fusion_service.image_processor.process_image(
            image_data, 
            task,
            question=question
        )
        
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"图像处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"图像处理失败: {str(e)}")


@router.post("/multimodal/document")
async def process_document(
    file: UploadFile = File(...),
    extract_structure: bool = True
):
    """
    处理文档上传
    
    支持格式：txt, md, json, pdf, docx, doc
    """
    try:
        file_data = await file.read()
        filename = file.filename or "unknown"
        result = multimodal_fusion_service.document_processor.process_document(
            file_data,
            filename,
            extract_structure
        )
        
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文档处理失败: {str(e)}")





