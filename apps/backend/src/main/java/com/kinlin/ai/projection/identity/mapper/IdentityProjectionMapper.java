package com.kinlin.ai.projection.identity.mapper;

import java.util.Map;

import com.kinlin.ai.projection.common.mapper.QueryWire;
import com.kinlin.ai.projection.identity.dto.IdentityHealthQuery;

import static com.kinlin.ai.projection.common.mapper.QueryWire.invalid;
import static com.kinlin.ai.projection.common.mapper.QueryWire.object;
import static com.kinlin.ai.projection.common.mapper.QueryWire.requiredText;
import static com.kinlin.ai.projection.common.mapper.QueryWire.text;

/**
 * Pure whitelist mapping from the agentos_v2.py {@code get_identity_health} wire to
 * the typed public health DTO. No I/O, no recomputation: counters and the degraded
 * status stay exactly as the upstream computed them.
 */
public final class IdentityProjectionMapper {
    private IdentityProjectionMapper() {
    }

    public static IdentityHealthQuery identityHealth(Map<String, Object> wire) {
        return new IdentityHealthQuery(
                requiredText(wire, "status"),
                requiredText(wire, "source"),
                requiredNonNegativeLong(wire, "backlogCount"),
                requiredNonNegativeLong(wire, "failedCount"),
                text(wire, "oldestEventAt"),
                requiredNonNegativeLong(wire, "unappliedEventCount"),
                requiredNonNegativeLong(wire, "inboxBacklog"),
                requiredNonNegativeLong(wire, "outboxBacklog"),
                startup(object(wire.get("startupReconciliation"))));
    }

    private static IdentityHealthQuery.StartupReconciliationQuery startup(Map<?, ?> raw) {
        return new IdentityHealthQuery.StartupReconciliationQuery(
                requiredNonNegativeLong(raw, "examinedMissions"),
                requiredNonNegativeLong(raw, "examinedRuns"),
                requiredNonNegativeLong(raw, "repairedMissions"),
                requiredNonNegativeLong(raw, "repairedRuns"),
                requiredNonNegativeLong(raw, "replayedEvents"),
                requiredNonNegativeLong(raw, "failureCount"));
    }

    private static long requiredNonNegativeLong(Map<?, ?> source, String key) {
        if (!(source.get(key) instanceof Number value)) {
            throw invalid();
        }
        long result = new java.math.BigDecimal(value.toString()).longValueExact();
        if (result < 0) {
            throw invalid();
        }
        return result;
    }
}
