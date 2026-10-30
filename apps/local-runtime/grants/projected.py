"""Read the backend's atomic workspace projection on every authorization."""
from datetime import datetime, timezone
import json
from pathlib import Path

from runtime.errors import AuthorizationError
from .models import GrantRecord, WorkspaceRecord


class ProjectedGrantStore:
    def __init__(self, path, caller_id, capabilities):
        self.path = Path(path)
        self.caller_id = caller_id
        self.capabilities = frozenset(capabilities)

    def _records(self):
        try:
            records = json.loads(self.path.read_text(encoding='utf-8'))['grants']
            if not isinstance(records, list):
                raise ValueError('Invalid grant list')
            seen = set()
            roots = {}
            for record in records:
                for key in ('grantId', 'workspaceId', 'canonicalRoot'):
                    if not isinstance(record[key], str) or not record[key]:
                        raise ValueError('Invalid workspace identity')
                if not Path(record['canonicalRoot']).is_absolute() or record['grantId'] in seen:
                    raise ValueError('Invalid or duplicate grant')
                if record['workspaceId'] in roots and roots[record['workspaceId']] != record['canonicalRoot']:
                    raise ValueError('Conflicting workspace roots')
                for key in ('allowedCallers', 'capabilities'):
                    if not isinstance(record[key], list) or not all(isinstance(item, str) for item in record[key]):
                        raise ValueError('Invalid grant scope')
                if not isinstance(record.get('revoked'), bool):
                    raise ValueError('Invalid revocation flag')
                seen.add(record['grantId'])
                roots[record['workspaceId']] = record['canonicalRoot']
            return [record for record in records if self.caller_id in record['allowedCallers']]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise AuthorizationError('GRANT_PROJECTION_UNAVAILABLE') from exc

    def get_workspace(self, workspace_id):
        for row in self._records():
            if row['workspaceId'] == workspace_id:
                return WorkspaceRecord(workspace_id, Path(row['canonicalRoot']))
        return None

    def get_grant(self, grant_id):
        for row in self._records():
            if row['grantId'] == grant_id:
                return GrantRecord(grant_id=grant_id, workspace_id=row['workspaceId'],
                    canonical_root=Path(row['canonicalRoot']),
                    allowed_capabilities=frozenset(row['capabilities']) & self.capabilities,
                    created_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
                    revoked=row.get('revoked') is not False)
        return None
