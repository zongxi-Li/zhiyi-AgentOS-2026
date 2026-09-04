"""写作 Pack 的注册入口与包级配置。"""



from pathlib import Path

from packs.writer.agents import OutlineGenerateAgent
from packs.writer.capabilities import register_writer_capabilities


def register_pack(agent_registry, workflow_registry, capability_catalog) -> None:
    """注册写作工作流 Pack。"""

    register_writer_capabilities(capability_catalog)
    agent_registry.register(OutlineGenerateAgent())
    workflow_registry.load_directory(Path(__file__).resolve().parent / "workflows")
