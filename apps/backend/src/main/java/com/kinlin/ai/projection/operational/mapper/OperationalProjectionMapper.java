package com.kinlin.ai.projection.operational.mapper;

import com.kinlin.ai.projection.operational.dto.OperationalQuery;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.time.LocalDateTime;
import static com.kinlin.ai.projection.common.mapper.QueryWire.*;

/** Reads existing diagnostic results only; never executes a probe or writes state. */
public final class OperationalProjectionMapper {
    private OperationalProjectionMapper() { }
    public static OperationalQuery.Token token(Map<String, Object> wire) {
        return new OperationalQuery.Token(bool(wire, "valid"), text(wire, "message"),
                wire.get("userId") instanceof UUID id ? id : null, text(wire, "username"));
    }
    public static OperationalQuery.BasicHealth health(Map<String, Object> wire) {
        return new OperationalQuery.BasicHealth(text(wire, "status"), text(wire, "service"),
                text(wire, "version"), text(wire, "check"));
    }
    public static OperationalQuery.Ready ready(Map<String, Object> wire) {
        var checks = object(wire.get("checks"));
        OperationalQuery.ReadyChecks projected = checks.get("redis") instanceof String
                ? new OperationalQuery.DisabledChecks(bool(checks, "postgres"), text(checks, "redis"), text(checks, "error"))
                : new OperationalQuery.EnabledChecks(bool(checks, "postgres"), bool(checks, "redis"), text(checks, "error"));
        return new OperationalQuery.Ready(text(wire, "status"), projected);
    }
    public static OperationalQuery.Dependencies dependencies(Map<String, Object> wire) {
        var ai = object(object(wire.get("dependencies")).get("aiService"));
        OperationalQuery.PythonHealth detail = null;
        if (ai.get("detail") instanceof Map<?, ?> value) {
            var dependencies = optionalObject(value.get("dependencies"));
            detail = new OperationalQuery.PythonHealth(text(value, "status"), dependencies.isEmpty() ? null
                    : new OperationalQuery.PythonDependencies(state(dependencies.get("modelProvider")),
                            state(dependencies.get("providerConversationState"))));
        }
        return new OperationalQuery.Dependencies(text(wire, "status"), new OperationalQuery.DependencyServices(
                new OperationalQuery.AiService(text(ai, "status"), detail, text(ai, "error"), false)));
    }
    private static OperationalQuery.DependencyState state(Object source) {
        if (source == null) { return null; }
        var wire = object(source);
        return new OperationalQuery.DependencyState(text(wire, "status"), bool(wire, "affectsReadiness"));
    }
    public static OperationalQuery.Metrics metrics(Map<String, Object> wire) {
        return new OperationalQuery.Metrics(decimal(wire, "apiRequests"), decimal(wire, "errors"),
                decimal(wire, "messages"), decimal(wire, "errorRate"));
    }
    public static OperationalQuery.SystemInfo systemInfo(Map<String, Object> wire) {
        return new OperationalQuery.SystemInfo(text(wire, "osName"), text(wire, "osVersion"), text(wire, "osArch"),
                text(wire, "javaVersion"), bool(wire, "isKylinOS"), text(wire, "kylinVersion"));
    }
    public static OperationalQuery.Resources resources(Map<String, Object> wire) {
        var cpu = object(wire.get("cpu"));
        var memory = object(wire.get("memory"));
        OperationalQuery.SystemServices services = null;
        if (wire.get("systemServices") != null) {
            var source = object(wire.get("systemServices"));
            services = new OperationalQuery.SystemServices(text(source, "NetworkManager"), text(source, "firewalld"),
                    text(source, "kylin-security"));
        }
        return new OperationalQuery.Resources(new OperationalQuery.Cpu(smallInt(cpu, "processors")),
                new OperationalQuery.Memory(integer(memory, "total"), integer(memory, "used"), integer(memory, "free"),
                        decimal(memory, "percent")), services);
    }
    public static OperationalQuery.Security security(Map<String, Object> wire) {
        return new OperationalQuery.Security(text(wire, "firewallStatus"), text(wire, "selinuxStatus"), text(wire, "error"));
    }
    public static OperationalQuery.AlertGroup alertGroup(String type, List<OperationalQuery.Alert> alerts) {
        return new OperationalQuery.AlertGroup(type, alerts);
    }
    public static OperationalQuery.Alert alert(String type, String message, String severity, LocalDateTime timestamp) {
        return new OperationalQuery.Alert(type, message, severity, timestamp);
    }
    public static OperationalQuery.File file(String id, String name, String path, long size, String type, String uploadTime) {
        return new OperationalQuery.File(id, name, path, size, type, uploadTime);
    }
}
