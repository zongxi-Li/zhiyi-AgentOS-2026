package com.kinlin.ai.projection.history.mapper;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.kinlin.ai.projection.common.mapper.QueryWire;
import com.kinlin.ai.projection.history.dto.HistoryConfigQuery;
import com.kinlin.ai.projection.history.dto.HistoryInputQuery;
import com.kinlin.ai.projection.history.dto.HistoryPluginDataQuery;
import com.kinlin.ai.projection.history.dto.HistoryPluginEntryQuery;

import static com.kinlin.ai.projection.common.mapper.QueryWire.bool;
import static com.kinlin.ai.projection.common.mapper.QueryWire.integer;
import static com.kinlin.ai.projection.common.mapper.QueryWire.invalid;
import static com.kinlin.ai.projection.common.mapper.QueryWire.object;
import static com.kinlin.ai.projection.common.mapper.QueryWire.requiredText;
import static com.kinlin.ai.projection.common.mapper.QueryWire.text;
import static com.kinlin.ai.projection.common.mapper.QueryWire.texts;

/**
 * Pure whitelist mapping from the agentos_v2.py {@code get_history_config} wire to
 * the typed reopen configuration. No I/O, no recomputation: the upstream endpoint
 * already bounds values (23-key whitelist, sensitive-key filtering, 100-item caps)
 * and this mapper only drops the keys with no verified frontend reader.
 */
public final class HistoryConfigProjectionMapper {
    private HistoryConfigProjectionMapper() {
    }

    public static HistoryConfigQuery historyConfig(Map<String, Object> wire) {
        return new HistoryConfigQuery(
                requiredText(wire, "runId"),
                text(wire, "title"),
                text(wire, "reviewMode"),
                texts(wire.get("enabledPluginIds")),
                input(object(wire.get("input"))));
    }

    private static HistoryInputQuery input(Map<?, ?> raw) {
        return new HistoryInputQuery(
                text(raw, "taskGoal"),
                text(raw, "userIntent"),
                text(raw, "materialText"),
                text(raw, "contractText"),
                texts(raw.get("materialIds")),
                texts(raw.get("constraints")),
                texts(raw.get("expectedArtifacts")),
                text(raw, "planningMode"),
                text(raw, "planningDiversity"),
                text(raw, "capabilityProfile"),
                text(raw, "thinkingMode"),
                text(raw, "reasoningEffort"),
                integer(raw, "planningSeed"),
                bool(raw, "webSearchEnabled"),
                pluginData(raw.get("pluginData")));
    }

    private static List<HistoryPluginDataQuery> pluginData(Object raw) {
        if (raw == null) {
            return null;
        }
        if (!(raw instanceof Map<?, ?> map)) {
            throw invalid();
        }
        List<HistoryPluginDataQuery> blocks = new ArrayList<>();
        for (Map.Entry<?, ?> entry : map.entrySet()) {
            if (!(entry.getKey() instanceof String pluginId) || pluginId.isBlank()
                    || !(entry.getValue() instanceof Map<?, ?> fields)) {
                continue;
            }
            List<HistoryPluginEntryQuery> entries = new ArrayList<>();
            for (Map.Entry<?, ?> field : fields.entrySet()) {
                if (!(field.getKey() instanceof String name) || name.isBlank()) {
                    continue;
                }
                HistoryPluginEntryQuery scalar = scalarEntry(name, field.getValue());
                if (scalar != null) {
                    entries.add(scalar);
                }
            }
            if (!entries.isEmpty()) {
                blocks.add(new HistoryPluginDataQuery(pluginId, entries));
            }
        }
        return blocks.isEmpty() ? null : blocks;
    }

    private static HistoryPluginEntryQuery scalarEntry(String name, Object value) {
        if (value instanceof String text) {
            return new HistoryPluginEntryQuery(name, text, null, null);
        }
        if (value instanceof Boolean bool) {
            return new HistoryPluginEntryQuery(name, null, bool, null);
        }
        if (value instanceof Number number) {
            return new HistoryPluginEntryQuery(name, null, null, new BigDecimal(number.toString()));
        }
        return null;
    }
}
