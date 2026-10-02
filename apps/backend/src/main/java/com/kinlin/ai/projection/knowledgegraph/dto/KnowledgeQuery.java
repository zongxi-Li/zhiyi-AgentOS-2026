package com.kinlin.ai.projection.knowledgegraph.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;
import java.util.List;

/** Public retrieval and reasoning facts evidenced by knowledgegraphservice.py. */
public final class KnowledgeQuery {
    private KnowledgeQuery() { }
    public record EntityEnvelope(boolean success, EntityDetail data) implements QueryResponse { }
    public record SearchEnvelope(boolean success, Search data) implements QueryResponse { }
    public record ReasonEnvelope(boolean success, Reason data) implements QueryResponse { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record EntityDetail(Entity entity, List<Related> related_entities) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Entity(String id, String type, Properties properties, List<Relation> relations) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Properties(String name, String role_id) { }
    public record Relation(String target, String relation, Double weight) { }
    public record Related(String entity, String relation, Double weight, Properties properties) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record ExtractedEntity(String id, String text, String type, String source, Double confidence, Properties properties) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Search(List<Related> kg_results, List<Vector> vector_results, List<Fused> fused_results,
            List<ExtractedEntity> entities, String error) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Vector(String content, Double score) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Fused(String source, String content, Double score, Properties metadata) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Reason(List<List<List<String>>> reasoning_paths, List<String> conclusions,
            List<ExtractedEntity> entities, List<String> relations, String error) { }
}
