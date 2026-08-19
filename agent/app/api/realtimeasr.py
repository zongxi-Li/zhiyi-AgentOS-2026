"""
实时语音识别API路由
支持WebSocket流式识别
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from typing import Optional
import json
import logging

from app.services.realtimeasservice import realtime_asr_service

router = APIRouter()
logger = logging.getLogger(__name__)


class StartRecognitionRequest(BaseModel):
    language: str = "zh-CN"
    sample_rate: int = 16000


@router.websocket("/realtime-asr/{session_id}")
async def websocket_realtime_asr(websocket: WebSocket, session_id: str):
    """
    WebSocket实时语音识别
    
    客户端发送：
    - {"type": "start", "language": "zh-CN", "sample_rate": 16000}
    - {"type": "audio", "data": base64_encoded_audio}
    - {"type": "end"}
    
    服务端返回：
    - {"type": "partial", "text": "部分识别结果", "confidence": 0.7}
    - {"type": "final", "text": "最终识别结果", "confidence": 0.9}
    - {"type": "error", "message": "错误信息"}
    """
    await websocket.accept()
    logger.info(f"WebSocket连接已建立: {session_id}")
    
    try:
        # 等待开始消息
        start_message = await websocket.receive_json()
        if start_message.get("type") != "start":
            await websocket.send_json({
                "type": "error",
                "message": "请先发送start消息"
            })
            return
        
        # 开始识别会话
        await realtime_asr_service.start_recognition_session(
            session_id=session_id,
            language=start_message.get("language", "zh-CN"),
            sample_rate=start_message.get("sample_rate", 16000)
        )
        
        await websocket.send_json({
            "type": "started",
            "session_id": session_id
        })
        
        # 处理音频流
        while True:
            try:
                # 接收消息
                message = await websocket.receive()
                
                if message["type"] == "websocket.receive":
                    if "text" in message:
                        # JSON消息
                        data = json.loads(message["text"])
                        msg_type = data.get("type")
                        
                        if msg_type == "end":
                            # 结束识别
                            result = await realtime_asr_service.end_recognition_session(session_id)
                            await websocket.send_json({
                                "type": "final",
                                "text": result["final_text"],
                                "all_results": result["all_results"]
                            })
                            break
                        
                        elif msg_type == "audio":
                            # 音频数据（base64编码）
                            import base64
                            audio_data = base64.b64decode(data.get("data", ""))
                            
                            # 处理音频块
                            recognition_result = await realtime_asr_service.process_audio_chunk(
                                session_id=session_id,
                                audio_chunk=audio_data
                            )
                            
                            # 发送部分结果
                            if recognition_result.get("partial_text"):
                                await websocket.send_json({
                                    "type": "partial",
                                    "text": recognition_result["partial_text"],
                                    "confidence": recognition_result.get("confidence", 0.7)
                                })
                            
                            # 发送最终结果
                            if recognition_result.get("is_final"):
                                await websocket.send_json({
                                    "type": "final",
                                    "text": recognition_result["final_text"],
                                    "confidence": recognition_result.get("confidence", 0.9)
                                })
                    
                    elif "bytes" in message:
                        # 二进制音频数据
                        audio_data = message["bytes"]
                        
                        # 处理音频块
                        recognition_result = await realtime_asr_service.process_audio_chunk(
                            session_id=session_id,
                            audio_chunk=audio_data
                        )
                        
                        # 发送识别结果
                        if recognition_result.get("partial_text"):
                            await websocket.send_json({
                                "type": "partial",
                                "text": recognition_result["partial_text"],
                                "confidence": recognition_result.get("confidence", 0.7)
                            })
                        
                        if recognition_result.get("is_final"):
                            await websocket.send_json({
                                "type": "final",
                                "text": recognition_result["final_text"],
                                "confidence": recognition_result.get("confidence", 0.9)
                            })
            
            except WebSocketDisconnect:
                logger.info(f"WebSocket断开连接: {session_id}")
                break
            except Exception as e:
                logger.error(f"处理WebSocket消息失败: {e}", exc_info=True)
                await websocket.send_json({
                    "type": "error",
                    "message": str(e)
                })
    
    except Exception as e:
        logger.error(f"WebSocket会话失败: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except:
            pass
    finally:
        # 清理会话
        if session_id in realtime_asr_service.active_sessions:
            try:
                await realtime_asr_service.end_recognition_session(session_id)
            except:
                pass


@router.post("/realtime-asr/start/{session_id}")
async def start_recognition_session(
    session_id: str,
    request: StartRecognitionRequest
):
    """开始识别会话（HTTP方式）"""
    try:
        await realtime_asr_service.start_recognition_session(
            session_id=session_id,
            language=request.language,
            sample_rate=request.sample_rate
        )
        return {
            "success": True,
            "session_id": session_id,
            "message": "识别会话已开始"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"开始识别会话失败: {str(e)}")


@router.post("/realtime-asr/process/{session_id}")
async def process_audio_chunk(
    session_id: str,
    audio_data: bytes
):
    """处理音频块（HTTP方式）"""
    try:
        result = await realtime_asr_service.process_audio_chunk(
            session_id=session_id,
            audio_chunk=audio_data
        )
        return {
            "success": True,
            "data": result
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理音频失败: {str(e)}")


@router.post("/realtime-asr/end/{session_id}")
async def end_recognition_session(session_id: str):
    """结束识别会话"""
    try:
        result = await realtime_asr_service.end_recognition_session(session_id)
        return {
            "success": True,
            "data": result
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"结束识别会话失败: {str(e)}")





