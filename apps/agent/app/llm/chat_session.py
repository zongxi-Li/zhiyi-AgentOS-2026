"""DSH-style durable protocol journal with a separate, tool-balanced send view.

SQLiteSession owns SDK message persistence. The UI history is only a bootstrap
for conversations created before this journal existed, never the next turn's
source of truth. Scope comes from the authenticated application identity.
"""
from contextlib import asynccontextmanager
import hashlib
import json

from agents import SQLiteSession
from app.paths import APP_DATA_DIR
from app.security.internal_auth import current_trusted_user
from app.context_compaction.protocol import is_checkpoint

_active = set()


def conversation_scope(context_id):
    user = current_trusted_user()
    if user is None:
        return None
    return hashlib.sha256(json.dumps([user.tenant_id, user.user_id, context_id]).encode()).hexdigest()


def balanced_view(items):
    """Keep confirmed results; close unrecorded outcomes explicitly, never as success."""
    calls = {x.get('call_id') for x in items if x.get('type') == 'function_call'}
    results = {x.get('call_id') for x in items if x.get('type') == 'function_call_output'}
    view = []
    for item in items:
        if item.get('type') == 'function_call_output' and item.get('call_id') not in calls:
            continue
        view.append(item)
        if item.get('type') == 'function_call' and item.get('call_id') not in results:
            view.append({'type': 'function_call_output', 'call_id': item['call_id'],
                         'output': json.dumps({'error': 'TOOL_OUTCOME_UNKNOWN',
                           'message': 'Previous request interrupted before a durable result. Inspect actual state before retrying; do not assume success.'})})
    return view


class ProtocolSession(SQLiteSession):
    projection = None

    async def get_items(self, limit=None):
        raw = balanced_view(await super().get_items(limit))
        if self.projection is None:
            return raw
        # An explicit /compact changes the send view, not the source journal.
        # Preserve full protocol cycles for the retained user-turn suffix.
        # Generated checkpoint messages stay untrusted user data, but they are
        # not original turns. Match only retained original users to the journal.
        projected_users = [x['content'] for x in self.projection if x.get('role') == 'user' and not is_checkpoint(x)]
        def text(item):
            content = item.get('content', '')
            return content if isinstance(content, str) else ''.join(block.get('text', '') for block in content)
        users = [(i, text(x)) for i, x in enumerate(raw) if x.get('role') == 'user']
        if not projected_users:
            return self.projection
        tail = users[-len(projected_users):]
        if [text for _, text in tail] != projected_users:
            raise ValueError('CHAT_CONTEXT_PROJECTION_STALE')
        first_user = next(i for i, x in enumerate(self.projection) if x.get('role') == 'user' and not is_checkpoint(x))
        return self.projection[:first_user] + raw[tail[0][0]:]


@asynccontextmanager
async def open_chat_session(context_id, model, base_url, role_id, history, projection=False):
    scope = conversation_scope(context_id)
    if scope is None or not context_id:
        yield None
        return
    route = hashlib.sha256(json.dumps([base_url.rstrip('/'), model, role_id]).encode()).hexdigest()
    identity = scope + ':' + route
    if identity in _active:
        raise RuntimeError('CHAT_SESSION_BUSY')
    _active.add(identity)
    session = None
    try:
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        session = ProtocolSession(identity, APP_DATA_DIR / 'oscode_sessions.sqlite3')
        # Only test journal existence here. Runner reads the full balanced input
        # once; loading every historical tool output twice delays long sessions.
        if not await SQLiteSession.get_items(session, limit=1):
            await session.add_items(history or [])
        if projection:
            session.projection = history
        yield session
    finally:
        if session:
            session.close()
        _active.discard(identity)


def forget_chat_sessions(context_id):
    import sqlite3
    scope = conversation_scope(context_id)
    path = APP_DATA_DIR / 'oscode_sessions.sqlite3'
    if not scope or not path.exists():
        return
    if any(key.startswith(scope + ':') for key in _active):
        raise RuntimeError('CHAT_SESSION_BUSY')
    with sqlite3.connect(path) as connection:
        connection.execute('DELETE FROM agent_messages WHERE session_id LIKE ?', (scope + ':%',))
        connection.execute('DELETE FROM agent_sessions WHERE session_id LIKE ?', (scope + ':%',))
