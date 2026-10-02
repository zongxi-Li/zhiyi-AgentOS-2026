package com.kinlin.ai.projection.graph.mapper;

import com.kinlin.ai.projection.graph.dto.*;
import java.util.Map;
import static com.kinlin.ai.projection.common.mapper.QueryWire.*;

public final class GraphProjectionMapper {
    private GraphProjectionMapper() { }
    public static GraphQuery identityGraph(Map<?, ?> blueprint) {
        GraphQuery graph = graph(object(blueprint.get("graph")));
        return new GraphQuery(graph.runId(), text(blueprint, "graphId"), smallInt(blueprint, "version"),
                text(blueprint, "missionId"), graph.objective(), graph.complexityLevel(), graph.nodes(), graph.edges(),
                graph.completedStepIds(), graph.activeStepIds(), graph.skippedStepIds());
    }
    public static GraphQuery graph(Map<?, ?> source) {
        Integer version = smallInt(source, "graphVersion");
        if (version == null) { version = smallInt(source, "version"); }
        return new GraphQuery(text(source, "runId"), text(source, "graphId"), version, text(source, "missionId"),
                text(source, "objective"), text(source, "complexityLevel"), items(source.get("nodes"), GraphProjectionMapper::node),
                items(source.get("edges"), GraphProjectionMapper::edge), texts(source.get("completedStepIds")),
                texts(source.get("activeStepIds")), texts(source.get("skippedStepIds")));
    }
    /** Shared with the workspace graph projection; the run graph output is regression-covered. */
    public static GraphNodeQuery node(Map<?, ?> node) {
        return new GraphNodeQuery(requiredText(node, "nodeId"), text(node, "nodeType"), text(node, "name"),
                text(node, "description"), text(node, "goal"), text(node, "agentName"), text(node, "capability"),
                text(node, "controlType"), display(optionalObject(node.get("metadata"))));
    }
    /** Shared with the workspace graph projection; the run graph output is regression-covered. */
    public static GraphEdgeQuery edge(Map<?, ?> edge) {
        return new GraphEdgeQuery(text(edge, "edgeId"), requiredText(edge, "sourceId"), requiredText(edge, "targetId"),
                text(edge, "edgeType"), text(edge, "activation"), display(optionalObject(edge.get("metadata"))));
    }
    private static GraphDisplayQuery display(Map<?, ?> value) {
        return new GraphDisplayQuery(text(value, "semanticTaskKey"), text(value, "taskId"), text(value, "logicalRole"),
                text(value, "endpointRole"), text(value, "agentName"), texts(value.get("allowedSkills")),
                texts(value.get("dependencyKeys")), smallInt(value, "displayOrder"));
    }
}
