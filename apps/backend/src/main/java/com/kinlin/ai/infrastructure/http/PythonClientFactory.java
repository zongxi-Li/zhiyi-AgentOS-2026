package com.kinlin.ai.infrastructure.http;

import com.kinlin.ai.gateway.AgentOsPaths;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * Sole owner of Python base-URL wiring for formal outbound transports.
 *
 * <p>Builds the single blocking/JSON {@link WebClient} used by every formal client family
 * (AgentOS gateway, platform-AI clients, SSE gateway, AI proxy, health probe) from the
 * shared auth-filtered builder. Business services must never build their own WebClient
 * or resolve the Python root themselves.</p>
 */
@Component
public class PythonClientFactory {

    private final WebClient transport;

    public PythonClientFactory(WebClient.Builder sharedBuilder, PythonServiceProperties properties) {
        this.transport = sharedBuilder.clone().baseUrl(properties.getUrl()).build();
    }

    /** The configured Java-to-Python transport; auth, trace and identity headers come from the shared filter. */
    public WebClient pythonTransport() {
        return transport;
    }

    /** Coarse endpoint family for transport metrics; must stay low-cardinality. */
    public static String endpointFamily(String path) {
        if (path == null) {
            return "other";
        }
        if (path.startsWith(AgentOsPaths.UPSTREAM_ROOT)) {
            return "agentos";
        }
        if (path.startsWith("/health")) {
            return "health";
        }
        if (path.startsWith("/rag/")) {
            return "platform_rag";
        }
        if (path.startsWith("/api/knowledge-graph")) {
            return "platform_knowledge_graph";
        }
        if (path.startsWith("/ai/")) {
            return "platform_proxy";
        }
        return "other";
    }
}
