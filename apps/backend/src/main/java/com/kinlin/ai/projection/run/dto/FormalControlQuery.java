package com.kinlin.ai.projection.run.dto;

/** Public control references only. No executable snapshot, principal or signed ledger. */
public record FormalControlQuery(
        String status, Boolean executionAuthorized, Boolean permitIssued, Boolean dispatchEligible,
        Boolean dispatchEnabled, String commitId, Long commitmentRevision, String materializationId,
        String activationId, String graphId, Integer graphVersion, String handoffId, String handoffStatus,
        String permitId, String permitStatus, DispatchReceipt dispatch
) {
    public record DispatchReceipt(String dispatchId, String runId, String permitId, Integer graphVersion, String status) { }
}
