"""
音频分析服务
使用librosa等专业库进行音频特征提取和分析
"""
import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
import io

logger = logging.getLogger(__name__)

# 尝试导入librosa，如果不可用则使用简化实现
try:
    import librosa
    LIBROSA_AVAILABLE = True
    logger.info("librosa已安装，使用专业音频分析")
except ImportError:
    LIBROSA_AVAILABLE = False
    logger.warning("librosa未安装，使用简化音频分析。安装: pip install librosa")


class AudioAnalysisService:
    """音频分析服务"""
    
    def __init__(self):
        """初始化音频分析服务"""
        self.sample_rate = 16000  # 默认采样率
        self.use_librosa = LIBROSA_AVAILABLE
    
    def analyze_audio(
        self,
        audio_data: bytes,
        sample_rate: int = 16000
    ) -> Dict:
        """
        分析音频特征
        
        Args:
            audio_data: 音频数据（字节流，PCM格式）
            sample_rate: 采样率
        
        Returns:
            包含音频特征的字典
        """
        try:
            if self.use_librosa:
                return self._analyze_with_librosa(audio_data, sample_rate)
            else:
                return self._analyze_simplified(audio_data, sample_rate)
        except Exception as e:
            logger.error(f"音频分析失败: {e}", exc_info=True)
            return self._analyze_simplified(audio_data, sample_rate)
    
    def _analyze_with_librosa(self, audio_data: bytes, sample_rate: int) -> Dict:
        """使用librosa进行专业音频分析"""
        try:
            # 将字节流转换为numpy数组
            audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
            audio_array = audio_array / 32768.0  # 归一化到[-1, 1]
            
            # 使用librosa提取特征
            # 1. 提取MFCC特征（Mel频率倒谱系数）
            mfccs = librosa.feature.mfcc(
                y=audio_array,
                sr=sample_rate,
                n_mfcc=13
            )
            
            # 2. 提取音调（pitch）
            pitches, magnitudes = librosa.piptrack(
                y=audio_array,
                sr=sample_rate
            )
            pitch_mean = np.mean(pitches[pitches > 0]) if np.any(pitches > 0) else 0.0
            
            # 3. 提取节奏特征（tempo）
            tempo, beats = librosa.beat.beat_track(
                y=audio_array,
                sr=sample_rate
            )
            
            # 4. 提取能量特征
            rms = librosa.feature.rms(y=audio_array)[0]
            energy_mean = np.mean(rms)
            energy_max = np.max(rms)
            
            # 5. 提取频谱特征
            spectral_centroids = librosa.feature.spectral_centroid(
                y=audio_array,
                sr=sample_rate
            )[0]
            spectral_rolloff = librosa.feature.spectral_rolloff(
                y=audio_array,
                sr=sample_rate
            )[0]
            
            # 6. 零交叉率（ZCR）
            zcr = librosa.feature.zero_crossing_rate(audio_array)[0]
            zcr_mean = np.mean(zcr)
            
            # 计算音频时长
            duration = len(audio_array) / sample_rate
            
            # 计算强度（基于RMS能量）
            intensity = min(1.0, energy_mean * 2.0)
            
            # 计算节奏感（基于tempo）
            rhythm = min(1.0, tempo / 120.0) if tempo > 0 else 0.5
            
            logger.debug(f"音频分析完成: 时长={duration:.2f}s, 音调={pitch_mean:.2f}Hz, 节奏={tempo:.2f}BPM")
            
            return {
                "intensity": float(intensity),
                "rhythm": float(rhythm),
                "pitch": float(pitch_mean),
                "tempo": float(tempo),
                "energy_mean": float(energy_mean),
                "energy_max": float(energy_max),
                "zcr": float(zcr_mean),
                "spectral_centroid": float(np.mean(spectral_centroids)),
                "spectral_rolloff": float(np.mean(spectral_rolloff)),
                "duration": float(duration),
                "sample_rate": sample_rate,
                "mfccs": mfccs.mean(axis=1).tolist(),  # MFCC特征的平均值
                "method": "librosa"
            }
        except Exception as e:
            logger.error(f"librosa音频分析失败: {e}", exc_info=True)
            return self._analyze_simplified(audio_data, sample_rate)
    
    def _analyze_simplified(self, audio_data: bytes, sample_rate: int) -> Dict:
        """简化音频分析（降级方案）"""
        try:
            # 将字节流转换为numpy数组
            audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
            audio_array = audio_array / 32768.0  # 归一化
            
            # 计算基本特征
            duration = len(audio_array) / sample_rate
            
            # RMS能量
            rms = np.sqrt(np.mean(audio_array ** 2))
            intensity = min(1.0, rms * 2.0)
            
            # 零交叉率（简化计算）
            zcr = np.mean(np.abs(np.diff(np.sign(audio_array)))) / 2.0
            rhythm = min(1.0, zcr * 10.0)
            
            return {
                "intensity": float(intensity),
                "rhythm": float(rhythm),
                "pitch": 0.0,
                "tempo": 0.0,
                "energy_mean": float(rms),
                "energy_max": float(np.max(np.abs(audio_array))),
                "zcr": float(zcr),
                "spectral_centroid": 0.0,
                "spectral_rolloff": 0.0,
                "duration": float(duration),
                "sample_rate": sample_rate,
                "mfccs": [],
                "method": "simplified"
            }
        except Exception as e:
            logger.error(f"简化音频分析失败: {e}", exc_info=True)
            return {
                "intensity": 0.7,
                "rhythm": 0.6,
                "pitch": 0.0,
                "tempo": 0.0,
                "duration": len(audio_data) / sample_rate,
                "method": "fallback"
            }
    
    def extract_phonemes_from_audio(
        self,
        audio_data: bytes,
        text: str,
        sample_rate: int = 16000
    ) -> List[Dict]:
        """
        从音频中提取音素序列（用于口型同步）
        
        Args:
            audio_data: 音频数据
            text: 对应文本
            sample_rate: 采样率
        
        Returns:
            音素序列（包含时间戳）
        """
        try:
            # 首先将文本转换为音素
            phonemes = self._text_to_phonemes(text)
            
            # 分析音频时长
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            duration = len(audio_array) / sample_rate
            
            # 计算每个音素的时长（简化：平均分配）
            phoneme_duration = duration / len(phonemes) if phonemes else 0.1
            
            # 如果使用librosa，可以更精确地分析音素边界
            if self.use_librosa:
                # 使用onset检测来更精确地定位音素边界
                audio_float = audio_array.astype(np.float32) / 32768.0
                onsets = librosa.onset.onset_detect(
                    y=audio_float,
                    sr=sample_rate,
                    units='time'
                )
                
                # 如果检测到onset，使用它们来分配音素时长
                if len(onsets) > 1:
                    onset_times = onsets.tolist()
                    onset_times.append(duration)  # 添加结束时间
                    
                    phoneme_list = []
                    for i, phoneme in enumerate(phonemes):
                        start_time = onset_times[i] if i < len(onset_times) else i * phoneme_duration
                        end_time = onset_times[i + 1] if i + 1 < len(onset_times) else start_time + phoneme_duration
                        
                        phoneme_list.append({
                            "phoneme": phoneme,
                            "start_time": float(start_time),
                            "end_time": float(end_time),
                            "duration": float(end_time - start_time)
                        })
                    return phoneme_list
            
            # 简化方案：平均分配
            phoneme_list = []
            for i, phoneme in enumerate(phonemes):
                start_time = i * phoneme_duration
                end_time = (i + 1) * phoneme_duration
                phoneme_list.append({
                    "phoneme": phoneme,
                    "start_time": float(start_time),
                    "end_time": float(end_time),
                    "duration": float(phoneme_duration)
                })
            
            return phoneme_list
            
        except Exception as e:
            logger.error(f"音素提取失败: {e}", exc_info=True)
            return []
    
    def _text_to_phonemes(self, text: str) -> List[str]:
        """
        文本转音素（增强实现）
        
        使用拼音转换库（如果可用）或简化实现
        """
        try:
            # 尝试使用pypinyin（如果可用）
            try:
                from pypinyin import lazy_pinyin, Style
                pinyin_list = lazy_pinyin(text, style=Style.TONE3)
                
                # 将拼音转换为音素（简化映射）
                phonemes = []
                for pinyin in pinyin_list:
                    # 提取声母和韵母
                    if pinyin:
                        # 简化处理：将拼音转换为音素
                        phonemes.append(pinyin)
                return phonemes if phonemes else list(text)
            except ImportError:
                # 如果没有pypinyin，使用简化实现
                logger.debug("pypinyin未安装，使用简化音素转换")
                return self._text_to_phonemes_simplified(text)
        except Exception as e:
            logger.warning(f"音素转换失败: {e}，使用简化实现")
            return self._text_to_phonemes_simplified(text)
    
    def _text_to_phonemes_simplified(self, text: str) -> List[str]:
        """简化音素转换"""
        phonemes = []
        for char in text:
            if char.isalpha():
                phonemes.append(char.lower())
            elif char in ["，", "。", "！", "？", ",", ".", "!", "?"]:
                phonemes.append("pause")
        return phonemes if phonemes else list(text)


# 全局音频分析服务实例
audio_analysis_service = AudioAnalysisService()

