"""
语音情感识别服务
从音频中提取特征并识别情感
"""
import logging
import numpy as np
from typing import Dict, Optional
import struct

logger = logging.getLogger(__name__)


class VoiceEmotionRecognizer:
    """语音情感识别器"""
    
    def __init__(self):
        # 情感特征阈值
        self.emotion_thresholds = {
            "happy": {
                "pitch_range": (0.6, 1.0),
                "energy_range": (0.6, 1.0),
                "tempo_range": (0.5, 1.0)
            },
            "sad": {
                "pitch_range": (0.0, 0.4),
                "energy_range": (0.0, 0.4),
                "tempo_range": (0.0, 0.5)
            },
            "angry": {
                "pitch_range": (0.5, 1.0),
                "energy_range": (0.7, 1.0),
                "tempo_range": (0.6, 1.0)
            },
            "anxious": {
                "pitch_range": (0.6, 1.0),
                "energy_range": (0.3, 0.6),
                "tempo_range": (0.5, 0.8)
            },
            "excited": {
                "pitch_range": (0.7, 1.0),
                "energy_range": (0.7, 1.0),
                "tempo_range": (0.7, 1.0)
            },
            "calm": {
                "pitch_range": (0.4, 0.6),
                "energy_range": (0.3, 0.6),
                "tempo_range": (0.3, 0.6)
            }
        }
    
    def recognize_emotion(self, audio_data: bytes, sample_rate: int = 16000) -> Dict:
        """
        从音频数据识别情感
        
        Args:
            audio_data: 音频字节数据
            sample_rate: 采样率（默认16kHz）
        
        Returns:
            情感识别结果
        """
        try:
            # 提取音频特征
            features = self._extract_audio_features(audio_data, sample_rate)
            
            # 识别情感
            emotion = self._classify_emotion(features)
            
            return {
                "emotion": emotion["type"],
                "intensity": emotion["intensity"],
                "confidence": emotion["confidence"],
                "features": features,
                "details": emotion
            }
        except Exception as e:
            logger.error(f"语音情感识别失败: {e}", exc_info=True)
            return {
                "emotion": "neutral",
                "intensity": 0.5,
                "confidence": 0.5,
                "error": str(e)
            }
    
    def _extract_audio_features(self, audio_data: bytes, sample_rate: int) -> Dict:
        """提取音频特征"""
        try:
            # 将字节转换为numpy数组（假设16位PCM）
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            if len(audio_array) == 0:
                return self._default_features()
            
            # 归一化到[-1, 1]
            audio_float = audio_array.astype(np.float32) / 32768.0
            
            # 计算基本特征
            features = {
                "pitch": self._calculate_pitch(audio_float, sample_rate),
                "energy": self._calculate_energy(audio_float),
                "tempo": self._calculate_tempo(audio_float, sample_rate),
                "zero_crossing_rate": self._calculate_zcr(audio_float),
                "spectral_centroid": self._calculate_spectral_centroid(audio_float, sample_rate),
                "duration": len(audio_float) / sample_rate
            }
            
            return features
        except Exception as e:
            logger.error(f"提取音频特征失败: {e}")
            return self._default_features()
    
    def _calculate_pitch(self, audio: np.ndarray, sample_rate: int) -> float:
        """计算音调（基频，使用librosa）"""
        try:
            # 尝试使用librosa进行专业音调检测
            try:
                import librosa
                pitches, magnitudes = librosa.piptrack(y=audio, sr=sample_rate)
                pitch_mean = np.mean(pitches[pitches > 0]) if np.any(pitches > 0) else 0.0
                # 归一化到[0, 1]
                normalized_pitch = min(pitch_mean / 1000.0, 1.0) if pitch_mean > 0 else 0.5
                return normalized_pitch
            except ImportError:
                # 降级到简化实现
                zcr = self._calculate_zcr(audio)
                pitch = min(zcr * 2.0, 1.0)
                return pitch
        except:
            return 0.5
    
    def _calculate_energy(self, audio: np.ndarray) -> float:
        """计算音频能量（RMS）"""
        try:
            rms = np.sqrt(np.mean(audio**2))
            # 归一化到[0, 1]
            energy = min(rms * 2.0, 1.0)
            return energy
        except:
            return 0.5
    
    def _calculate_tempo(self, audio: np.ndarray, sample_rate: int) -> float:
        """计算节奏（基于能量变化）"""
        try:
            # 计算短时能量
            frame_size = int(sample_rate * 0.025)  # 25ms帧
            num_frames = len(audio) // frame_size
            
            if num_frames < 2:
                return 0.5
            
            energies = []
            for i in range(num_frames):
                frame = audio[i * frame_size:(i + 1) * frame_size]
                energy = np.sqrt(np.mean(frame**2))
                energies.append(energy)
            
            # 计算能量变化率（节奏指标）
            energy_variance = np.var(energies)
            tempo = min(energy_variance * 10.0, 1.0)
            
            return tempo
        except:
            return 0.5
    
    def _calculate_zcr(self, audio: np.ndarray) -> float:
        """计算零交叉率"""
        try:
            if len(audio) < 2:
                return 0.0
            
            sign_changes = np.sum(np.diff(np.sign(audio)) != 0)
            zcr = sign_changes / len(audio)
            
            return min(zcr, 1.0)
        except:
            return 0.0
    
    def _calculate_spectral_centroid(self, audio: np.ndarray, sample_rate: int) -> float:
        """计算频谱质心（使用librosa）"""
        try:
            # 尝试使用librosa进行专业频谱分析
            try:
                import librosa
                spectral_centroids = librosa.feature.spectral_centroid(y=audio, sr=sample_rate)[0]
                centroid_mean = np.mean(spectral_centroids)
                # 归一化到[0, 1]
                normalized_centroid = min(centroid_mean / 5000.0, 1.0)
                return normalized_centroid
            except ImportError:
                # 降级到简化实现：使用FFT计算频谱
                fft = np.fft.fft(audio)
                magnitude = np.abs(fft)
                
                # 计算频率
                frequencies = np.fft.fftfreq(len(audio), 1.0 / sample_rate)
                
                # 只考虑正频率
                positive_freq_idx = frequencies >= 0
                frequencies = frequencies[positive_freq_idx]
                magnitude = magnitude[positive_freq_idx]
                
                if np.sum(magnitude) == 0:
                    return 0.5
            
            # 计算加权平均频率
            spectral_centroid = np.sum(frequencies * magnitude) / np.sum(magnitude)
            
            # 归一化到[0, 1]（假设最大频率为sample_rate/2）
            normalized = min(spectral_centroid / (sample_rate / 2), 1.0)
            
            return normalized
        except:
            return 0.5
    
    def _classify_emotion(self, features: Dict) -> Dict:
        """根据特征分类情感"""
        pitch = features.get("pitch", 0.5)
        energy = features.get("energy", 0.5)
        tempo = features.get("tempo", 0.5)
        
        emotion_scores = {}
        
        # 计算每个情感的匹配分数
        for emotion_type, thresholds in self.emotion_thresholds.items():
            pitch_range = thresholds["pitch_range"]
            energy_range = thresholds["energy_range"]
            tempo_range = thresholds["tempo_range"]
            
            # 计算匹配度
            pitch_match = self._range_match(pitch, pitch_range)
            energy_match = self._range_match(energy, energy_range)
            tempo_match = self._range_match(tempo, tempo_range)
            
            # 综合得分
            score = (pitch_match + energy_match + tempo_match) / 3.0
            emotion_scores[emotion_type] = score
        
        # 选择得分最高的情感
        max_emotion = max(emotion_scores, key=emotion_scores.get)
        max_score = emotion_scores[max_emotion]
        
        # 计算强度（基于特征值）
        intensity = (pitch + energy + tempo) / 3.0
        
        # 置信度（基于匹配度）
        confidence = max_score
        
        return {
            "type": max_emotion if max_score > 0.3 else "neutral",
            "intensity": intensity,
            "confidence": confidence,
            "scores": emotion_scores
        }
    
    def _range_match(self, value: float, range_tuple: tuple) -> float:
        """计算值在范围内的匹配度"""
        min_val, max_val = range_tuple
        if min_val <= value <= max_val:
            # 在范围内，计算到中心的距离
            center = (min_val + max_val) / 2.0
            distance = abs(value - center)
            range_size = max_val - min_val
            match = 1.0 - (distance / (range_size / 2.0))
            return max(match, 0.0)
        else:
            # 在范围外，计算距离
            if value < min_val:
                distance = min_val - value
            else:
                distance = value - max_val
            # 距离越大，匹配度越低
            match = max(0.0, 1.0 - distance * 2.0)
            return match
    
    def _default_features(self) -> Dict:
        """返回默认特征"""
        return {
            "pitch": 0.5,
            "energy": 0.5,
            "tempo": 0.5,
            "zero_crossing_rate": 0.0,
            "spectral_centroid": 0.5,
            "duration": 0.0
        }


# 全局语音情感识别器实例
voice_emotion_recognizer = VoiceEmotionRecognizer()





