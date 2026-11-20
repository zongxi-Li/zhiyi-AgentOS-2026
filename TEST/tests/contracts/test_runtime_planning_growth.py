"""The durable planning inbox is not capped by the number of prior rounds."""
from datetime import datetime, timezone

from contracts.runtime_planning import RuntimeHumanAnswer, RuntimePlanningObservation, RuntimeUserInput


def test_observation_keeps_all_confirmed_human_answers_and_operator_inputs():
    now = datetime.now(timezone.utc)
    answers = tuple(RuntimeHumanAnswer(questionId=f"question:{index}", sourceRunId="run:source",
        prompt="Clarify the current source scope", answer=f"answer {index}",
        operationId=f"answer:{index}", answeredAt=now) for index in range(96))
    inputs = tuple(RuntimeUserInput(sourceRunId="run:source", operationId=f"input:{index}",
        content=f"confirmed request {index}", submittedAt=now) for index in range(96))
    observation = RuntimePlanningObservation(missionId="mission_0123456789ab", runId="run:current",
        graphId="graph", graphVersion=200, planVersion=200, wakeReason="user_input", goal="Review sources",
        steps=(), remainingStepIds=(), humanAnswers=answers, userInputs=inputs)
    restored = RuntimePlanningObservation.model_validate_json(observation.model_dump_json(by_alias=True))
    assert restored.human_answers == answers and restored.user_inputs == inputs
    assert restored.fingerprint() == observation.fingerprint()
