package com.kinlin.ai.controller;

import com.kinlin.ai.client.AgentOsClient;
import com.kinlin.ai.dto.agentos.AgentOsApiResponse;
import com.kinlin.ai.dto.agentos.AgentOsReviewRequest;
import com.kinlin.ai.dto.agentos.AgentOsReviewResponse;
import com.kinlin.ai.dto.agentos.AgentOsRetryRequest;
import com.kinlin.ai.dto.agentos.AgentOsRunResponse;
import com.kinlin.ai.gateway.AgentOsPaths;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * REVIEW_RECOVERY ownership: review read / apply and the failed-step retry.
 * Review application is the gate between waiting_review and continuation;
 * retry spawns recovery runs — the same recovery lifecycle.
 */
@RestController
@RequestMapping("/api/agentos/v2")
public class AgentOsReviewController {

    private final AgentOsClient gateway;

    public AgentOsReviewController(AgentOsClient gateway) {
        this.gateway = gateway;
    }

    @GetMapping("/runs/{runId}/reviews")
    public ResponseEntity<Map<String, Object>> getReviews(@PathVariable String runId) {
        return AgentOsControllerSupport.response(
                gateway.get(AgentOsPaths.run(runId) + "/reviews"));
    }

    @PostMapping("/runs/{runId}/reviews")
    public ResponseEntity<? extends AgentOsApiResponse> applyReview(
            @PathVariable String runId,
            @Valid @RequestBody AgentOsReviewRequest body
    ) {
        return AgentOsControllerSupport.typedResponse(gateway.postTyped(
                AgentOsPaths.run(runId) + "/reviews", body, AgentOsReviewResponse.class
        ));
    }

    @PostMapping("/runs/{runId}/steps/{stepId}/retry")
    public ResponseEntity<? extends AgentOsApiResponse> retryRunStep(
            @PathVariable String runId,
            @PathVariable String stepId,
            @Valid @RequestBody AgentOsRetryRequest body
    ) {
        return AgentOsControllerSupport.typedResponse(gateway.postTyped(
                AgentOsPaths.step(runId, stepId) + "/retry",
                body,
                AgentOsRunResponse.class
        ));
    }
}
