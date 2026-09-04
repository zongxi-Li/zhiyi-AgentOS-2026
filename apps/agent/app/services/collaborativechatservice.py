"""
实时协作对话服务
支持多用户同时与同一角色对话
"""
import logging
import asyncio
from typing import Dict, List, Optional, Set
from collections import defaultdict
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)


class CollaborativeSession:
    """协作会话"""
    
    def __init__(self, session_id: str, role_id: str):
        self.session_id = session_id
        self.role_id = role_id
        self.participants: Set[str] = set()  # 参与者ID集合
        self.messages: List[Dict] = []  # 消息列表
        self.context: List[Dict] = []  # 对话上下文
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
    
    def add_participant(self, user_id: str):
        """添加参与者"""
        self.participants.add(user_id)
        self.last_activity = datetime.now()
        logger.info(f"用户 {user_id} 加入协作会话 {self.session_id}")
    
    def remove_participant(self, user_id: str):
        """移除参与者"""
        self.participants.discard(user_id)
        self.last_activity = datetime.now()
        logger.info(f"用户 {user_id} 离开协作会话 {self.session_id}")
    
    def add_message(self, user_id: str, content: str, message_type: str = "text"):
        """添加消息"""
        message = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "content": content,
            "type": message_type,
            "timestamp": datetime.now().isoformat()
        }
        self.messages.append(message)
        self.context.append({
            "role": "user",
            "content": content,
            "user_id": user_id
        })
        self.last_activity = datetime.now()
    
    def add_response(self, content: str, metadata: Optional[Dict] = None):
        """添加AI回复"""
        response = {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "content": content,
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat()
        }
        self.messages.append(response)
        self.context.append({
            "role": "assistant",
            "content": content
        })
        self.last_activity = datetime.now()


class CollaborativeChatService:
    """协作对话服务"""
    
    def __init__(self):
        self.active_sessions: Dict[str, CollaborativeSession] = {}
        self.user_sessions: Dict[str, Set[str]] = defaultdict(set)  # 用户参与的会话
    
    def create_session(
        self,
        role_id: str,
        creator_id: str,
        session_id: Optional[str] = None
    ) -> str:
        """
        创建协作会话
        
        Args:
            role_id: 角色ID
            creator_id: 创建者ID
            session_id: 会话ID（可选，不提供则自动生成）
        
        Returns:
            会话ID
        """
        if not session_id:
            session_id = str(uuid.uuid4())
        
        session = CollaborativeSession(session_id, role_id)
        session.add_participant(creator_id)
        
        self.active_sessions[session_id] = session
        self.user_sessions[creator_id].add(session_id)
        
        logger.info(f"创建协作会话: {session_id}, 角色: {role_id}, 创建者: {creator_id}")
        
        return session_id
    
    def join_session(self, session_id: str, user_id: str) -> bool:
        """
        加入会话
        
        Args:
            session_id: 会话ID
            user_id: 用户ID
        
        Returns:
            是否成功加入
        """
        if session_id not in self.active_sessions:
            return False
        
        session = self.active_sessions[session_id]
        session.add_participant(user_id)
        self.user_sessions[user_id].add(session_id)
        
        return True
    
    def leave_session(self, session_id: str, user_id: str):
        """离开会话"""
        if session_id in self.active_sessions:
            session = self.active_sessions[session_id]
            session.remove_participant(user_id)
            self.user_sessions[user_id].discard(session_id)
            
            # 如果会话没有参与者了，清理会话
            if not session.participants:
                del self.active_sessions[session_id]
                logger.info(f"会话 {session_id} 已关闭（无参与者）")
    
    async def process_message(
        self,
        session_id: str,
        user_id: str,
        content: str,
        ai_service
    ) -> Dict:
        """
        处理消息并生成回复
        
        Args:
            session_id: 会话ID
            user_id: 用户ID
            content: 消息内容
            ai_service: AI服务实例
        
        Returns:
            回复结果
        """
        if session_id not in self.active_sessions:
            raise ValueError(f"会话不存在: {session_id}")
        
        session = self.active_sessions[session_id]
        
        # 检查用户是否在会话中
        if user_id not in session.participants:
            raise ValueError(f"用户 {user_id} 不在会话 {session_id} 中")
        
        # 添加用户消息
        session.add_message(user_id, content)
        
        # 协调多个用户的问题（如果有多个未回复的问题）
        coordinated_context = self._coordinate_questions(session)
        
        # 生成AI回复
        try:
            response = await ai_service.generate_text(
                text=coordinated_context.get("combined_question", content),
                role_id=session.role_id,
                context=session.context[-10:]  # 使用最近10条消息作为上下文
            )
            
            response_text = response.get("text", "")
            
            # 添加AI回复
            session.add_response(response_text, {
                "responding_to": user_id,
                "participants_count": len(session.participants)
            })
            
            return {
                "session_id": session_id,
                "response": response_text,
                "participants": list(session.participants),
                "message_count": len(session.messages)
            }
        except Exception as e:
            logger.error(f"生成AI回复失败: {e}", exc_info=True)
            raise
    
    def _coordinate_questions(self, session: CollaborativeSession) -> Dict:
        """
        协调多个用户的问题
        
        如果有多个用户同时提问，将问题合并或选择主要问题
        """
        # 获取最近的消息（最近30秒内的）
        recent_messages = [
            msg for msg in session.messages[-10:]
            if msg.get("role") != "assistant"
            and self._is_recent(msg.get("timestamp", ""), seconds=30)
        ]
        
        if len(recent_messages) > 1:
            # 多个问题，合并或选择主要问题
            questions = [msg.get("content", "") for msg in recent_messages]
            combined_question = self._combine_questions(questions)
            
            return {
                "combined_question": combined_question,
                "source_questions": questions,
                "question_count": len(questions)
            }
        elif recent_messages:
            return {
                "combined_question": recent_messages[0].get("content", ""),
                "source_questions": [recent_messages[0].get("content", "")],
                "question_count": 1
            }
        else:
            return {
                "combined_question": "",
                "source_questions": [],
                "question_count": 0
            }
    
    def _combine_questions(self, questions: List[str]) -> str:
        """合并多个问题"""
        if not questions:
            return ""
        
        if len(questions) == 1:
            return questions[0]
        
        # 合并问题
        combined = f"有多个相关问题：{'；'.join(questions[:3])}"  # 最多合并3个问题
        if len(questions) > 3:
            combined += f"等共{len(questions)}个问题"
        
        return combined
    
    def _is_recent(self, timestamp: str, seconds: int = 30) -> bool:
        """判断时间戳是否在最近N秒内"""
        try:
            msg_time = datetime.fromisoformat(timestamp)
            delta = (datetime.now() - msg_time).total_seconds()
            return delta <= seconds
        except:
            return False
    
    def get_session_info(self, session_id: str) -> Optional[Dict]:
        """获取会话信息"""
        if session_id not in self.active_sessions:
            return None
        
        session = self.active_sessions[session_id]
        
        return {
            "session_id": session_id,
            "role_id": session.role_id,
            "participants": list(session.participants),
            "participant_count": len(session.participants),
            "message_count": len(session.messages),
            "created_at": session.created_at.isoformat(),
            "last_activity": session.last_activity.isoformat()
        }
    
    def get_user_sessions(self, user_id: str) -> List[Dict]:
        """获取用户参与的所有会话"""
        session_ids = self.user_sessions.get(user_id, set())
        sessions = []
        
        for session_id in session_ids:
            if session_id in self.active_sessions:
                info = self.get_session_info(session_id)
                if info:
                    sessions.append(info)
        
        return sessions
    
    def cleanup_inactive_sessions(self, hours: int = 24):
        """清理不活跃的会话"""
        cutoff_time = datetime.now().timestamp() - (hours * 3600)
        
        inactive_sessions = []
        for session_id, session in self.active_sessions.items():
            if session.last_activity.timestamp() < cutoff_time:
                inactive_sessions.append(session_id)
        
        for session_id in inactive_sessions:
            session = self.active_sessions[session_id]
            # 清理用户会话映射
            for user_id in session.participants:
                self.user_sessions[user_id].discard(session_id)
            del self.active_sessions[session_id]
            logger.info(f"清理不活跃会话: {session_id}")
        
        return len(inactive_sessions)


# 全局协作对话服务实例
collaborative_chat_service = CollaborativeChatService()





