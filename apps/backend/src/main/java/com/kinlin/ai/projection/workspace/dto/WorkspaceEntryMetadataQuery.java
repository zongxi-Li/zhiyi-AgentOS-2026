package com.kinlin.ai.projection.workspace.dto;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Explicit whitelist for entry {@code metadata} (workspace.py writes free-form dicts).
 * The JSON path {@code metadata} is preserved — consumers read these keys through
 * {@code entry.metadata.*} and must not be promoted elsewhere — but the container is a
 * typed record, not the Role free-JSON exception.
 *
 * <p>Field-level compatibility record (E1 verification, 2026-10-02):
 * <ul>
 *   <li>{@code outputRef}/{@code outputSummary} — injected by agentos_v2.py from the
 *       execution runtime's {@code outputRefs}/{@code outputSummaries}, both typed
 *       {@code dict[str, str]} (executor/graph.py); type-stable Strings. Consumers:
 *       TaskEditor + RuntimeInspector (typeof-string guarded), artifactProjection.</li>
 *   <li>{@code runtimeStatus} — workspace.py from latest attempt status value; String.
 *       Consumer: ProjectTaskExecutionInspector ({@code || '未观测'} fallback).</li>
 *   <li>{@code taskPlanVersion} — workspace.py GRAPH entry from plan.plan_version; int
 *       (99/99 int in the workflow_runs_v2 metadata census). Consumers:
 *       ProjectGraphInspector, ProjectRunSidebarView. Never moved out of metadata.</li>
 *   <li>Artifact descriptor candidates ({@code artifactKind}/{@code artifact_kind}/
 *       {@code schema}/{@code schemaName}, {@code evidenceRefs}/{@code evidence_refs},
 *       {@code upstreamInputs}/{@code sourceStepIds}, {@code traceLinks}/{@code traceRefs},
 *       {@code confidence}, {@code agentName}/{@code agent}) — no Python producer exists
 *       today and the identity store census shows none of these keys, so value types are
 *       unprovable; they are typed as the consumers' display shapes (String /
 *       List&lt;String&gt;) with the original wire aliases preserved. The frontend readers
 *       (artifactProjection text/list) filter non-scalars to empty, so omitting a
 *       non-conforming value is display-equivalent to the raw passthrough.</li>
 * </ul>
 *
 * <p>Dropped metadata keys (registered in the scheme matrix): {@code identityVersion} and
 * metadata-level {@code logicalRole} (canonicalize_artifact_identity internals; the entry
 * top-level logicalRole is kept), {@code sourceAttachmentIds} (no public consumer; public
 * attachments already live in inputAttachments), {@code parentTaskId} (no consumer
 * repo-wide), {@code projection} (run-history internal marker). The mapper must project a
 * whitelisted key only when its value conforms to the declared type, and omit it otherwise
 * — never stringify objects and never fail the whole workspace for a bad candidate.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record WorkspaceEntryMetadataQuery(
        String outputRef,
        String outputSummary,
        String runtimeStatus,
        Integer taskPlanVersion,
        String artifactKind,
        String artifact_kind,
        String schema,
        String schemaName,
        List<String> evidenceRefs,
        List<String> evidence_refs,
        List<String> upstreamInputs,
        List<String> sourceStepIds,
        List<String> traceLinks,
        List<String> traceRefs,
        String confidence,
        String agentName,
        String agent
) {
    public WorkspaceEntryMetadataQuery {
        evidenceRefs = immutable(evidenceRefs);
        evidence_refs = immutable(evidence_refs);
        upstreamInputs = immutable(upstreamInputs);
        sourceStepIds = immutable(sourceStepIds);
        traceLinks = immutable(traceLinks);
        traceRefs = immutable(traceRefs);
    }

    private static List<String> immutable(List<String> value) {
        return value == null ? null : List.copyOf(value);
    }

    /** Empty whitelist for entries without metadata (folders, system document, runs). */
    public static WorkspaceEntryMetadataQuery empty() {
        return new WorkspaceEntryMetadataQuery(null, null, null, null, null, null, null, null,
                null, null, null, null, null, null, null, null, null);
    }
}
