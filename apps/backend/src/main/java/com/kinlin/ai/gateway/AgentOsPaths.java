package com.kinlin.ai.gateway;

/**
 * Single definition of the AgentOS v2 upstream path family.
 *
 * <p>J1.1 boundary: the AgentOS northbound upstream is reachable only through the
 * single transport family (AgentOsGatewayService for commands/queries, AiSseGatewayService
 * for the event stream). The path literal lives here and nowhere else; the architecture
 * guard enforces that.</p>
 */
public final class AgentOsPaths {

    /** Upstream root served by the Python AgentOS core. */
    public static final String UPSTREAM_ROOT = "/ai/agentos/v2";

    private AgentOsPaths() {
    }
}
