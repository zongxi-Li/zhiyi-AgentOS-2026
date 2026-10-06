package com.kinlin.ai.projection.resourcecatalog.dto;

import java.util.List;

import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * Typed persisted heartbeat/observation history of one catalog resource. Null
 * measurement fields are the "not observed" states of the upstream event rows.
 */
public record ResourceHealthHistoryQuery(
        String resourceId,
        List<Event> items,
        Long total
) implements QueryResponse {

    public ResourceHealthHistoryQuery {
        items = List.copyOf(items);
    }

    /** One recorded health observation. */
    public record Event(
            String observedAt,
            Double reliability,
            Double latencyMs,
            String lastHeartbeat,
            Long version
    ) { }
}
