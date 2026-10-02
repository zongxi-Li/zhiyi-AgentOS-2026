package com.kinlin.ai.projection.knowledgegraph.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * Typed knowledge-graph query envelopes over the {@code /api/knowledge-graph}
 * read-only queries whose data payload shapes are evidenced by frontend readers
 * (KnowledgeGraphView / KnowledgeGraphVisualization). Wire keys stay snake_case
 * exactly as the remote service emits them, so the consumers keep reading
 * {@code entities_count} and friends unchanged. The success/data envelope is
 * part of the wire contract the frontend unwraps, so it is modeled concretely
 * per query (no generic DTO fields).
 *
 * <p>Entity, search and reason responses use the sibling {@link KnowledgeQuery}
 * contracts traced to the repository's Python producers.
 */
public final class KnowledgeGraphEnvelopeQuery {
    private KnowledgeGraphEnvelopeQuery() {
    }

    /** GET /stats wire envelope with the three counters the stat strips render. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record StatsEnvelope(
            Boolean success,
            GraphStatsQuery data
    ) implements QueryResponse {
    }

    /** GET /graph-data wire envelope with nodes, edges and stats for the visualization. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record GraphDataEnvelope(
            Boolean success,
            GraphDataQuery data
    ) implements QueryResponse {
    }

    /** GET /stats data payload. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record GraphStatsQuery(
            Long entities_count,
            Long relations_count,
            Long triples_count
    ) implements QueryResponse {
    }

    /** GET /graph-data data payload. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record GraphDataQuery(
            List<GraphNodeQuery> nodes,
            List<GraphEdgeQuery> edges,
            GraphStatsQuery stats
    ) implements QueryResponse {
    }

    /** One graph node; the unread {@code properties} bag is dropped and registered. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record GraphNodeQuery(
            String id,
            String label,
            String type
    ) implements QueryResponse {
    }

    /** One graph edge in vis-network shape. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record GraphEdgeQuery(
            String from,
            String to,
            String label,
            String arrows
    ) implements QueryResponse {
    }
}
