"""User-visible binding to the system-issued, startup-scoped Host Grant.

Selecting a path confirms the existing authority; no client-selected allowedRoot
or new Grant enters the executor. Changing roots requires an explicit relaunch.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from app.security.internal_auth import current_trusted_user


class WorkspaceSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str


def create_router(runtime):
    router = APIRouter()

    async def binding():
        if current_trusted_user() is None:
            raise HTTPException(401, 'Authenticated user required')
        client = getattr(runtime, 'local_runtime_client', None)
        authorization = getattr(runtime, 'local_runtime_authorization', None)
        if client is None or authorization is None:
            raise HTTPException(503, 'Local workspace is not configured')
        root = await client.workspace_root(authorization)
        return {'workspaceRoot': root, 'workspaceId': authorization.workspace_id,
                'grantId': authorization.grant_id, 'scope': 'startup-workspace',
                'capabilities': ['fs.list', 'fs.read', 'fs.write', 'fs.patch']}

    @router.get('/local-workspace')
    async def get_workspace():
        return await binding()

    @router.post('/local-workspace/select')
    async def select_workspace(request: WorkspaceSelection):
        selected = await binding()
        try:
            matches = Path(request.path).resolve(strict=True) == Path(selected['workspaceRoot']).resolve(strict=True)
        except (OSError, ValueError):
            matches = False
        if not matches:
            raise HTTPException(403, 'Directory is outside the startup-issued Workspace Grant; relaunch with -Workspace')
        return {**selected, 'selected': True}

    return router
