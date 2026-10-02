package com.kinlin.ai.projection.artifact.mapper;

import com.kinlin.ai.projection.artifact.dto.ArtifactDetailQuery;
import com.kinlin.ai.projection.artifact.dto.ArtifactFragmentPageQuery;
import com.kinlin.ai.projection.artifact.dto.ArtifactFragmentQuery;
import com.kinlin.ai.projection.artifact.dto.ArtifactPageQuery;

import java.time.DateTimeException;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.function.Function;

/** Pure whitelist mapping from existing client wire results. No I/O or state authority. */
public final class ArtifactProjectionMapper {
    private ArtifactProjectionMapper() { }

    public static ArtifactPageQuery page(Map<String, Object> wire) {
        return new ArtifactPageQuery(text(wire, "runId"),
                items(wire.get("items"), ArtifactProjectionMapper::row),
                nonNegativeLong(wire, "total"));
    }

    /**
     * The upstream wire is already merged (manifest → artifact → binding, later keys win on
     * the identity path; manifest-only rows on the fallback). Identity fields are required
     * exactly when the merged row carries an artifactId.
     */
    public static ArtifactDetailQuery detail(Map<String, Object> wire) {
        return row(wire);
    }

    private static ArtifactDetailQuery row(Map<?, ?> wire) {
        String artifactId = optionalText(wire, "artifactId");
        boolean identity = artifactId != null;
        return new ArtifactDetailQuery(
                text(wire, "manifestId"), text(wire, "kind"), text(wire, "mediaType"),
                optionalText(wire, "checksum"), nonNegativeLong(wire, "byteLength"),
                nonNegativeInt(wire, "fragmentCount"), optionalNonNegativeLong(wire, "estimatedTokens"),
                bool(wire, "sealed"), time(wire, "createdAt"),
                artifactId,
                identity ? text(wire, "missionId") : null,
                identity ? text(wire, "originRunId") : null,
                identity ? text(wire, "taskId") : null,
                identity ? text(wire, "semanticTaskKey") : null,
                identity ? text(wire, "artifactKey") : null,
                identity ? text(wire, "acgNodeId") : null,
                identity ? text(wire, "producerAttemptId") : null,
                identity ? text(wire, "name") : null,
                identity ? text(wire, "artifactType") : null,
                identity ? text(wire, "contentRef") : null,
                identity ? text(wire, "runId") : null,
                identity ? text(wire, "disposition") : null,
                identity ? optionalText(wire, "sourceRunId") : null);
    }

    public static ArtifactFragmentPageQuery fragmentPage(Map<String, Object> wire) {
        return new ArtifactFragmentPageQuery(
                row(object(wire.get("manifest"))),
                items(wire.get("items"), ArtifactProjectionMapper::fragment),
                optionalText(wire, "nextCursor"));
    }

    private static ArtifactFragmentQuery fragment(Map<?, ?> row) {
        return new ArtifactFragmentQuery(
                text(row, "fragmentId"), text(row, "manifestId"), nonNegativeInt(row, "sequence"),
                text(row, "checksum"), nonNegativeLong(row, "byteLength"),
                optionalNonNegativeLong(row, "estimatedTokens"),
                stringList(row.get("sourceRefs")), stringList(row.get("constraintRefs")),
                text(row, "verificationStatus"), bool(row, "complete"), text(row, "content"));
    }

    private static String text(Map<?, ?> source, String field) {
        if (source.get(field) instanceof String value) { return value; }
        throw invalid();
    }

    private static String optionalText(Map<?, ?> source, String field) {
        return source.get(field) == null ? null : text(source, field);
    }

    private static String time(Map<?, ?> source, String field) {
        String value = text(source, field);
        try { OffsetDateTime.parse(value); }
        catch (DateTimeException invalidTime) { throw invalid(); }
        return value; // Preserve upstream offset and precision instead of reformatting it.
    }

    private static boolean bool(Map<?, ?> source, String field) {
        if (source.get(field) instanceof Boolean value) { return value; }
        throw invalid();
    }

    private static int nonNegativeInt(Map<?, ?> source, String field) {
        if (!(source.get(field) instanceof Number value)) { throw invalid(); }
        int result = new java.math.BigDecimal(value.toString()).intValueExact();
        if (result < 0) { throw invalid(); }
        return result;
    }

    private static long nonNegativeLong(Map<?, ?> source, String field) {
        if (!(source.get(field) instanceof Number value)) { throw invalid(); }
        long result = exact(value).longValueExact();
        if (result < 0) { throw invalid(); }
        return result;
    }

    private static Long optionalNonNegativeLong(Map<?, ?> source, String field) {
        return source.get(field) == null ? null : nonNegativeLong(source, field);
    }

    private static java.math.BigDecimal exact(Number value) {
        // For floating inputs, preserve the actual binary value rather than a rounded decimal string.
        return value instanceof Float || value instanceof Double
                ? new java.math.BigDecimal(value.doubleValue()) : new java.math.BigDecimal(value.toString());
    }

    private static List<String> stringList(Object value) {
        return list(value).stream().map(item -> {
            if (!(item instanceof String entry)) { throw invalid(); }
            return entry;
        }).toList();
    }

    private static Map<?, ?> object(Object value) {
        if (value instanceof Map<?, ?> map) { return map; }
        throw invalid();
    }

    private static List<?> list(Object value) {
        if (value instanceof List<?> list) { return list; }
        throw invalid();
    }

    private static <T> List<T> items(Object value, Function<Map<?, ?>, T> mapper) {
        return list(value).stream().map(item -> mapper.apply(object(item))).toList();
    }

    private static IllegalArgumentException invalid() {
        return new IllegalArgumentException("Invalid Artifact query contract");
    }
}
