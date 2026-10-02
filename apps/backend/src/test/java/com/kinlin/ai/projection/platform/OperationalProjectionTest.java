package com.kinlin.ai.projection.platform;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.operational.mapper.OperationalProjectionMapper;
import com.kinlin.ai.service.AlertService;
import com.kinlin.ai.service.FileService;
import org.junit.jupiter.api.Test;
import java.util.List;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class OperationalProjectionTest {
    private final ObjectMapper json = new ObjectMapper().findAndRegisterModules();

    @Test
    void readinessVariantsKeepBooleansDisabledTextAndPartialFailureKeys() throws Exception {
        for (var source : List.of(
                Map.<String, Object>of("status", "UP", "checks", Map.of("postgres", true, "redis", true)),
                Map.<String, Object>of("status", "UP", "checks", Map.of("postgres", true, "redis", "disabled")),
                Map.<String, Object>of("status", "DOWN", "checks", Map.of("error", "DataAccessException")))) {
            assertEquals(json.valueToTree(source), json.readTree(json.writeValueAsString(OperationalProjectionMapper.ready(source))));
        }
    }

    @Test
    void dependencyDetailProjectsTheActualPythonContractWithoutRawObjects() throws Exception {
        var source = Map.<String, Object>of("status", "REACHABLE", "dependencies", Map.of("aiService", Map.of(
                "status", "REACHABLE", "affectsReadiness", false, "detail", Map.of("status", "UP",
                        "dependencies", Map.of("modelProvider", Map.of("status", "CONFIGURED", "affectsReadiness", false,
                                "internal", "SECRET"), "providerConversationState", Map.of("status", "DISABLED", "affectsReadiness", false)),
                        "runtime", Map.of("binding", "SECRET")))));
        var result = json.readTree(json.writeValueAsString(OperationalProjectionMapper.dependencies(source)));
        assertEquals("CONFIGURED", result.at("/dependencies/aiService/detail/dependencies/modelProvider/status").textValue());
        assertFalse(result.toString().contains("SECRET"));
        assertFalse(result.at("/dependencies/aiService/affectsReadiness").booleanValue());
    }

    @Test
    void systemDiagnosticsPreserveFixedServiceNamesAndExistingErrorShape() throws Exception {
        var source = Map.<String, Object>of("cpu", Map.of("processors", 8), "memory", Map.of("total", 1000,
                "used", 250, "free", 750, "percent", 25.0), "systemServices", Map.of("NetworkManager", "active",
                "firewalld", "inactive", "kylin-security", "unknown", "internal", "SECRET"));
        var result = json.readTree(json.writeValueAsString(OperationalProjectionMapper.resources(source)));
        assertEquals("active", result.at("/systemServices/NetworkManager").textValue());
        assertEquals("unknown", result.at("/systemServices/kylin-security").textValue());
        assertEquals(25.0, result.at("/memory/percent").doubleValue());
        assertFalse(result.toString().contains("SECRET"));
        var error = Map.<String, Object>of("error", "非银河麒麟系统");
        assertEquals(json.valueToTree(error), json.valueToTree(OperationalProjectionMapper.security(error)));
    }

    @Test
    void alertsUseTypedAssociationRowsAndFilesKeepPublicDownloadPaths() throws Exception {
        var alert = new AlertService.Alert();
        alert.setAlertType("warning"); alert.setMessage("公开告警"); alert.setSeverity("info");
        var row = OperationalProjectionMapper.alertGroup("warning", List.of(OperationalProjectionMapper.alert(
                alert.getAlertType(), alert.getMessage(), alert.getSeverity(), alert.getTimestamp())));
        assertEquals("warning", row.alertType());
        assertEquals("公开告警", row.alerts().get(0).message());
        var file = new FileService.FileInfo();
        file.setId("f1"); file.setName("notes.txt"); file.setPath("general/notes.txt"); file.setSize(42);
        assertEquals(json.valueToTree(file), json.valueToTree(OperationalProjectionMapper.file(file.getId(), file.getName(),
                file.getPath(), file.getSize(), file.getType(), file.getUploadTime())));
    }

    @Test
    void platformControllersExposeProjectionsAndPreserveErrorStatuses() throws Exception {
        var kylin = mock(com.kinlin.ai.service.KylinOSIntegrationService.class);
        when(kylin.getSecurityStatus()).thenReturn(Map.of("error", "非银河麒麟系统"));
        var alerts = mock(AlertService.class);
        when(alerts.getAllAlerts()).thenReturn(Map.of("warning", List.of()));
        var files = mock(FileService.class);
        when(files.listFiles("general")).thenThrow(new java.io.IOException("read failed"));
        var mvc = org.springframework.test.web.servlet.setup.MockMvcBuilders.standaloneSetup(
                new com.kinlin.ai.controller.KylinOSController(kylin),
                new com.kinlin.ai.controller.AlertController(alerts),
                new com.kinlin.ai.controller.FileController(files),
                new com.kinlin.ai.controller.AuthController(mock(com.kinlin.ai.service.UserService.class),
                        mock(com.kinlin.ai.util.JwtUtil.class)),
                new com.kinlin.ai.controller.MetricsController(new io.micrometer.core.instrument.simple.SimpleMeterRegistry()))
                .build();
        mvc.perform(get("/api/kylin-os/security")).andExpect(status().isOk())
                .andExpect(jsonPath("$.error").value("非银河麒麟系统"));
        mvc.perform(get("/api/alerts/history")).andExpect(status().isOk())
                .andExpect(jsonPath("$[0].alertType").value("warning")).andExpect(jsonPath("$[0].alerts").isEmpty());
        mvc.perform(get("/files")).andExpect(status().isInternalServerError()).andExpect(content().string(""));
        mvc.perform(get("/auth/verify")).andExpect(status().isOk()).andExpect(jsonPath("$.valid").value(false));
        mvc.perform(get("/metrics")).andExpect(status().isOk()).andExpect(jsonPath("$.apiRequests").value(0.0));
    }
}
