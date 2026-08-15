"""教育 Pack 的注册入口与包级配置。"""



from pathlib import Path

from packs.education.agents import LessonPlanAgent
from packs.education.capabilities import register_education_capabilities


def register_pack(agent_registry, workflow_registry, capability_catalog) -> None:
    """注册教育工作流 Pack。"""

    register_education_capabilities(capability_catalog)
    agent_registry.register(LessonPlanAgent())
    workflow_registry.load_directory(Path(__file__).resolve().parent / "workflows")
