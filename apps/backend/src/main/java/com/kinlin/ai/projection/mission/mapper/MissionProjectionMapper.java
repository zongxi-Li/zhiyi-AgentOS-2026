package com.kinlin.ai.projection.mission.mapper;

import com.kinlin.ai.projection.mission.dto.MissionDetailQuery;
import com.kinlin.ai.projection.mission.dto.MissionRunHistoryQuery;
import com.kinlin.ai.projection.mission.dto.MissionRunSummaryQuery;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.time.DateTimeException;
import java.util.List;
import java.util.Map;
import java.util.function.Function;

/** Pure whitelist mapping from existing client wire results. No I/O or state authority. */
public final class MissionProjectionMapper {
    private MissionProjectionMapper() { }

    public static MissionDetailQuery detail(Map<String, Object> wire) {
        Map<?, ?> mission = object(wire.get("mission"));
        return new MissionDetailQuery(new MissionDetailQuery.MissionSummary(
                text(mission, "missionId"), text(mission, "goal"), text(mission, "description"),
                text(mission, "status"), time(mission, "createdAt", false), time(mission, "updatedAt", false)),
                items(wire.get("tasks"), task -> new MissionDetailQuery.TaskSummary(
                        text(task, "taskId"), text(task, "missionId"), optionalText(task, "semanticTaskKey"),
                        optionalText(task, "parentTaskId"), text(task, "title"), text(task, "objective"),
                        text(task, "status"), list(task.get("constraints")).size())),
                items(wire.get("blueprints"), graph -> new MissionDetailQuery.GraphSummary(
                        text(graph, "graphId"), positiveInt(graph, "version"), time(graph, "createdAt", false))),
                items(wire.get("runs"), MissionProjectionMapper::run));
    }

    public static MissionRunHistoryQuery history(Map<String, Object> wire) {
        return new MissionRunHistoryQuery(text(wire, "missionId"), items(wire.get("runs"), MissionProjectionMapper::run));
    }

    private static MissionRunSummaryQuery run(Map<?, ?> run) {
        return new MissionRunSummaryQuery(text(run, "runId"), text(run, "missionId"), text(run, "status"),
                positiveInt(run, "graphVersion"), time(run, "startedAt", true), time(run, "finishedAt", true),
                time(run, "createdAt", false), time(run, "updatedAt", false));
    }

    private static String text(Map<?, ?> source, String field) {
        if (source.get(field) instanceof String value) { return value; }
        throw invalid();
    }

    private static String optionalText(Map<?, ?> source, String field) {
        return source.get(field) == null ? null : text(source, field);
    }

    private static String time(Map<?, ?> source, String field, boolean optional) {
        String value = optional ? optionalText(source, field) : text(source, field);
        if (value != null) {
            try { OffsetDateTime.parse(value); }
            catch (DateTimeException invalidTime) { throw invalid(); }
        }
        return value; // Preserve upstream offset and precision instead of reformatting it.
    }

    private static int positiveInt(Map<?, ?> source, String field) {
        if (!(source.get(field) instanceof Number value)) { throw invalid(); }
        int result = new BigDecimal(value.toString()).intValueExact();
        if (result < 1) { throw invalid(); }
        return result;
    }

    private static Map<?, ?> object(Object value) {
        if (value instanceof Map<?, ?> map) { return map; }
        throw invalid();
    }

    private static List<?> list(Object value) {
        if (value instanceof List<?> list) { return list; }
        throw invalid();
    }

    private static <T> List<T> items(Object value, Function<Map<?, ?>, T> mapper) {
        return list(value).stream().map(item -> mapper.apply(object(item))).toList();
    }

    private static IllegalArgumentException invalid() {
        return new IllegalArgumentException("Invalid Mission query contract");
    }
}
