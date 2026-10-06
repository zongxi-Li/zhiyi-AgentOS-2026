package com.kinlin.ai.projection.resourcecatalog.dto;

import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * Credential metadata of one catalog resource: identity and age only — the secret
 * material exists once, in the registration/rotation response, and never here.
 */
public record ResourceCredentialQuery(
        String resourceId,
        String credentialId,
        String createdAt
) implements QueryResponse { }
