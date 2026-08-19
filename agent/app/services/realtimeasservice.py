"""
实时语音识别服务
支持WebSocket流式语音识别
集成阿里云流式ASR API
"""
import logging
import asyncio
from typing import Dict, Optional, AsyncGenerator
from collections import deque
import numpy as np
from app.config import settings

logger = logging.getLogger(__name__)


class RealtimeASRService:
    """实时语音识别服务"""
    
    def __init__(self):
        self.active_sessions = {}  # 活跃的识别会话
        self.audio_buffer = {}  # 音频缓冲区
        self.buffer_size = 16000 * 2  # 2秒的音频缓冲区（16kHz采样率）
        self._speech_adapter = None  # 语音适配器（延迟初始化）
        
    async def start_recognition_session(
        self,
        session_id: str,
        language: str = "zh-CN",
        sample_rate: int = 16000
    ):
        """
        开始识别会话
        
        Args:
            session_id: 会话ID
            language: 语言类型
            sample_rate: 采样率
        """
        self.active_sessions[session_id] = {
            "language": language,
            "sample_rate": sample_rate,
            "status": "active",
            "partial_results": [],
            "final_results": []
        }
        
        self.audio_buffer[session_id] = deque(maxlen=self.buffer_size)
        
        logger.info(f"开始识别会话: {session_id}")
    
    async def process_audio_chunk(
        self,
        session_id: str,
        audio_chunk: bytes
    ) -> Dict:
        """
        处理音频块（流式识别）
        
        Args:
            session_id: 会话ID
            audio_chunk: 音频数据块
        
        Returns:
            识别结果（可能包含部分结果和最终结果）
        """
        if session_id not in self.active_sessions:
            raise ValueError(f"会话不存在: {session_id}")
        
        session = self.active_sessions[session_id]
        
        # 添加到缓冲区（确保是bytes类型）
        if isinstance(audio_chunk, bytes):
            self.audio_buffer[session_id].extend(audio_chunk)
        elif isinstance(audio_chunk, (list, tuple)):
            # 如果是列表或元组，直接extend
            self.audio_buffer[session_id].extend(bytes(audio_chunk))
        else:
            logger.warning(f"音频块类型错误: {type(audio_chunk)}")
        
        # 噪音过滤
        filtered_audio = self._filter_noise(audio_chunk, session["sample_rate"])
        
        # 流式识别（简化实现：实际应该调用流式ASR API）
        # 这里模拟流式识别过程
        partial_text = await self._streaming_recognize(filtered_audio, session)
        
        result = {
            "session_id": session_id,
            "partial_text": partial_text,
            "is_final": False,
            "confidence": 0.7
        }
        
        # 检查是否应该输出最终结果（例如：检测到静音或句子结束）
        if self._should_finalize(audio_chunk, session):
            final_text = await self._finalize_recognition(session_id, session)
            result["final_text"] = final_text
            result["is_final"] = True
            session["final_results"].append(final_text)
            session["partial_results"] = []  # 清空部分结果
        
        return result
    
    async def _streaming_recognize(self, audio_chunk: bytes, session: Dict) -> str:
        """
        流式识别（使用阿里云流式ASR API）
        
        注意：由于阿里云DashScope的流式ASR API可能需要WebSocket连接，
        这里使用批量识别方式，将音频块累积到一定大小后再识别
        """
        try:
            # 获取语音适配器
            speech_adapter = await self._get_speech_adapter()
            if not speech_adapter:
                logger.warning("语音适配器不可用，使用模拟识别")
                return "[部分识别结果：需要配置API密钥]"
            
            # 累积音频数据到缓冲区
            session_id = None
            for sid, sess in self.active_sessions.items():
                if sess == session:
                    session_id = sid
                    break
            
            if session_id and session_id in self.audio_buffer:
                # 获取累积的音频数据（最近2秒）
                try:
                    audio_bytes = bytes(self.audio_buffer[session_id])
                    accumulated_audio = audio_bytes[-32000:]  # 2秒@16kHz
                except Exception as e:
                    logger.error(f"转换音频缓冲区失败: {e}")
                    return ""
                
                # 如果音频数据足够大，进行识别
                if len(accumulated_audio) >= 16000:  # 至少1秒的音频
                    try:
                        # 调用完整识别API（因为流式API可能需要WebSocket）
                        result = await speech_adapter.recognize_speech(
                            audio_data=accumulated_audio,
                            language=session.get("language", "zh-CN"),
                            format="pcm",
                            sample_rate=session.get("sample_rate", 16000)
                        )
                        
                        if result.get("success"):
                            recognized_text = result.get("text", "")
                            if recognized_text:
                                # 更新部分结果
                                if recognized_text not in session.get("partial_results", []):
                                    session.setdefault("partial_results", []).append(recognized_text)
                                return recognized_text
                    except Exception as e:
                        logger.warning(f"流式识别API调用失败: {e}")
            
            return "[识别中...]"
            
        except Exception as e:
            logger.error(f"流式识别异常: {e}", exc_info=True)
            return "[识别失败]"
    
    def _should_finalize(self, audio_chunk: bytes, session: Dict) -> bool:
        """判断是否应该输出最终结果"""
        # 检测静音或句子结束
        # 简化实现：检查音频能量
        audio_energy = self._calculate_energy(audio_chunk)
        
        # 如果音频能量很低，可能是静音
        if audio_energy < 0.01:
            # 检查是否已经有部分结果
            if session.get("partial_results"):
                return True
        
        return False
    
    def _calculate_energy(self, audio_data: bytes) -> float:
        """计算音频能量"""
        try:
            # 将字节转换为numpy数组
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            # 计算RMS能量
            energy = np.sqrt(np.mean(audio_array**2))
            # 归一化
            normalized_energy = energy / 32768.0
            return normalized_energy
        except Exception as e:
            logger.error(f"计算音频能量失败: {e}")
            return 0.0
    
    async def _finalize_recognition(self, session_id: str, session: Dict) -> str:
        """完成识别，输出最终结果"""
        # 合并所有部分结果
        if session.get("partial_results"):
            final_text = " ".join(session["partial_results"])
        else:
            # 如果没有部分结果，进行完整识别
            audio_data = bytes(self.audio_buffer[session_id])
            final_text = await self._full_recognize(audio_data, session)
        
        return final_text
    
    async def _full_recognize(self, audio_data: bytes, session: Dict) -> str:
        """
        完整音频识别（使用阿里云ASR API）
        
        支持重试机制，最多重试3次
        """
        max_retries = 3
        retry_delay = 0.5  # 重试延迟（秒）
        
        for attempt in range(max_retries):
            try:
                # 获取语音适配器
                speech_adapter = await self._get_speech_adapter()
                if not speech_adapter:
                    logger.warning("语音适配器不可用，使用模拟识别")
                    return "[完整识别结果：需要配置API密钥]"
                
                # 检查音频数据大小
                if len(audio_data) < 1000:  # 音频数据太小
                    logger.warning("音频数据太小，无法识别")
                    return "[音频数据不足]"
                
                # 调用完整识别API
                result = await speech_adapter.recognize_speech(
                    audio_data=audio_data,
                    language=session.get("language", "zh-CN"),
                    format="pcm",
                    sample_rate=session.get("sample_rate", 16000)
                )
                
                if result.get("success"):
                    recognized_text = result.get("text", "")
                    if recognized_text:
                        logger.info(f"完整识别成功: {len(recognized_text)} 字符")
                        return recognized_text
                    else:
                        logger.warning("识别结果为空")
                        return "[识别结果为空]"
                else:
                    error_msg = result.get("error", "未知错误")
                    logger.warning(f"完整识别失败: {error_msg}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay * (attempt + 1))
                        continue
                    return f"[识别失败: {error_msg}]"
                    
            except Exception as e:
                logger.error(f"完整识别异常 (尝试 {attempt + 1}/{max_retries}): {e}", exc_info=True)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (attempt + 1))
                    continue
                return f"[识别失败: {str(e)}]"
        
        return "[识别失败: 超过最大重试次数]"
    
    async def _get_speech_adapter(self):
        """获取语音适配器（延迟初始化）"""
        if self._speech_adapter is None:
            try:
                # 获取API密钥
                api_key = getattr(settings, 'DASHSCOPE_API_KEY', '') or getattr(settings, 'QWEN_API_KEY', '')
                if api_key:
                    from app.ai_engine.speechadapter import SpeechAdapter
                    self._speech_adapter = SpeechAdapter(api_key)
                    logger.info("实时语音识别服务已初始化语音适配器")
                else:
                    logger.warning("未配置API密钥，实时语音识别将使用模拟模式")
                    return None
            except Exception as e:
                logger.error(f"初始化语音适配器失败: {e}", exc_info=True)
                return None
        return self._speech_adapter
    
    def _filter_noise(self, audio_data: bytes, sample_rate: int) -> bytes:
        """
        噪音过滤
        
        Args:
            audio_data: 原始音频数据
            sample_rate: 采样率
        
        Returns:
            过滤后的音频数据
        """
        try:
            # 转换为numpy数组
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            # 简单的噪音过滤：低通滤波
            # 实际应该使用更专业的降噪算法（如谱减法、维纳滤波等）
            filtered = self._low_pass_filter(audio_array, sample_rate, cutoff=4000)
            
            # 转回字节
            filtered_bytes = filtered.astype(np.int16).tobytes()
            
            return filtered_bytes
        except Exception as e:
            logger.error(f"噪音过滤失败: {e}")
            return audio_data
    
    def _low_pass_filter(self, audio_array: np.ndarray, sample_rate: int, cutoff: int = 4000) -> np.ndarray:
        """低通滤波器（简化实现）"""
        # 简化实现：实际应该使用scipy.signal等专业库
        # 这里使用简单的移动平均作为低通滤波
        window_size = max(1, int(sample_rate / cutoff))
        if window_size > len(audio_array):
            return audio_array
        
        # 移动平均
        filtered = np.convolve(audio_array, np.ones(window_size) / window_size, mode='same')
        return filtered.astype(np.int16)
    
    async def end_recognition_session(self, session_id: str) -> Dict:
        """
        结束识别会话
        
        Args:
            session_id: 会话ID
        
        Returns:
            最终识别结果
        """
        if session_id not in self.active_sessions:
            raise ValueError(f"会话不存在: {session_id}")
        
        session = self.active_sessions[session_id]
        
        # 获取最终结果
        final_text = await self._finalize_recognition(session_id, session)
        
        # 清理会话
        del self.active_sessions[session_id]
        if session_id in self.audio_buffer:
            del self.audio_buffer[session_id]
        
        logger.info(f"结束识别会话: {session_id}")
        
        return {
            "session_id": session_id,
            "final_text": final_text,
            "all_results": session.get("final_results", [])
        }


# 全局实时ASR服务实例
realtime_asr_service = RealtimeASRService()





