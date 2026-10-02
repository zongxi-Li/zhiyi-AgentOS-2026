package com.kinlin.ai.projection.knowledgegraph.mapper;

import com.kinlin.ai.projection.knowledgegraph.dto.KnowledgeQuery;
import java.util.List;
import java.util.Map;
import static com.kinlin.ai.projection.common.mapper.QueryWire.*;

/** Projects already-computed results; never extracts entities or executes graph searches. */
public final class KnowledgeQueryMapper {
    private KnowledgeQueryMapper() { }
    public static KnowledgeQuery.EntityEnvelope entity(Map<String, Object> wire) {
        var source = wire.get("entity");
        KnowledgeQuery.Entity entity = source == null ? null : entityData(object(source));
        return new KnowledgeQuery.EntityEnvelope(true, new KnowledgeQuery.EntityDetail(entity,
                wire.containsKey("related_entities") ? items(wire.get("related_entities"), KnowledgeQueryMapper::related) : null));
    }
    public static KnowledgeQuery.SearchEnvelope search(Map<String, Object> wire) {
        return new KnowledgeQuery.SearchEnvelope(true, new KnowledgeQuery.Search(
                wire.containsKey("kg_results") ? items(wire.get("kg_results"), KnowledgeQueryMapper::related) : null,
                wire.containsKey("vector_results") ? items(wire.get("vector_results"), row -> new KnowledgeQuery.Vector(
                        text(row, "content"), decimal(row, "score"))) : null,
                wire.containsKey("fused_results") ? items(wire.get("fused_results"), row -> new KnowledgeQuery.Fused(
                        text(row, "source"), text(row, "content"), decimal(row, "score"), properties(row.get("metadata")))) : null,
                wire.containsKey("entities") ? items(wire.get("entities"), KnowledgeQueryMapper::extracted) : null,
                text(wire, "error")));
    }
    public static KnowledgeQuery.ReasonEnvelope reason(Map<String, Object> wire) {
        List<List<List<String>>> paths = wire.containsKey("reasoning_paths") ? list(wire.get("reasoning_paths"))
                .stream().map(path -> list(path).stream().map(edge -> {
                    var pair = texts(edge);
                    if (pair.size() != 2) { throw invalid(); }
                    return pair;
                }).toList()).toList() : null;
        return new KnowledgeQuery.ReasonEnvelope(true, new KnowledgeQuery.Reason(paths,
                wire.containsKey("conclusions") ? texts(wire.get("conclusions")) : null,
                wire.containsKey("entities") ? items(wire.get("entities"), KnowledgeQueryMapper::extracted) : null,
                wire.containsKey("relations") ? texts(wire.get("relations")) : null, text(wire, "error")));
    }
    private static KnowledgeQuery.Entity entityData(Map<?, ?> wire) {
        return new KnowledgeQuery.Entity(text(wire, "id"), text(wire, "type"), properties(wire.get("properties")),
                wire.containsKey("relations") ? items(wire.get("relations"), row -> new KnowledgeQuery.Relation(
                        text(row, "target"), text(row, "relation"), decimal(row, "weight"))) : null);
    }
    private static KnowledgeQuery.Related related(Map<?, ?> wire) {
        return new KnowledgeQuery.Related(text(wire, "entity"), text(wire, "relation"), decimal(wire, "weight"), properties(wire.get("properties")));
    }
    private static KnowledgeQuery.ExtractedEntity extracted(Map<?, ?> wire) {
        return new KnowledgeQuery.ExtractedEntity(text(wire, "id"), text(wire, "text"), text(wire, "type"),
                text(wire, "source"), decimal(wire, "confidence"), properties(wire.get("properties")));
    }
    private static KnowledgeQuery.Properties properties(Object source) {
        if (source == null) { return null; }
        var wire = object(source);
        return new KnowledgeQuery.Properties(text(wire, "name"), text(wire, "role_id"));
    }
}
