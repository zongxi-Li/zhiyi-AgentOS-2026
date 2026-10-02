package com.kinlin.ai.projection.resource.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Public model capability snapshot (observed call audit or declared catalog hint).
 *
 * <p>The declared-catalog hint only requires provider OR model to be present, so both stay
 * nullable here; AcgResourceInspector falls back to "API 未声明" and the strip falls back to
 * provider. version/revision/source/contextWindowTokens/maxOutputTokens have direct readers;
 * maxTokensField/features/maxTokensRequired/observedAt do not and are omitted.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ModelCapabilityQuery(
        String provider,
        String model,
        String version,
        String revision,
        String source,
        Long contextWindowTokens,
        Long maxOutputTokens
) {
}
