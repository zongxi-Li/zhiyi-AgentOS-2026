package com.kinlin.ai.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * AgentOS runtime properties (J1.3: legacy role-specific {@code agent.python.*}
 * and the zero-reference trace/federated keys are removed).
 */
@Data
@Component
@ConfigurationProperties(prefix = "agent")
public class AgentProperties {

    private boolean enabled = true;

    private int timeoutMs = 240000;

    private int progressTimeoutMs = 5000;

    /** Async preparation should return quickly and must not inherit the sync workflow timeout. */
    private int asyncStartTimeoutMs = 15000;
}
