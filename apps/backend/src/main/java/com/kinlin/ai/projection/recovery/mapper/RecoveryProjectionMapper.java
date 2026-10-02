package com.kinlin.ai.projection.recovery.mapper;

import java.util.Map;

import com.kinlin.ai.projection.common.mapper.QueryWire;
import com.kinlin.ai.projection.recovery.dto.CheckpointItemQuery;
import com.kinlin.ai.projection.recovery.dto.CheckpointsQuery;

import static com.kinlin.ai.projection.common.mapper.QueryWire.invalid;
import static com.kinlin.ai.projection.common.mapper.QueryWire.items;
import static com.kinlin.ai.projection.common.mapper.QueryWire.requiredText;

/**
 * Pure whitelist mapping from the agentos_v2.py {@code get_checkpoints} wire to the
 * typed recovery-availability DTO. No I/O, no recomputation: canResume and version
 * stay exactly as the runtime computed them.
 */
public final class RecoveryProjectionMapper {
    private RecoveryProjectionMapper() {
    }

    public static CheckpointsQuery checkpoints(Map<String, Object> wire) {
        if (wire.get("items") == null) {
            throw invalid();
        }
        return new CheckpointsQuery(
                requiredText(wire, "runId"),
                items(wire.get("items"), RecoveryProjectionMapper::item),
                requiredNonNegativeLong(wire, "total"));
    }

    private static CheckpointItemQuery item(Map<?, ?> raw) {
        return new CheckpointItemQuery(
                requiredText(raw, "checkpointId"),
                requiredNonNegativeLong(raw, "version"),
                requiredBoolean(raw, "canResume"));
    }

    private static Boolean requiredBoolean(Map<?, ?> source, String key) {
        if (!(source.get(key) instanceof Boolean value)) {
            throw invalid();
        }
        return value;
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
