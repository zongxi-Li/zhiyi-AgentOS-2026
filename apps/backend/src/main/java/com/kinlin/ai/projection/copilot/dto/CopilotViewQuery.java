package com.kinlin.ai.projection.copilot.dto;

import java.util.List;

import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * Typed task-Copilot view for GET /runs/{runId}/copilot: mission identity, pending
 * planner question, shared conversation, review gate and model picker rows. Every
 * nested body is a closed record — the runtime's request echoes and planning patch
 * structures stay behind the projection, and history rows carry their source Run id.
 */
public record CopilotViewQuery(
        String runId,
        String missionId,
        String latestRunId,
        String taskPermission,
        String status,
        int revision,
        Question question,
        List<HumanAnswer> humanAnswers,
        Review review,
        List<Exchange> exchanges,
        Decision decision,
        List<Step> steps,
        boolean modelAvailable,
        List<ModelOption> models,
        String defaultModelId,
        List<String> permissions
) implements QueryResponse {

    public CopilotViewQuery {
        humanAnswers = List.copyOf(humanAnswers);
        exchanges = List.copyOf(exchanges);
        steps = List.copyOf(steps);
        models = List.copyOf(models);
        permissions = List.copyOf(permissions);
    }

    /** The pending planner clarification; absent unless the run waits on this round. */
    public record Question(
            String questionId,
            String prompt,
            List<String> choices
    ) {
        public Question {
            choices = List.copyOf(choices);
        }
    }

    /** One durable planner answer with its exact question and source Run. */
    public record HumanAnswer(
            String questionId,
            String sourceRunId,
            String prompt,
            String answer,
            String operationId,
            String answeredAt
    ) { }

    /** The waiting-review gate fact; absent outside waiting_review. */
    public record Review(
            String subjectId,
            String subjectType,
            String reason,
            String reasonCode,
            boolean canApprove,
            boolean decisionRejected,
            String expectedRunUpdatedAt
    ) { }

    /** One shared conversation row; the request echo stays upstream, never projected. */
    public record Exchange(
            String operationId,
            String user,
            String assistant,
            String createdAt,
            Long observedRevision,
            String permission,
            String modelId,
            String requestedModelId,
            String reasoningEffort,
            String sourceRunId,
            Action action,
            Receipt receipt
    ) { }

    /** A proposed task operation awaiting user confirmation. */
    public record Action(
            String kind,
            String stepId,
            Long expectedRevision,
            String capabilityCatalogRevision,
            Boolean executionEnvironmentChanged,
            List<String> executeStepIds,
            List<String> reusedStepIds,
            String content
    ) {
        public Action {
            executeStepIds = List.copyOf(executeStepIds);
            reusedStepIds = List.copyOf(reusedStepIds);
        }
    }

    /** The apply receipt of a confirmed operation. */
    public record Receipt(
            String proposalId,
            String runId,
            String kind,
            String status,
            List<String> executeStepIds,
            List<String> reusedStepIds
    ) {
        public Receipt {
            executeStepIds = List.copyOf(executeStepIds);
            reusedStepIds = List.copyOf(reusedStepIds);
        }
    }

    /** The latest planner decision headline; patch structures stay in the runtime. */
    public record Decision(
            String observationId,
            String action,
            String reason
    ) { }

    /** One step row of the current plan view. */
    public record Step(
            String stepId,
            String name,
            String status
    ) { }

    /** One selectable planner model route with its declared reasoning efforts. */
    public record ModelOption(
            String id,
            String provider,
            String model,
            List<String> reasoningEfforts,
            String defaultReasoningEffort
    ) {
        public ModelOption {
            reasoningEfforts = List.copyOf(reasoningEfforts);
        }
    }
}
