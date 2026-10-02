package com.kinlin.ai.projection.workspace.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Typed details of a Workspace diagnostic, constructed per code from the whitelist below;
 * the upstream details dict is never copied wholesale and unknown codes keep only
 * code/message/severity. All fields optional; an empty whitelist serializes as
 * {@code {}} matching the upstream {@code exclude_none} shape.
 *
 * <p>Per-code rules (workspace.py / agentos_v2.py producers):
 * <ul>
 *   <li>RUN_DELIVERABLE_MISSING — runId.</li>
 *   <li>GRAPH_TASK_NOT_FOUND — acgNodeId, taskId.</li>
 *   <li>TASK_PLAN_TASK_NOT_FOUND — semanticTaskKey, runId.</li>
 *   <li>LEGACY_ARTIFACT_IDENTITY — count (non-negative Long).</li>
 *   <li>PLAN_SNAPSHOT_UNRESOLVED — runId; taskPlanVersion as exact Integer. Upstream echoes
 *       the raw run-metadata pointer, whose type is unfixed (the diagnostic exists precisely
 *       because it may not resolve). Decision (E1): null/int/integer-string map exactly;
 *       any other value omits the field while the diagnostic itself stays (code, message,
 *       runId, HTTP 200) — the workspace must not turn into a fabricated 502, and raw
 *       objects must not reach the wire. No frontend component reads diagnostic details
 *       today, so the omission has no display impact.</li>
 *   <li>PLANNING_PROJECTION_PENDING — runtimeStatus, lifecyclePhase, errorCode (optional
 *       Strings).</li>
 *   <li>NO_ACTIVE_RUN — no fields (empty details, severity info).</li>
 * </ul>
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record WorkspaceDiagnosticDetailsQuery(
        String runId,
        String acgNodeId,
        String taskId,
        String semanticTaskKey,
        Long count,
        Integer taskPlanVersion,
        String runtimeStatus,
        String lifecyclePhase,
        String errorCode
) { }
