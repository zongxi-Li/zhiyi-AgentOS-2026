"""程序员 Pack 的注册入口与包级配置。"""



from pathlib import Path

from agent.packs.programmer.agents import (
    CodeGenerationAgent,
    CodebaseSearchAgent,
    DiagramGenerationAgent,
    RequirementAnalysisAgent,
)


def register_pack(agent_registry, workflow_registry) -> None:
    """注册程序员工作流 Pack。"""

    agent_registry.register(RequirementAnalysisAgent())
    agent_registry.register(CodebaseSearchAgent())
    agent_registry.register(CodeGenerationAgent())
    agent_registry.register(DiagramGenerationAgent())
    workflow_registry.load_directory(Path(__file__).resolve().parent / "workflows")
