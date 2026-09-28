package com.kinlin.ai.infrastructure.http;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * Canonical owner of the Java-to-Python service root and its transport timeouts.
 *
 * <p>Config keys are unchanged (deployment compatibility): this class only consolidates
 * ownership. Every formal client must take the Python root from this bean.</p>
 *
 * <p>Timeout categories owned here:
 * <ul>
 *   <li>CONNECT — {@code ai.service.connect-timeout}</li>
 *   <li>COMMAND/QUERY (platform-ai family) — {@code ai.service.timeout}</li>
 *   <li>HEALTH_PROBE — {@code ai.service.health-timeout} (default keeps the former
 *       hardcoded 3s probe)</li>
 * </ul>
 * AgentOS-family categories (COMMAND/QUERY/ASYNC_START/PROGRESS) are owned by
 * {@code agent.timeout-ms}/{@code agent.progress-timeout-ms}/{@code agent.async-start-timeout-ms}
 * via {@code AgentProperties}; STREAM_IDLE/STREAM_MAX are owned by {@code ai.sse.*} in
 * {@code AiSseGatewayService}.</p>
 */
@Component
@ConfigurationProperties(prefix = "ai.service")
public class PythonServiceProperties {

    private static final String DEFAULT_URL = "http://localhost:8000";

    private String url = DEFAULT_URL;
    private int connectTimeout = 15000;
    private int timeout = 240000;
    private int healthTimeout = 3000;

    public String getUrl() {
        return url;
    }

    public void setUrl(String url) {
        this.url = url;
    }

    public int getConnectTimeout() {
        return connectTimeout;
    }

    public void setConnectTimeout(int connectTimeout) {
        this.connectTimeout = connectTimeout;
    }

    public int getTimeout() {
        return timeout;
    }

    public void setTimeout(int timeout) {
        this.timeout = timeout;
    }

    public int getHealthTimeout() {
        return healthTimeout;
    }

    public void setHealthTimeout(int healthTimeout) {
        this.healthTimeout = healthTimeout;
    }
}
