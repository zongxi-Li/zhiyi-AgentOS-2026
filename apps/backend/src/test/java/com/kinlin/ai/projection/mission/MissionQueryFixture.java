package com.kinlin.ai.projection.mission;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Actual MissionDetail / MissionRunHistory wire shapes plus hostile unknown fields. */
public final class MissionQueryFixture {
    public static final String TIME = "2026-10-01T12:00:00.123456+08:00";
    public static final String SECRET = "internal-control-sentinel";
    private MissionQueryFixture() { }

    public static Map<String, Object> run() {
        Map<String, Object> run = new LinkedHashMap<>();
        run.put("runId", "run_1");
        run.put("missionId", "mission_1");
        run.put("blueprintId", "blueprint_1");
        run.put("status", "running");
        run.put("graphVersion", 3);
        run.put("startedAt", TIME);
        run.put("finishedAt", null);
        run.put("createdAt", TIME);
        run.put("updatedAt", TIME);
        run.put("checkpoint", Map.of("scheduler", SECRET));
        run.put("metadata", Map.of("binding", SECRET));
        run.put("executionState", Map.of("graphPatchRefs", List.of(SECRET)));
        return run;
    }

    public static Map<String, Object> history() {
        return new LinkedHashMap<>(Map.of("missionId", "mission_1", "runs", List.of(run()), "unknown", SECRET));
    }

    public static Map<String, Object> detail() {
        Map<String, Object> mission = new LinkedHashMap<>(Map.of(
                "missionId", "mission_1", "userId", SECRET, "goal", "审核合同", "description", "查看执行进度",
                "status", "running", "createdAt", TIME, "updatedAt", TIME, "metadata", Map.of("path", SECRET)));
        Map<String, Object> task = new LinkedHashMap<>(Map.of(
                "taskId", "task_1", "missionId", "mission_1", "title", "读取材料", "objective", "提取公开结论",
                "status", "running", "constraints", List.of(Map.of("internal", SECRET)), "metadata", Map.of("binding", SECRET)));
        task.put("parentTaskId", null);
        task.put("semanticTaskKey", null); // Legacy identity rows are valid without a semantic key.
        Map<String, Object> blueprint = Map.of(
                "blueprintId", "blueprint_1", "missionId", "mission_1", "graphId", "graph_1", "version", 3,
                "createdAt", TIME, "graph", Map.of("nodes", List.of(Map.of("policy", SECRET))), "metadata", Map.of("package", SECRET));
        return new LinkedHashMap<>(Map.of("mission", mission, "tasks", List.of(task), "blueprints", List.of(blueprint),
                "runs", List.of(run()), "TaskPlan", Map.of("binding", SECRET), "unknown", SECRET));
    }
}
