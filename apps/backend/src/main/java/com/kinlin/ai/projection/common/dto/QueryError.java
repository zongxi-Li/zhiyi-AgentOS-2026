package com.kinlin.ai.projection.common.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

/** The frozen gateway error fields; absent requestId stays absent on map-based query routes. */
public record QueryError(String code, String message,
                         @JsonInclude(JsonInclude.Include.NON_NULL) String requestId) implements QueryResponse { }
