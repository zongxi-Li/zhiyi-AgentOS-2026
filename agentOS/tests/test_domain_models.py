import pytest

from support.domain import (
    AgentProfile,
    StepDefinition,
    Task,
    TaskStatus,
    WorkflowDefinition,
)


def test_agent_profile_normalizes_identity_and_supports_capabilities_case_insensitively():
    profile = AgentProfile(
        agent_name=" Risk ",
        domain=" Legal ",
        capabilities=["Risk", " review "],
        allowed_skills=["statute_lookup"],
    )

    assert profile.agent_name == "risk"
    assert profile.domain == "legal"
    assert profile.supports("risk") is True
    assert profile.supports("REVIEW") is True
    assert profile.supports("draft") is False
    assert profile.can_use_skill("statute_lookup") is True


def test_step_definition_validates_required_identity_and_retry_count():
    with pytest.raises(ValueError, match="step_id"):
        StepDefinition(step_id=" ", name="Risk", agent_name="risk")

    with pytest.raises(ValueError, match="max_retries"):
        StepDefinition(step_id="risk", name="Risk", agent_name="risk", max_retries=-1)


def test_workflow_definition_exposes_first_get_and_next_step_ids():
    workflow = WorkflowDefinition(
        workflow_id=" legal_contract_review_v1 ",
        name="Legal Contract Review",
        domain=" Legal ",
        intent=" contract_review ",
        steps=[
            StepDefinition(step_id="risk", name="Risk", agent_name="risk"),
            StepDefinition(step_id="draft", name="Draft", agent_name="draft", next_step_id="done"),
        ],
    )

    assert workflow.workflow_id == "legal_contract_review_v1"
    assert workflow.domain == "legal"
    assert workflow.intent == "contract_review"
    assert workflow.first_step_id() == "risk"
    assert workflow.get_step("risk").agent_name == "risk"
    assert workflow.next_step_id("risk") == "draft"
    assert workflow.next_step_id("draft") is None


def test_workflow_definition_rejects_empty_or_duplicate_steps():
    with pytest.raises(ValueError, match="at least one step"):
        WorkflowDefinition(workflow_id="w1", name="Workflow", domain="legal", steps=[])

    with pytest.raises(ValueError, match="duplicate step_id"):
        WorkflowDefinition(
            workflow_id="w1",
            name="Workflow",
            domain="legal",
            steps=[
                StepDefinition(step_id="risk", name="Risk", agent_name="risk"),
                StepDefinition(step_id="risk", name="Risk Again", agent_name="risk"),
            ],
        )


def test_task_uses_nonblank_role_and_task_aliases_without_blank_override():
    task = Task(
        title="合同审查",
        domain="legal",
        intent="contract_review",
        role_type=" ",
        task_type="",
        input={"source": "workbench"},
    )

    assert task.domain == "legal"
    assert task.intent == "contract_review"
    assert task.input == {"source": "workbench"}
    assert task.status == TaskStatus.PENDING


def test_task_prefers_nonblank_role_and_task_aliases_and_can_assign_workflow():
    task = Task(
        title="课程设计",
        domain="legal",
        intent="contract_review",
        role_type="education",
        task_type="lesson_plan",
    )

    task.assign_workflow("education_lesson_plan_v1")

    assert task.domain == "education"
    assert task.intent == "lesson_plan"
    assert task.recommended_workflow == "education_lesson_plan_v1"


def test_task_rejects_invalid_lifecycle_transition():
    task = Task(title="合同审查", domain="legal", intent="contract_review")

    task.transition_to(TaskStatus.RUNNING)
    task.transition_to(TaskStatus.COMPLETED)

    with pytest.raises(ValueError, match="illegal transition"):
        task.transition_to(TaskStatus.RUNNING)
