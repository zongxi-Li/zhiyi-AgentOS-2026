"""
协作对话API路由
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.services.collaborativechatservice import collaborative_chat_service
from app.services.aiservice import AIService

router = APIRouter()

# AI服务实例
ai_service = AIService()


class CreateSessionRequest(BaseModel):
    role_id: str
    creator_id: str
    session_id: Optional[str] = None


class JoinSessionRequest(BaseModel):
    user_id: str


class SendMessageRequest(BaseModel):
    user_id: str
    content: str


@router.post("/collaborative-chat/create")
async def create_session(request: CreateSessionRequest):
    """
    创建协作会话
    
    示例：
    {
        "role_id": "lawyer",
        "creator_id": "user_123"
    }
    """
    try:
        session_id = collaborative_chat_service.create_session(
            role_id=request.role_id,
            creator_id=request.creator_id,
            session_id=request.session_id
        )
        
        return {
            "success": True,
            "data": {
                "session_id": session_id,
                "role_id": request.role_id
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建会话失败: {str(e)}")


@router.post("/collaborative-chat/{session_id}/join")
async def join_session(session_id: str, request: JoinSessionRequest):
    """加入协作会话"""
    try:
        success = collaborative_chat_service.join_session(session_id, request.user_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        return {
            "success": True,
            "message": f"用户 {request.user_id} 已加入会话"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"加入会话失败: {str(e)}")


@router.post("/collaborative-chat/{session_id}/leave")
async def leave_session(session_id: str, user_id: str):
    """离开协作会话"""
    try:
        collaborative_chat_service.leave_session(session_id, user_id)
        return {
            "success": True,
            "message": f"用户 {user_id} 已离开会话"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"离开会话失败: {str(e)}")


@router.post("/collaborative-chat/{session_id}/message")
async def send_message(session_id: str, request: SendMessageRequest):
    """
    发送消息到协作会话
    
    示例：
    {
        "user_id": "user_123",
        "content": "我想咨询法律问题"
    }
    """
    try:
        result = await collaborative_chat_service.process_message(
            session_id=session_id,
            user_id=request.user_id,
            content=request.content,
            ai_service=ai_service
        )
        
        return {
            "success": True,
            "data": result
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理消息失败: {str(e)}")


@router.get("/collaborative-chat/{session_id}")
async def get_session_info(session_id: str):
    """获取会话信息"""
    try:
        info = collaborative_chat_service.get_session_info(session_id)
        
        if not info:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        return {
            "success": True,
            "data": info
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取会话信息失败: {str(e)}")


@router.get("/collaborative-chat/user/{user_id}/sessions")
async def get_user_sessions(user_id: str):
    """获取用户参与的所有会话"""
    try:
        sessions = collaborative_chat_service.get_user_sessions(user_id)
        return {
            "success": True,
            "data": sessions
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取用户会话失败: {str(e)}")


@router.post("/collaborative-chat/cleanup")
async def cleanup_inactive_sessions(hours: int = 24):
    """清理不活跃的会话"""
    try:
        cleaned_count = collaborative_chat_service.cleanup_inactive_sessions(hours)
        return {
            "success": True,
            "message": f"已清理 {cleaned_count} 个不活跃会话"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清理会话失败: {str(e)}")





