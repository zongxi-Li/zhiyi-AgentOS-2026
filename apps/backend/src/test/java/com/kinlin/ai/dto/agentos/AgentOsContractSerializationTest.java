package com.kinlin.ai.dto.agentos;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertFalse;

class AgentOsContractSerializationTest {

    private final ObjectMapper mapper = new ObjectMapper().findAndRegisterModules();
    private final Path fixtures = Path.of("..", "..", "contracts", "agentos-v2");

    @Test
    void decodesAndReencodesPythonControlFixtures() throws Exception {
        AgentOsMissionResponse mission = read("mission-response.json", AgentOsMissionResponse.class);
        AgentOsRunResponse run = read("run-response.json", AgentOsRunResponse.class);
        AgentOsReviewResponse review = read("review-response.json", AgentOsReviewResponse.class);
        AgentOsRetryRequest retry = read("retry-request.json", AgentOsRetryRequest.class);
        AgentOsErrorResponse error = read("error-response.json", AgentOsErrorResponse.class);

        assertEquals("mission_contract_001", mission.missionId());
        assertEquals(AgentOsRunStatus.WAITING_REVIEW, run.status());
        assertNull(run.supersededByRunId());
        assertEquals("review-operation-001", review.operationId());
        assertEquals("successor_run", retry.mode());
        assertEquals("AGENTOS_CONFLICT", error.code());

        JsonNode original = mapper.readTree(Files.readString(fixtures.resolve("run-response.json")));
        JsonNode encoded = mapper.readTree(mapper.writeValueAsString(run));
        for (String field : new String[]{"runId", "missionId", "workflowId", "status", "lifecyclePhase"}) {
            assertEquals(original.get(field), encoded.get(field));
        }
    }

    @Test
    void rejectsMissingRequiredFieldsEnumDriftAndInternalFields() throws Exception {
        JsonNode canonical = mapper.readTree(Files.readString(fixtures.resolve("run-response.json")));

        JsonNode missingRunId = canonical.deepCopy();
        ((com.fasterxml.jackson.databind.node.ObjectNode) missingRunId).remove("runId");
        assertThrows(Exception.class, () -> mapper.treeToValue(missingRunId, AgentOsRunResponse.class));

        JsonNode enumDrift = canonical.deepCopy();
        ((com.fasterxml.jackson.databind.node.ObjectNode) enumDrift).put("status", "paused");
        assertThrows(Exception.class, () -> mapper.treeToValue(enumDrift, AgentOsRunResponse.class));

        JsonNode internal = canonical.deepCopy();
        ((com.fasterxml.jackson.databind.node.ObjectNode) internal).putObject("executionBindings");
        assertThrows(Exception.class, () -> mapper.treeToValue(internal, AgentOsRunResponse.class));
    }

    @Test
    void coreDtoSurfaceContainsNoInternalAcgAuthority() {
        Class<?>[] coreTypes = {
                AgentOsMissionResponse.class, AgentOsMissionSummary.class,
                AgentOsRunResponse.class, AgentOsRunSummary.class,
                AgentOsReviewRequest.class, AgentOsReviewResponse.class,
                AgentOsRetryRequest.class, AgentOsOperationResponse.class
        };
        String[] forbidden = {
                "taskPlan", "graphPatch", "compiledACGPackage", "bindingManifest",
                "bindingRequirements", "executionBindings", "resourcePlan", "resourceId", "workerId"
        };
        for (Class<?> type : coreTypes) {
            for (java.lang.reflect.RecordComponent component : type.getRecordComponents()) {
                for (String name : forbidden) {
                    assertFalse(component.getName().equalsIgnoreCase(name),
                            () -> type.getSimpleName() + " exposes " + component.getName());
                }
            }
        }
    }

    private <T> T read(String name, Class<T> type) throws Exception {
        return mapper.readValue(Files.readString(fixtures.resolve(name)), type);
    }
}
