"""写作 Pack 的注册入口与包级配置。"""



from pathlib import Path

from agent.packs.writer.agents import OutlineGenerateAgent


def register_pack(agent_registry, workflow_registry) -> None:
    """注册写作工作流 Pack。"""

    agent_registry.register(OutlineGenerateAgent())
    workflow_registry.load_directory(Path(__file__).resolve().parent / "workflows")
