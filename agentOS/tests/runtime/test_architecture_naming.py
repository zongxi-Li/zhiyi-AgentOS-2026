"""架构职责名称与兼容别名不变量。"""

from contracts.workflow import (
    AgentTask,
    LegacyAgentTask,
    WknWorkflowRun,
    WorkflowRun,
)
from runtime import WknWorkflowRuntime, WorkflowRuntime
from runtime.v2 import (
    AcgIdentityLifecycleService,
    WknAcgIdentityBridge,
    WknIdentityLifecycleAdapter,
    WorkflowRuntimeV2,
)
from support.acg import ACGBlueprint, WknBlueprintSpec


def test_architecture_uses_responsibility_names_with_compatible_aliases() -> None:
    assert WorkflowRuntime is WknWorkflowRuntime
    assert WorkflowRuntimeV2 is AcgIdentityLifecycleService
    assert WknAcgIdentityBridge is WknIdentityLifecycleAdapter
    assert AgentTask is LegacyAgentTask
    assert WorkflowRun is WknWorkflowRun
    assert ACGBlueprint is WknBlueprintSpec
