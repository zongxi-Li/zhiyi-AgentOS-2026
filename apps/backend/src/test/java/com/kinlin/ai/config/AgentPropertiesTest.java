package com.kinlin.ai.config;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * J1.3：legacy role-specific（agent.python.*）与零引用字段（trace-enabled/federated）已删除，
 * 仅保留正式 AgentOS gateway 消费的字段。
 */
class AgentPropertiesTest {

    @Test
    void formalAgentOsFieldsKeepTheirFrozenDefaults() {
        AgentProperties properties = new AgentProperties();

        assertThat(properties.isEnabled()).isTrue();
        assertThat(properties.getTimeoutMs()).isEqualTo(240000);
        assertThat(properties.getProgressTimeoutMs()).isEqualTo(5000);
        assertThat(properties.getAsyncStartTimeoutMs()).isEqualTo(15000);
    }

    @Test
    void formalAgentOsFieldsStayBindable() {
        AgentProperties properties = new AgentProperties();
        properties.setEnabled(false);
        properties.setTimeoutMs(1000);
        properties.setProgressTimeoutMs(2000);
        properties.setAsyncStartTimeoutMs(3000);

        assertThat(properties.isEnabled()).isFalse();
        assertThat(properties.getTimeoutMs()).isEqualTo(1000);
        assertThat(properties.getProgressTimeoutMs()).isEqualTo(2000);
        assertThat(properties.getAsyncStartTimeoutMs()).isEqualTo(3000);
    }
}
