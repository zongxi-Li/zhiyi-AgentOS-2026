package com.kinlin.ai.projection.knowledgegraph.mapper;

import java.util.List;
import java.util.Map;

import com.kinlin.ai.projection.common.mapper.QueryWire;
import com.kinlin.ai.projection.knowledgegraph.dto.KnowledgeGraphEnvelopeQuery;

import static com.kinlin.ai.projection.common.mapper.QueryWire.integer;
import static com.kinlin.ai.projection.common.mapper.QueryWire.invalid;
import static com.kinlin.ai.projection.common.mapper.QueryWire.items;
import static com.kinlin.ai.projection.common.mapper.QueryWire.requiredText;
import static com.kinlin.ai.projection.common.mapper.QueryWire.text;

/**
 * Pure whitelist mapping from the KnowledgeGraphService query results to the
 * typed graph DTOs. No I/O, no recomputation: counters and node/edge lists pass
 * through in upstream order with the upstream snake_case keys.
 */
public final class KnowledgeGraphProjectionMapper {
    private KnowledgeGraphProjectionMapper() {
    }

    public static KnowledgeGraphEnvelopeQuery.StatsEnvelope stats(Map<String, Object> wire) {
        if (wire.get("entities_count") == null && wire.get("triples_count") == null) {
            throw invalid();
        }
        return new KnowledgeGraphEnvelopeQuery.StatsEnvelope(true, statsData(wire));
    }

    public static KnowledgeGraphEnvelopeQuery.GraphDataEnvelope graphData(Map<String, Object> wire) {
        if (wire.get("nodes") == null || wire.get("edges") == null) {
            throw invalid();
        }
        Object stats = wire.get("stats");
        return new KnowledgeGraphEnvelopeQuery.GraphDataEnvelope(true,
                new KnowledgeGraphEnvelopeQuery.GraphDataQuery(
                        items(wire.get("nodes"), KnowledgeGraphProjectionMapper::node),
                        items(wire.get("edges"), KnowledgeGraphProjectionMapper::edge),
                        stats instanceof Map<?, ?> statsMap && !statsMap.isEmpty()
                                ? statsData(statsMap) : null));
    }

    private static KnowledgeGraphEnvelopeQuery.GraphStatsQuery statsData(Map<?, ?> wire) {
        return new KnowledgeGraphEnvelopeQuery.GraphStatsQuery(
                integer(wire, "entities_count"),
                integer(wire, "relations_count"),
                integer(wire, "triples_count"));
    }

    private static KnowledgeGraphEnvelopeQuery.GraphNodeQuery node(Map<?, ?> raw) {
        return new KnowledgeGraphEnvelopeQuery.GraphNodeQuery(
                requiredText(raw, "id"),
                text(raw, "label"),
                text(raw, "type"));
    }

    private static KnowledgeGraphEnvelopeQuery.GraphEdgeQuery edge(Map<?, ?> raw) {
        return new KnowledgeGraphEnvelopeQuery.GraphEdgeQuery(
                requiredText(raw, "from"),
                requiredText(raw, "to"),
                text(raw, "label"),
                text(raw, "arrows"));
    }
}
