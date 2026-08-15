"""程序员 Pack 的智能体实现，负责需求分析、代码检索、代码生成和图表生成步骤。"""


from service.agents.base import AgentOutput, AgentProfile, BaseAgent


class RequirementAnalysisAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            AgentProfile(
                agentName="requirement_analysis",
                domain="programmer",
                capabilities=["requirement_analysis", "technical_spec"],
                allowedSkills=["requirement_analysis"],
                description="Turns a programming request into a minimal implementation specification.",
            )
        )

    async def run(self, context):
        task_input = context.task.input
        requirement = str(task_input.get("requirement") or context.task.title).strip()
        target_language = str(task_input.get("targetLanguage") or task_input.get("target_language") or "python").strip()
        spec = {
            "requirement": requirement,
            "target_language": target_language,
            "functional_requirements": [
                "Validate required input.",
                "Implement the requested behavior.",
                "Return structured success and error results.",
            ],
            "acceptance_criteria": [
                "Happy path returns expected output.",
                "Invalid input is rejected with a clear error.",
            ],
        }
        return AgentOutput(
            output={
                "technical_spec": spec,
                "final_answer": f"Requirement analysis ready for {target_language}: {requirement}.",
            },
            summary="Requirement analysis generated.",
        )
