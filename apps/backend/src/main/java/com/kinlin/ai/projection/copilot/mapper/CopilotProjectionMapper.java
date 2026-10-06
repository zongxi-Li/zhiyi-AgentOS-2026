package com.kinlin.ai.projection.copilot.mapper;

import java.util.Map;

import com.kinlin.ai.projection.copilot.dto.CopilotViewQuery;
import com.kinlin.ai.projection.copilot.dto.CopilotViewQuery.Action;
import com.kinlin.ai.projection.copilot.dto.CopilotViewQuery.Decision;
import com.kinlin.ai.projection.copilot.dto.CopilotViewQuery.Exchange;
import com.kinlin.ai.projection.copilot.dto.CopilotViewQuery.HumanAnswer;
import com.kinlin.ai.projection.copilot.dto.CopilotViewQuery.ModelOption;
import com.kinlin.ai.projection.copilot.dto.CopilotViewQuery.Question;
import com.kinlin.ai.projection.copilot.dto.CopilotViewQuery.Receipt;
import com.kinlin.ai.projection.copilot.dto.CopilotViewQuery.Review;
import com.kinlin.ai.projection.copilot.dto.CopilotViewQuery.Step;

import static com.kinlin.ai.projection.common.mapper.QueryWire.bool;
import static com.kinlin.ai.projection.common.mapper.QueryWire.integer;
import static com.kinlin.ai.projection.common.mapper.QueryWire.items;
import static com.kinlin.ai.projection.common.mapper.QueryWire.object;
import static com.kinlin.ai.projection.common.mapper.QueryWire.requiredInt;
import static com.kinlin.ai.projection.common.mapper.QueryWire.requiredText;
import static com.kinlin.ai.projection.common.mapper.QueryWire.text;
import static com.kinlin.ai.projection.common.mapper.QueryWire.texts;

/**
 * Pure whitelist mapping from the runtime planning interaction {@code view} wire to
 * the typed task-Copilot view. No I/O, no recomputation: identity fields are required,
 * conversation rows keep their source Run attribution, and the upstream request echo
 * ({@code operationRequest}) plus the planning patch structures inside {@code decision}
 * stay behind the projection.
 */
public final class CopilotProjectionMapper {
    private CopilotProjectionMapper() {
    }

    public static CopilotViewQuery view(Map<String, Object> wire) {
        return new CopilotViewQuery(
                requiredText(wire, "runId"),
                requiredText(wire, "missionId"),
                text(wire, "latestRunId"),
                text(wire, "taskPermission"),
                requiredText(wire, "status"),
                requiredInt(wire, "revision"),
                wire.get("question") == null ? null : question(object(wire.get("question"))),
                items(wire.get("humanAnswers"), CopilotProjectionMapper::humanAnswer),
                wire.get("review") == null ? null : review(object(wire.get("review"))),
                items(wire.get("exchanges"), CopilotProjectionMapper::exchange),
                wire.get("decision") == null ? null : decision(object(wire.get("decision"))),
                items(wire.get("steps"), CopilotProjectionMapper::step),
                Boolean.TRUE.equals(bool(wire, "modelAvailable")),
                items(wire.get("models"), CopilotProjectionMapper::modelOption),
                text(wire, "defaultModelId"),
                texts(wire.get("permissions")));
    }

    private static Question question(Map<?, ?> raw) {
        return new Question(requiredText(raw, "questionId"), text(raw, "prompt"), texts(raw.get("choices")));
    }

    private static HumanAnswer humanAnswer(Map<?, ?> raw) {
        return new HumanAnswer(requiredText(raw, "questionId"), text(raw, "sourceRunId"),
                text(raw, "prompt"), text(raw, "answer"), text(raw, "operationId"), text(raw, "answeredAt"));
    }

    private static Review review(Map<?, ?> raw) {
        return new Review(text(raw, "subjectId"), text(raw, "subjectType"), text(raw, "reason"),
                text(raw, "reasonCode"), Boolean.TRUE.equals(bool(raw, "canApprove")),
                Boolean.TRUE.equals(bool(raw, "decisionRejected")), text(raw, "expectedRunUpdatedAt"));
    }

    private static Exchange exchange(Map<?, ?> raw) {
        return new Exchange(requiredText(raw, "operationId"), text(raw, "user"), text(raw, "assistant"),
                text(raw, "createdAt"), integer(raw, "observedRevision"), text(raw, "permission"),
                text(raw, "modelId"), text(raw, "requestedModelId"), text(raw, "reasoningEffort"),
                text(raw, "sourceRunId"),
                raw.get("action") == null ? null : action(object(raw.get("action"))),
                raw.get("receipt") == null ? null : receipt(object(raw.get("receipt"))));
    }

    private static Action action(Map<?, ?> raw) {
        return new Action(requiredText(raw, "kind"), text(raw, "stepId"), integer(raw, "expectedRevision"),
                text(raw, "capabilityCatalogRevision"), bool(raw, "executionEnvironmentChanged"),
                texts(raw.get("executeStepIds")), texts(raw.get("reusedStepIds")), text(raw, "content"));
    }

    private static Receipt receipt(Map<?, ?> raw) {
        return new Receipt(text(raw, "proposalId"), text(raw, "runId"), text(raw, "kind"),
                text(raw, "status"), texts(raw.get("executeStepIds")), texts(raw.get("reusedStepIds")));
    }

    private static Decision decision(Map<?, ?> raw) {
        return new Decision(text(raw, "observationId"), text(raw, "action"), text(raw, "reason"));
    }

    private static Step step(Map<?, ?> raw) {
        return new Step(requiredText(raw, "stepId"), text(raw, "name"), text(raw, "status"));
    }

    private static ModelOption modelOption(Map<?, ?> raw) {
        return new ModelOption(requiredText(raw, "id"), text(raw, "provider"), text(raw, "model"),
                texts(raw.get("reasoningEfforts")), text(raw, "defaultReasoningEffort"));
    }
}
