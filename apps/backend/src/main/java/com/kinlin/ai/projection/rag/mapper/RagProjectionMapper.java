package com.kinlin.ai.projection.rag.mapper;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.kinlin.ai.projection.common.mapper.QueryWire;
import com.kinlin.ai.projection.rag.dto.RagDocumentPageQuery;
import com.kinlin.ai.projection.rag.dto.RagQueryResponseQuery;

import static com.kinlin.ai.projection.common.mapper.QueryWire.integer;
import static com.kinlin.ai.projection.common.mapper.QueryWire.invalid;
import static com.kinlin.ai.projection.common.mapper.QueryWire.items;
import static com.kinlin.ai.projection.common.mapper.QueryWire.requiredText;

/**
 * Pure whitelist mapping from the RagService outputs to the typed RAG DTOs. No
 * I/O, no recomputation: answers, sources and counters pass through untouched.
 * A mistyped optional source field is omitted, never echoed or fatal.
 */
public final class RagProjectionMapper {
    private RagProjectionMapper() {
    }

    public static RagQueryResponseQuery query(
            String answer, List<Map<String, Object>> sources, Double confidence) {
        if (answer == null) {
            throw invalid();
        }
        List<RagQueryResponseQuery.RagSourceQuery> rows = new ArrayList<>();
        for (Map<String, Object> source : sources == null ? List.<Map<String, Object>>of() : sources) {
            rows.add(new RagQueryResponseQuery.RagSourceQuery(
                    textOrOmit(source, "title"), textOrOmit(source, "url"), textOrOmit(source, "content")));
        }
        return new RagQueryResponseQuery(answer, rows, confidence);
    }

    public static RagDocumentPageQuery documents(Map<String, Object> wire) {
        if (wire.get("documents") == null || !(wire.get("count") instanceof Number)) {
            throw invalid();
        }
        return new RagDocumentPageQuery(
                items(wire.get("documents"), RagProjectionMapper::document),
                integer(wire, "count").longValue());
    }

    private static RagDocumentPageQuery.RagDocumentQuery document(Map<?, ?> raw) {
        return new RagDocumentPageQuery.RagDocumentQuery(
                requiredText(raw, "doc_id"),
                textOrOmit(raw, "filename"),
                textOrOmit(raw, "upload_time"),
                textOrOmit(raw, "role_id"));
    }

    private static String textOrOmit(Map<?, ?> source, String key) {
        return source.get(key) instanceof String value ? value : null;
    }
}
