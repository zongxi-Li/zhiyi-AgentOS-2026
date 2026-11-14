"""Application-owned send projections over the SDK's append-only SQLite journal.

The SDK still writes every protocol item. Cursors are SDK row IDs, never message
text. Triggers invalidate views on branch edits; appends do not invalidate them.
Only commits re-hash archived rows. Warm reads decode the checkpoint and suffix.
"""
from dataclasses import dataclass
import hashlib
import json
import sqlite3
import time


POLICY_VERSION = 'oscode-working-context.v2'


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def policy_key(model, base_url, role_id, policies):
    policy = (policies or {}).get(f"{base_url.rstrip('/')}::{model}", {})
    return hashlib.sha256(wire([POLICY_VERSION, model, base_url.rstrip('/'), role_id, policy]).encode()).hexdigest()


def chain(rows, initial='0' * 64):
    digest = initial
    for row_id, data in rows:
        digest = hashlib.sha256((digest + wire([row_id, data])).encode()).hexdigest()
    return digest


@dataclass
class JournalView:
    messages: list
    origins: list
    cursor: int
    source_hash: str
    version: int
    epoch: int
    raw_count: int
    prefix_cursor: int
    prefix_hash: str
    rows: list
    metadata: dict


class ProjectionStore:
    def __init__(self, path, identity, policy, route):
        self.path, self.identity, self.policy, self.route = path, identity, policy, route

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self):
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS oscode_context_projections (
                    session_id TEXT PRIMARY KEY, owner_scope TEXT NOT NULL,
                    route TEXT NOT NULL, policy_version TEXT NOT NULL,
                    projection_version INTEGER NOT NULL DEFAULT 0,
                    history_epoch INTEGER NOT NULL DEFAULT 0,
                    valid INTEGER NOT NULL DEFAULT 0,
                    covered_cursor INTEGER NOT NULL DEFAULT 0,
                    covered_count INTEGER NOT NULL DEFAULT 0,
                    source_hash TEXT NOT NULL DEFAULT '',
                    projection_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    usage_anchor_json TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL DEFAULT 0
                );
                CREATE TRIGGER IF NOT EXISTS oscode_projection_journal_delete
                AFTER DELETE ON agent_messages BEGIN
                    UPDATE oscode_context_projections SET valid=0, history_epoch=history_epoch+1
                    WHERE session_id=OLD.session_id;
                END;
                CREATE TRIGGER IF NOT EXISTS oscode_projection_journal_update
                AFTER UPDATE ON agent_messages BEGIN
                    UPDATE oscode_context_projections SET valid=0, history_epoch=history_epoch+1
                    WHERE session_id IN (OLD.session_id, NEW.session_id);
                END;
                CREATE TRIGGER IF NOT EXISTS oscode_projection_journal_insert
                AFTER INSERT ON agent_messages BEGIN
                    UPDATE oscode_context_projections SET valid=0, history_epoch=history_epoch+1
                    WHERE session_id=NEW.session_id AND NEW.id<=covered_cursor;
                END;
            ''')
            # Idempotent migration from the first projection-store revision.
            if 'usage_anchor_json' not in {row[1] for row in db.execute('PRAGMA table_info(oscode_context_projections)')}:
                db.execute("ALTER TABLE oscode_context_projections ADD COLUMN usage_anchor_json TEXT NOT NULL DEFAULT '{}'")
            db.execute('''INSERT OR IGNORE INTO oscode_context_projections
                (session_id,owner_scope,route,policy_version) VALUES (?,?,?,?)''',
                (self.identity, self.identity.split(':')[0], wire(self.route), self.policy))

    def read(self, balance):
        with self.connect() as db:
            db.execute('BEGIN')
            state = db.execute('SELECT * FROM oscode_context_projections WHERE session_id=?', (self.identity,)).fetchone()
            if state is None:
                raise RuntimeError('CHAT_PROJECTION_MISSING')
            def object_json(value):
                try:
                    result = json.loads(value)
                    return result if isinstance(result, dict) else {}
                except (TypeError, ValueError):
                    return {}
            metadata = object_json(state['metadata_json'])
            valid = state['valid'] and state['policy_version'] == self.policy and state['route'] == wire(self.route)
            prefix = []
            if valid:
                try:
                    prefix = json.loads(state['projection_json'])
                    valid = (isinstance(prefix, list) and all(isinstance(item, dict) for item in prefix)
                        and hashlib.sha256(wire(prefix).encode()).hexdigest() == metadata.get('_projectionChecksum'))
                except (TypeError, ValueError):
                    valid = False
            if not valid:
                prefix, metadata = [], {}
            cursor = state['covered_cursor'] if valid else 0
            prefix_hash = state['source_hash'] if valid else '0' * 64
            rows = [tuple(row) for row in db.execute('SELECT id,message_data FROM agent_messages WHERE session_id=? AND id>? ORDER BY id',
                                                   (self.identity, cursor))]
            # Invalid JSON must fail closed: skipping a row would change cursor semantics.
            items = prefix + [json.loads(data) for _, data in rows]
            messages, origins = balance(items, row_ids=[None] * len(prefix) + [row_id for row_id, _ in rows])
            anchor = object_json(state['usage_anchor_json'])
            count = anchor.get('count')
            if (anchor.get('epoch') != state['history_epoch'] or state['policy_version'] != self.policy
                    or state['route'] != wire(self.route) or type(count) is not int or not 0 < count <= len(messages)
                    or hashlib.sha256(wire(messages[:count]).encode()).hexdigest() != anchor.get('prefixHash')):
                anchor = {}
            context_usage = anchor.get('watermark') or metadata.get('contextUsage')
            if isinstance(context_usage, dict):
                metadata['contextUsage'] = {**context_usage, 'projectionVersion': state['projection_version'] if valid else 0}
            return JournalView(messages, origins, rows[-1][0] if rows else cursor, chain(rows, prefix_hash),
                               state['projection_version'], state['history_epoch'],
                               (state['covered_count'] if valid else 0) + len(rows), cursor, prefix_hash, rows,
                               {**metadata, 'projectionVersion': state['projection_version'] if valid else 0,
                                'archivedItems': state['covered_count'] if valid else 0,
                                'journalReadItems': len(rows), '_usageAnchor': anchor})

    def save_anchor(self, anchor, epoch):
        with self.connect() as db:
            db.execute('''UPDATE oscode_context_projections SET usage_anchor_json=?
                WHERE session_id=? AND history_epoch=? AND policy_version=? AND route=?''',
                (wire({**anchor, 'epoch': epoch}), self.identity, epoch, self.policy, wire(self.route)))

    def commit(self, view, source, projected, metrics):
        """CAS a positional, hashed prefix. A later journal append is permitted."""
        if not source or len(source) > len(view.messages) or wire(view.messages[:len(source)]) != wire(source):
            return False
        cursor = view.origins[len(source) - 1]
        if cursor is None or cursor < view.prefix_cursor:
            return False
        covered_rows = [row for row in view.rows if row[0] <= cursor]
        expected_hash = chain(covered_rows, view.prefix_hash)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = db.execute('SELECT projection_version,history_epoch FROM oscode_context_projections WHERE session_id=?',
                               (self.identity,)).fetchone()
            if state is None or state['projection_version'] != view.version or state['history_epoch'] != view.epoch:
                return False
            rows = [tuple(row) for row in db.execute('SELECT id,message_data FROM agent_messages WHERE session_id=? AND id<=? ORDER BY id',
                                                    (self.identity, cursor))]
            if chain(rows) != expected_hash:
                return False
            db.execute('''UPDATE oscode_context_projections SET route=?,policy_version=?,projection_version=projection_version+1,
                valid=1,covered_cursor=?,covered_count=?,source_hash=?,projection_json=?,metadata_json=?,updated_at=?
                WHERE session_id=?''', (wire(self.route), self.policy, cursor, len(rows), expected_hash,
                                       wire(projected), wire({**metrics, '_projectionChecksum': hashlib.sha256(wire(projected).encode()).hexdigest()}),
                                       time.time(), self.identity))
        return True

    def result(self, call_id, offset=0, limit=8192):
        """Bounded authenticated journal read; caller supplies the scoped identity."""
        if not isinstance(call_id, str) or not call_id or len(call_id) > 256:
            raise ValueError('ARCHIVED_RESULT_REFERENCE_INVALID')
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 16384:
            raise ValueError('ARCHIVED_RESULT_RANGE_INVALID')
        with self.connect() as db:
            row = db.execute('''SELECT id,json_extract(message_data,'$.output') AS output FROM agent_messages
                WHERE session_id=? AND json_extract(message_data,'$.type')='function_call_output'
                AND json_extract(message_data,'$.call_id')=? ORDER BY id DESC LIMIT 1''', (self.identity, call_id)).fetchone()
            if row is None:
                raise ValueError('ARCHIVED_RESULT_NOT_FOUND')
            output = row['output'] if isinstance(row['output'], str) else wire(row['output'])
            return {'reference': f'journal:{call_id}', 'offset': offset, 'nextOffset': min(len(output), offset + limit),
                    'totalCharacters': len(output), 'truncated': offset + limit < len(output), 'text': output[offset:offset + limit]}
