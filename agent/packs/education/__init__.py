"""教育 Pack 的注册入口与包级配置。"""



from pathlib import Path

from agent.packs.education.agents import LessonPlanAgent


def register_pack(agent_registry, workflow_registry) -> None:
    """注册教育工作流 Pack。"""

    agent_registry.register(LessonPlanAgent())
    workflow_registry.load_directory(Path(__file__).resolve().parent / "workflows")
