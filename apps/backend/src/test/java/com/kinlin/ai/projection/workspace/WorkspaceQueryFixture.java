package com.kinlin.ai.projection.workspace;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Minimal sanitized GET /missions/{id}/workspace wire fixtures mirroring the upstream
 * pydantic dump semantics exactly: model-level nulls are absent (exclude_none), but nulls
 * INSIDE plain dicts (entry metadata, activeGraph, diagnostic details) stay on the wire.
 *
 * <p>Six upstream paths: full plan, missing plan snapshot, no run at all, deferred planning
 * fallback, legacy manifest artifacts, and plan/binding references to missing tasks.
 * SECRET sentinels mark internal control-plane values the projection must never echo;
 * {@link #MISSION_MD_LEAK} carries the upstream document sections that only the mapper may
 * rebuild. E2 mapper tests consume these maps for reachability and non-echo assertions.
 */
public final class WorkspaceQueryFixture {
    public static final String TIME = "2026-10-02T09:00:00.123456+08:00";
    public static final String SECRET = "internal-control-sentinel";

    /** Upstream mission.md body with the two leak sections the mapper must rebuild away. */
    public static final String MISSION_MD_LEAK = "# 审核合同\n\n查看执行进度\n\n## Mission metadata\n\n"
            + "```json\n{\n  \"identityGeneration\": \"" + SECRET + "\",\n  \"principalSource\": \"" + SECRET + "\"\n}"
            + "\n```\n\n## Current Run\n\n- Run: `run_1`\n- Status: `succeeded`\n"
            + "- Completed: `" + TIME + "`\n\n## Input attachments\n\n- **需求说明.md** (`att_1`) "
            + "- READY, 1024 bytes, `" + SECRET + "`\n\n## Planned steps\n\n- **读取材料** (`contract_read`): 提取公开结论\n"
            + "  - Constraints: `[{\"internal\": \"" + SECRET + "\"}]`\n";

    private WorkspaceQueryFixture() { }

    /** Raw Mission model as the envelope carries it today (userId + metadata included). */
    public static Map<String, Object> mission() {
        Map<String, Object> mission = new LinkedHashMap<>();
        mission.put("missionId", "mission_1");
        mission.put("userId", SECRET);
        mission.put("goal", "审核合同");
        mission.put("description", "查看执行进度");
        mission.put("metadata", Map.of(
                "identityGeneration", SECRET, "principalSource", SECRET,
                "runtimeDomain", SECRET, "runtimeIntent", SECRET));
        mission.put("createdAt", TIME);
        mission.put("updatedAt", TIME);
        mission.put("status", "active");
        return mission;
    }

    public static Map<String, Object> runSummary(String runId, boolean active) {
        Map<String, Object> run = new LinkedHashMap<>();
        run.put("runId", runId);
        run.put("status", active ? "succeeded" : "failed");
        run.put("createdAt", TIME);
        if (active) { run.put("completedAt", TIME); }
        run.put("isActive", active);
        return run;
    }

    /** Blueprint display snapshot with execution-spec sentinels that must not reach the DTO. */
    public static Map<String, Object> activeGraph(Integer planVersion) {
        Map<String, Object> node = new LinkedHashMap<>();
        node.put("nodeId", "node_1");
        node.put("nodeType", "agent");
        node.put("name", "读取材料");
        node.put("agentName", "审查员");
        node.put("inputSpec", Map.of("schema", SECRET));
        node.put("loopSpec", Map.of("policy", SECRET));
        node.put("modelName", SECRET);
        node.put("retryLimit", 3);
        node.put("metadata", Map.of("binding", SECRET));
        Map<String, Object> edge = Map.of("edgeId", "edge_1", "sourceId", "node_1", "targetId", "node_2",
                "edgeType", "dependency", "condition", SECRET);
        Map<String, Object> graph = new LinkedHashMap<>();
        graph.put("complexityLevel", "standard");
        graph.put("createdAt", TIME);
        graph.put("edges", List.of(edge));
        graph.put("graphId", "graph_1");
        graph.put("metadata", Map.of("package", SECRET));
        graph.put("missionId", "mission_1");
        graph.put("nodes", List.of(node));
        graph.put("objective", "审核合同");
        graph.put("priority", SECRET);
        graph.put("updatedAt", TIME);
        graph.put("version", 3);
        graph.put("blueprintId", "blueprint_1");
        graph.put("graphVersion", 3);
        graph.put("taskPlanVersion", planVersion); // dict value: null stays on the wire
        return graph;
    }

    public static Map<String, Object> graphNode() {
        Map<String, Object> node = new LinkedHashMap<>();
        node.put("acgNodeId", "node_1");
        node.put("nodeType", "agent");
        node.put("name", "读取材料");
        node.put("semanticTaskKey", "contract_read");
        node.put("taskId", "task_1");
        node.put("identityQuality", "canonical");
        node.put("displayOrder", 0);
        node.put("status", "succeeded");
        node.put("attemptId", "attempt_1");
        node.put("artifactCount", 1);
        node.put("artifactIds", List.of("artifact_1"));
        return node;
    }

    /** GRAPH explorer entry; metadata taskPlanVersion only when a plan resolved. */
    public static Map<String, Object> graphEntry(Integer planVersion) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("entryId", "overview:graph.acg");
        entry.put("kind", "graph");
        entry.put("name", "graph.acg");
        entry.put("group", "overview");
        entry.put("parentEntryId", "folder:overview");
        entry.put("displayOrder", 0);
        entry.put("runId", "run_1");
        entry.put("blueprintId", "blueprint_1");
        entry.put("graphId", "graph_1");
        entry.put("graphVersion", 3);
        entry.put("metadata", planVersion == null ? Map.of() : Map.of("taskPlanVersion", planVersion));
        return entry;
    }

    public static Map<String, Object> systemDocumentEntry() {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("entryId", "overview:mission.md");
        entry.put("kind", "virtual_document");
        entry.put("name", "mission.md");
        entry.put("group", "overview");
        entry.put("parentEntryId", "folder:overview");
        entry.put("displayOrder", 1);
        entry.put("content", MISSION_MD_LEAK);
        entry.put("metadata", Map.of());
        return entry;
    }

    /** TASK entry with the runtime join keys plus injected executor display metadata. */
    public static Map<String, Object> taskEntry() {
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("runtimeStatus", "succeeded");
        metadata.put("parentTaskId", SECRET);
        metadata.put("outputRef", "content_ref_1");
        metadata.put("outputSummary", "已生成阶段结论");
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("entryId", "task:contract_read");
        entry.put("kind", "task");
        entry.put("name", "读取材料");
        entry.put("title", "读取材料");
        entry.put("group", "steps");
        entry.put("parentEntryId", "folder:steps");
        entry.put("displayOrder", 0);
        entry.put("semanticTaskKey", "contract_read");
        entry.put("taskId", "task_1");
        entry.put("logicalRole", "task");
        entry.put("objective", "提取公开结论");
        entry.put("dependencyKeys", List.of());
        entry.put("attemptCount", 1);
        entry.put("latestAttemptId", "attempt_1");
        entry.put("acgNodeId", "node_1");
        entry.put("artifactCount", 1);
        entry.put("identityQuality", "canonical");
        entry.put("status", "completed");
        entry.put("runId", "run_1");
        entry.put("metadata", metadata);
        return entry;
    }

    /** Canonical artifact entry whose metadata dict only ever holds identity internals. */
    public static Map<String, Object> artifactEntry() {
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("identityVersion", SECRET);
        metadata.put("logicalRole", "final_synthesis");
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("entryId", "task:contract_read:primary");
        entry.put("kind", "artifact");
        entry.put("name", "final.md");
        entry.put("group", "output");
        entry.put("parentEntryId", "folder:output");
        entry.put("displayOrder", 0);
        entry.put("semanticTaskKey", "contract_read");
        entry.put("artifactKey", "primary");
        entry.put("taskId", "task_1");
        entry.put("logicalRole", "final_synthesis");
        entry.put("attemptCount", 0);
        entry.put("artifactCount", 0);
        entry.put("artifactId", "artifact_1");
        entry.put("contentRef", "content_ref_1");
        entry.put("artifactType", "run_deliverable");
        entry.put("mediaType", "text/markdown");
        entry.put("checksum", "a".repeat(64));
        entry.put("attemptId", "attempt_1");
        entry.put("acgNodeId", "node_1");
        entry.put("disposition", "GENERATED");
        // model-level nulls (e.g. sourceRunId, completedAt) stay absent on the wire
        entry.put("identityQuality", "canonical");
        entry.put("createdAt", TIME);
        entry.put("runId", "run_1");
        entry.put("metadata", metadata);
        return entry;
    }

    public static Map<String, Object> runEntry(Map<String, Object> summary) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("entryId", "run:" + summary.get("runId"));
        entry.put("kind", "run");
        entry.put("name", summary.get("runId"));
        entry.put("group", "runs");
        entry.put("parentEntryId", "folder:runs");
        entry.put("displayOrder", 0);
        entry.put("runId", summary.get("runId"));
        entry.put("status", summary.get("status"));
        entry.put("createdAt", TIME);
        entry.put("isActive", summary.get("isActive"));
        entry.put("metadata", Map.of("projection", "run-history"));
        return entry;
    }

    public static Map<String, Object> folder(String name, String group) {
        return new LinkedHashMap<>(Map.of(
                "entryId", "folder:" + group, "kind", "folder", "name", name, "group", group,
                "displayOrder", 0, "metadata", Map.of()));
    }

    /** Whitelisted attachment wire row: owner/storage keys excluded, metadata dict kept. */
    public static Map<String, Object> attachment() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("attachmentId", "att_1");
        row.put("originalFilename", "需求说明.md");
        row.put("mimeType", "text/markdown");
        row.put("extension", "md");
        row.put("sizeBytes", 1024);
        row.put("sha256", "b".repeat(64));
        row.put("status", "READY");
        row.put("characterCount", 512);
        row.put("metadata", Map.of("internal", SECRET));
        row.put("createdAt", TIME);
        row.put("updatedAt", TIME);
        return row;
    }

    public static Map<String, Object> diagnostic(String code, String severity, Map<String, Object> details) {
        Map<String, Object> diagnostic = new LinkedHashMap<>();
        diagnostic.put("code", code);
        diagnostic.put("message", "诊断信息 " + code);
        diagnostic.put("severity", severity);
        diagnostic.put("details", details);
        return diagnostic;
    }

    private static Map<String, Object> envelope(Map<String, Object> parts) {
        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("mission", parts.get("mission"));
        if (parts.containsKey("activeRun")) { envelope.put("activeRun", parts.get("activeRun")); }
        if (parts.containsKey("activeGraph")) { envelope.put("activeGraph", parts.get("activeGraph")); }
        envelope.put("runs", parts.getOrDefault("runs", List.of()));
        envelope.put("entries", parts.getOrDefault("entries", List.of()));
        envelope.put("graphNodes", parts.getOrDefault("graphNodes", List.of()));
        envelope.put("inputAttachments", parts.getOrDefault("inputAttachments", List.of()));
        envelope.put("diagnostics", parts.getOrDefault("diagnostics", List.of()));
        envelope.put("unknown", SECRET);
        return envelope;
    }

    /** Selected run with a resolved plan: full graph, task, artifact and navigator rows. */
    public static Map<String, Object> normalPlan() {
        Map<String, Object> active = runSummary("run_1", true);
        return envelope(Map.of(
                "mission", mission(),
                "activeRun", active,
                "activeGraph", activeGraph(2),
                "runs", List.of(active, runSummary("run_0", false)),
                "entries", List.of(folder("Overview", "overview"), folder("Steps", "steps"),
                        folder("Output", "output"), folder("Runs", "runs"),
                        graphEntry(2), systemDocumentEntry(), taskEntry(), artifactEntry(),
                        runEntry(active)),
                "graphNodes", List.of(graphNode()),
                "inputAttachments", List.of(attachment()),
                "diagnostics", List.of()));
    }

    /** Unresolvable plan pointer: fallback order, empty graph metadata, null version in details. */
    public static Map<String, Object> noPlan() {
        Map<String, Object> active = runSummary("run_1", true);
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("runId", "run_1");
        details.put("taskPlanVersion", null); // dict value: null stays on the wire
        return envelope(Map.of(
                "mission", mission(),
                "activeRun", active,
                "activeGraph", activeGraph(null),
                "runs", List.of(active),
                "entries", List.of(folder("Overview", "overview"), folder("Steps", "steps"),
                        folder("Output", "output"), folder("Runs", "runs"),
                        graphEntry(null), systemDocumentEntry(), taskEntry()),
                "graphNodes", List.of(),
                "diagnostics", List.of(diagnostic("PLAN_SNAPSHOT_UNRESOLVED", "warning", details))));
    }

    /** Mission without any Run: no activeRun/activeGraph keys at all, NO_ACTIVE_RUN info. */
    public static Map<String, Object> noRun() {
        return envelope(Map.of(
                "mission", mission(),
                "entries", List.of(folder("Overview", "overview"), folder("Steps", "steps"),
                        folder("Output", "output"), folder("Runs", "runs"), systemDocumentEntry()),
                "inputAttachments", List.of(attachment()),
                "diagnostics", List.of(diagnostic("NO_ACTIVE_RUN", "info", Map.of()))));
    }

    /** Runtime-only run before identity projection exists: planning-pending banner. */
    public static Map<String, Object> deferredFallback() {
        Map<String, Object> active = runSummary("run_2", true);
        active.put("status", "running");
        active.remove("completedAt");
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("runtimeStatus", "running");
        details.put("lifecyclePhase", "planning");
        details.put("errorCode", null); // dict value: null stays on the wire
        return envelope(Map.of(
                "mission", mission(),
                "activeRun", active,
                "runs", List.of(active),
                "inputAttachments", List.of(attachment()),
                "diagnostics", List.of(diagnostic("PLANNING_PROJECTION_PENDING", "warning", details))));
    }

    /** Sealed manifests without V2 identity: count diagnostic plus legacy entries. */
    public static Map<String, Object> legacyArtifact() {
        Map<String, Object> active = runSummary("run_1", true);
        Map<String, Object> legacy = new LinkedHashMap<>();
        legacy.put("entryId", "legacy:manifest_1");
        legacy.put("kind", "artifact");
        legacy.put("name", "manifest_1");
        legacy.put("group", "steps");
        legacy.put("parentEntryId", "folder:steps");
        legacy.put("displayOrder", 1);
        legacy.put("contentRef", "manifest_1");
        legacy.put("mediaType", "text/markdown");
        legacy.put("artifactType", "legacy_artifact");
        legacy.put("identityQuality", "legacy");
        legacy.put("createdAt", TIME);
        legacy.put("metadata", Map.of());
        return envelope(Map.of(
                "mission", mission(),
                "activeRun", active,
                "runs", List.of(active),
                "entries", List.of(folder("Overview", "overview"), folder("Steps", "steps"),
                        folder("Output", "output"), folder("Runs", "runs"), systemDocumentEntry(), legacy),
                "diagnostics", List.of(diagnostic("LEGACY_ARTIFACT_IDENTITY", "warning", Map.of("count", 1)))));
    }

    /** Plan/binding rows referencing a missing task: both not-found diagnostics fire. */
    public static Map<String, Object> missingTask() {
        Map<String, Object> active = runSummary("run_1", true);
        Map<String, Object> orphanNode = new LinkedHashMap<>();
        orphanNode.put("acgNodeId", "node_9");
        orphanNode.put("nodeType", "agent");
        orphanNode.put("name", "node_9");
        orphanNode.put("displayOrder", 1);
        orphanNode.put("artifactCount", 0);
        orphanNode.put("artifactIds", List.of());
        return envelope(Map.of(
                "mission", mission(),
                "activeRun", active,
                "activeGraph", activeGraph(2),
                "runs", List.of(active),
                "entries", List.of(folder("Overview", "overview"), folder("Steps", "steps"),
                        folder("Output", "output"), folder("Runs", "runs"), graphEntry(2),
                        systemDocumentEntry()),
                "graphNodes", List.of(orphanNode),
                "diagnostics", List.of(
                        diagnostic("TASK_PLAN_TASK_NOT_FOUND", "warning",
                                Map.of("semanticTaskKey", "ghost_task", "runId", "run_1")),
                        diagnostic("GRAPH_TASK_NOT_FOUND", "warning",
                                Map.of("acgNodeId", "node_9", "taskId", "task_9")))));
    }
}
