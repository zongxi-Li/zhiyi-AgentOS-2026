package com.kinlin.ai.projection.operational.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.kinlin.ai.projection.common.dto.QueryResponse;
import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

/** Explicit query contracts for existing platform diagnostics, authentication facts and file lists. */
public final class OperationalQuery {
    private OperationalQuery() { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Token(Boolean valid, String message, UUID userId, String username) implements QueryResponse { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record BasicHealth(String status, String service, String version, String check) implements QueryResponse { }
    public record Ready(String status, ReadyChecks checks) implements QueryResponse { }
    public sealed interface ReadyChecks permits EnabledChecks, DisabledChecks { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record EnabledChecks(Boolean postgres, Boolean redis, String error) implements ReadyChecks { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record DisabledChecks(Boolean postgres, String redis, String error) implements ReadyChecks { }
    public record Dependencies(String status, DependencyServices dependencies) implements QueryResponse { }
    public record DependencyServices(AiService aiService) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record AiService(String status, PythonHealth detail, String error, boolean affectsReadiness) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record PythonHealth(String status, PythonDependencies dependencies) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record PythonDependencies(DependencyState modelProvider, DependencyState providerConversationState) { }
    public record DependencyState(String status, Boolean affectsReadiness) { }
    public record Metrics(Double apiRequests, Double errors, Double messages, Double errorRate) implements QueryResponse { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record SystemInfo(String osName, String osVersion, String osArch, String javaVersion,
            Boolean isKylinOS, String kylinVersion) implements QueryResponse { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Resources(Cpu cpu, Memory memory, SystemServices systemServices) implements QueryResponse { }
    public record Cpu(Integer processors) { }
    public record Memory(Long total, Long used, Long free, Double percent) { }
    public record SystemServices(@JsonProperty("NetworkManager") String networkManager,
            String firewalld, @JsonProperty("kylin-security") String kylinSecurity) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Security(String firewallStatus, String selinuxStatus, String error) implements QueryResponse { }
    public record Alert(String alertType, String message, String severity, LocalDateTime timestamp) { }
    public record AlertGroup(String alertType, List<Alert> alerts) { }
    public record File(String id, String name, String path, long size, String type, String uploadTime) { }
}
