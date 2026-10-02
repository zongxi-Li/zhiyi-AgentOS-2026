package com.kinlin.ai.projection.workspace.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Workspace diagnostic. {@code severity} is the public info/warning label and {@code code}
 * drives the frontend branch (ProblemsPanel listing, PLANNING_PROJECTION_PENDING banner).
 * {@code details} is a typed whitelist keyed by code — never a copied container — see
 * {@link WorkspaceDiagnosticDetailsQuery} for the per-code field rules.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record WorkspaceDiagnosticQuery(
        String code,
        String message,
        String severity,
        WorkspaceDiagnosticDetailsQuery details
) { }
