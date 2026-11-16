"""Explicit default runtime assembly; the facade supplies its stable runtime type."""

import os

from adapters.agent.native import register_native_runtime
from components.mission.store import WorkflowRegistry
from adapters.agent import AgentRegistry
from support.packs.registry import register_installed_packs
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
from support.stores.workflow_store import WorkflowStore


def assemble_default_runtime(runtime_type):
    """按环境变量装配默认运行时并登记原生与已安装插件；缺少数据库路径时抛出错误。"""
    agent_registry = AgentRegistry()
    workflow_registry = WorkflowRegistry()

    db_path = os.getenv("AGENTOS_WORKFLOW_DB_PATH", "").strip()
    workflow_store: WorkflowStore
    if not db_path:
        raise RuntimeError("Workflow database path is required outside test mode.")
    workflow_store = SQLiteWorkflowStore(db_path)

    runtime = runtime_type(
        agent_registry=agent_registry,
        workflow_registry=workflow_registry,
        workflow_store=workflow_store,
        model_max_concurrency=int(os.getenv("AGENTOS_MODEL_MAX_CONCURRENCY", "4")),
        model_min_interval_seconds=float(
            os.getenv("AGENTOS_MODEL_MIN_INTERVAL_SECONDS", "0")
        ),
    )
    register_native_runtime(
        agent_registry=runtime.agent_registry,
        workflow_registry=runtime.workflow_registry,
    )
    runtime.plugin_manifests = register_installed_packs(
        agent_registry=runtime.agent_registry,
        workflow_registry=runtime.workflow_registry,
        capability_catalog=runtime.capability_catalog,
    )
    return runtime
