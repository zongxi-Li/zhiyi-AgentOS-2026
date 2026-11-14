"""DSH-style durable protocol journal with a separate, tool-balanced send view.

SQLiteSession owns SDK message persistence. The UI history is only a bootstrap
for conversations created before this journal existed, never the next turn's
source of truth. Scope comes from the authenticated application identity.
"""
from contextlib import asynccontextmanager
import asyncio
import hashlib
import json
import sqlite3
import time

from agents import SQLiteSession
from app.paths import APP_DATA_DIR
from app.security.internal_auth import current_trusted_user
from app.context_compaction.protocol import is_checkpoint, model_tool_data
from app.context_compaction.store import ProjectionStore, policy_key

_active = set()
_idle_jobs = {}


async def cancel_idle(identity):
    job = _idle_jobs.get(identity)
    if job is not None and job is not asyncio.current_task():
        _idle_jobs.pop(identity, None)
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)


def prepare_when_idle(identity, prepare):
    if identity in _idle_jobs or identity in _active:
        return
    async def run():
        try:
            await prepare()
        except asyncio.CancelledError:
            raise
        except Exception:
            # A soft-budget optimization must never become an unhandled task or
            # destroy the last committed projection. Metrics report foreground failures.
            import logging
            logging.getLogger(__name__).warning('oscode_idle_projection_failed', exc_info=False)
        finally:
            if _idle_jobs.get(identity) is asyncio.current_task():
                _idle_jobs.pop(identity, None)
    _idle_jobs[identity] = asyncio.create_task(run())


def conversation_scope(context_id):
    user = current_trusted_user()
    if user is None:
        return None
    return hashlib.sha256(json.dumps([user.tenant_id, user.user_id, context_id]).encode()).hexdigest()


def balanced_view(items, *, row_ids=None):
    """Keep confirmed results; close unrecorded outcomes explicitly, never as success."""
    calls = {x.get('call_id') for x in items if x.get('type') == 'function_call'}
    results = {x.get('call_id') for x in items if x.get('type') == 'function_call_output'}
    names = {x.get('call_id'): x.get('name') for x in items if x.get('type') == 'function_call'}
    view = []
    origins = []
    for index, item in enumerate(items):
        if item.get('type') == 'function_call_output' and item.get('call_id') not in calls:
            continue
        # Older journals can contain the same command snapshot under two aliases.
        # Project it losslessly, without rewriting the journal or clipping output.
        if item.get('type') == 'function_call_output' and names.get(item.get('call_id')) in {'run_command', 'terminal'}:
            try:
                envelope = json.loads(item.get('output', ''))
                if isinstance(envelope, dict) and envelope.get('ok') is True:
                    data = envelope.get('data')
                    projected = model_tool_data(names[item['call_id']], data)
                    if projected is not data:
                        item = {**item, 'output': json.dumps({**envelope, 'data': projected},
                                                           ensure_ascii=False, separators=(',', ':'))}
            except (TypeError, ValueError):
                pass
        view.append(item)
        origins.append(row_ids[index] if row_ids is not None else None)
        if item.get('type') == 'function_call' and item.get('call_id') not in results:
            view.append({'type': 'function_call_output', 'call_id': item['call_id'],
                         'output': json.dumps({'error': 'TOOL_OUTCOME_UNKNOWN',
                           'message': 'Previous request interrupted before a durable result. Inspect actual state before retrying; do not assume success.'})})
            origins.append(row_ids[index] if row_ids is not None else None)
    return (view, origins) if row_ids is not None else view


class ProtocolSession(SQLiteSession):
    projection = None
    projection_store = None
    last_view = None
    pending_projection = None
    on_progress = None

    async def get_items(self, limit=None):
        started = time.perf_counter()
        if self.projection_store and limit is None:
            self.last_view = await asyncio.to_thread(self.projection_store.read, balanced_view)
            raw = self.last_view.messages
            if self.on_progress:
                self.on_progress('model_phase', {'phase': 'context_journal',
                    **{k: v for k, v in self.last_view.metadata.items() if not k.startswith('_')},
                    'responseTimings': {'journalReadMs': round((time.perf_counter() - started) * 1000)}})
        else:
            raw = balanced_view(await super().get_items(limit))
        if self.projection is None or (self.last_view and self.last_view.metadata.get('projectionVersion')):
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

    async def commit_projection(self, source, projected, metrics):
        if self.projection_store is None or source == projected:
            return False
        view = await asyncio.to_thread(self.projection_store.read, balanced_view)
        if self.last_view and (view.version != self.last_view.version or view.epoch != self.last_view.epoch):
            return False
        # The journal is now durable, including tool steps written by Runner.
        committed = await asyncio.to_thread(self.projection_store.commit, view, source, projected, metrics)
        if committed:
            self.last_view = await asyncio.to_thread(self.projection_store.read, balanced_view)
        if self.on_progress:
            self.on_progress('model_phase', {'phase': 'context_committed' if committed else 'context_stale',
                'projectionVersion': self.last_view.version if self.last_view else 0,
                'archivedItems': self.last_view.metadata.get('archivedItems', 0) if self.last_view else 0,
                'contextUsage': self.last_view.metadata.get('contextUsage') if self.last_view else None})
        return committed

    async def flush_projection(self):
        candidate, self.pending_projection = self.pending_projection, None
        if candidate:
            try:
                return await self.commit_projection(*candidate)
            except Exception:
                import logging
                logging.getLogger(__name__).warning('oscode_projection_not_saved', exc_info=False)
                if self.on_progress:
                    self.on_progress('model_phase', {'phase': 'context_failed', 'failureCode': 'PROJECTION_SAVE_FAILED'})
        return False


@asynccontextmanager
async def open_chat_session(context_id, model, base_url, role_id, history, projection=False):
    scope = conversation_scope(context_id)
    if scope is None or not context_id:
        yield None
        return
    identity = session_identity(scope, model, base_url, role_id)
    await cancel_idle(identity)
    if identity in _active:
        raise RuntimeError('CHAT_SESSION_BUSY')
    _active.add(identity)
    session = None
    try:
        started = time.perf_counter()
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        session = ProtocolSession(identity, APP_DATA_DIR / 'oscode_sessions.sqlite3')
        session.context_id = context_id
        # Only test journal existence here. Runner reads the full balanced input
        # once; loading every historical tool output twice delays long sessions.
        if not await SQLiteSession.get_items(session, limit=1):
            await session.add_items(history or [])
        from app.config import settings
        session.projection_store = ProjectionStore(session.db_path, identity,
            policy_key(model, base_url, role_id, settings.OSCODE_CONTEXT_COMPACTION_MODELS),
            [base_url.rstrip('/'), model, role_id])
        await asyncio.to_thread(session.projection_store.initialize)
        session.preparation_timings = {'journalOpenMs': round((time.perf_counter() - started) * 1000)}
        if projection:
            session.projection = history
        yield session
    finally:
        if session:
            session.close()
        _active.discard(identity)


def session_identity(scope, model, base_url, role_id):
    return scope + ':' + hashlib.sha256(json.dumps([base_url.rstrip('/'), model, role_id]).encode()).hexdigest()


async def read_context_usage(context_id, model, base_url, role_id):
    """Read the existing scoped projection without acquiring or cancelling a live Runner."""
    scope = conversation_scope(context_id)
    path = APP_DATA_DIR / 'oscode_sessions.sqlite3'
    if not scope or not path.exists():
        return None
    from app.config import settings
    store = ProjectionStore(path, session_identity(scope, model, base_url, role_id),
        policy_key(model, base_url, role_id, settings.OSCODE_CONTEXT_COMPACTION_MODELS),
        [base_url.rstrip('/'), model, role_id])
    try:
        view = await asyncio.to_thread(store.read, balanced_view)
    except sqlite3.OperationalError as error:
        if 'no such table' not in str(error):
            raise
        return None
    except RuntimeError as error:
        if str(error) != 'CHAT_PROJECTION_MISSING':
            raise
        return None
    from app.llm.capabilities import provider_model_capabilities
    policy = settings.OSCODE_CONTEXT_COMPACTION_MODELS.get(f"{base_url.rstrip('/')}::{model}", {})
    window = policy.get('context_window', provider_model_capabilities(model, base_url).context_window_tokens)
    state = view.metadata.get('contextUsage') or {'usedTokens':None,'measurement':'unknown','source':'prepared'}
    return {**state, 'maxTokens':window}


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
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='oscode_context_projections'").fetchone():
            connection.execute('DELETE FROM oscode_context_projections WHERE session_id LIKE ?', (scope + ':%',))


async def forget_chat_sessions_safely(context_id):
    scope = conversation_scope(context_id)
    if scope:
        for identity in list(_idle_jobs):
            if identity.startswith(scope + ':'):
                await cancel_idle(identity)
    forget_chat_sessions(context_id)
