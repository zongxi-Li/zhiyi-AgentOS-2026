package com.kinlin.ai.gateway;

import org.springframework.web.util.UriUtils;

import java.nio.charset.StandardCharsets;
import java.util.Map;

/**
 * Single definition of the AgentOS v2 upstream path family.
 *
 * <p>J1.1 boundary: the AgentOS northbound upstream is reachable only through the
 * single transport family (AgentOsGatewayService for commands/queries, AiSseGatewayService
 * for the event stream). The path literal lives here and nowhere else; the architecture
 * guard enforces that.</p>
 *
 * <p>J1.2B: the upstream path family is built here, so web controllers project their
 * public routes onto named upstream paths without owning any path literal or identity
 * encoding themselves. Leaf action suffixes (cancel, retry, download…) stay at the one
 * controller that owns the action.</p>
 */
public final class AgentOsPaths {

    /** Upstream root served by the Python AgentOS core. */
    public static final String UPSTREAM_ROOT = "/ai/agentos/v2";

    private AgentOsPaths() {
    }

    /** Percent-encodes one upstream identity segment; ids arrive as raw request data. */
    public static String segment(String value) {
        return UriUtils.encodePathSegment(value, StandardCharsets.UTF_8);
    }

    /** Appends only non-blank params in insertion order, matching the upstream query contract. */
    public static String query(String basePath, Map<String, String> params) {
        StringBuilder result = new StringBuilder(basePath);
        boolean first = true;
        for (Map.Entry<String, String> entry : params.entrySet()) {
            if (entry.getValue() == null || entry.getValue().isBlank()) {
                continue;
            }
            result.append(first ? '?' : '&');
            first = false;
            result.append(entry.getKey()).append('=')
                    .append(UriUtils.encodeQueryParam(entry.getValue(), StandardCharsets.UTF_8));
        }
        return result.toString();
    }

    public static String missions() {
        return UPSTREAM_ROOT + "/missions";
    }

    public static String nodes() {
        return UPSTREAM_ROOT + "/nodes";
    }

    public static String mission(String missionId) {
        return missions() + "/" + segment(missionId);
    }

    public static String missionRuns(String missionId) {
        return mission(missionId) + "/runs";
    }

    public static String runs() {
        return UPSTREAM_ROOT + "/runs";
    }

    /** One catalog resource's upstream sub-action path (usage/history/enabled/probe…). */
    public static String resource(String resourceId) {
        return resources() + "/" + segment(resourceId);
    }

    public static String run(String runId) {
        return runs() + "/" + segment(runId);
    }

    public static String step(String runId, String stepId) {
        return run(runId) + "/steps/" + segment(stepId);
    }

    public static String artifact(String runId, String manifestId) {
        return run(runId) + "/artifacts/" + segment(manifestId);
    }

    public static String output(String runId, String outputRef) {
        return run(runId) + "/outputs/" + segment(outputRef);
    }

    public static String materials() {
        return UPSTREAM_ROOT + "/materials";
    }

    public static String material(String manifestId) {
        return materials() + "/" + segment(manifestId);
    }

    public static String resources() {
        return UPSTREAM_ROOT + "/resources";
    }

    public static String attachments() {
        return UPSTREAM_ROOT + "/attachments";
    }

    public static String attachment(String attachmentId) {
        return attachments() + "/" + segment(attachmentId);
    }

    public static String identityHealth() {
        return UPSTREAM_ROOT + "/identity/health";
    }
}
