package com.kinlin.ai.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.client.AgentOsClient;
import com.kinlin.ai.exception.AgentOsGatewayExceptionHandler;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * ARTIFACT_MATERIAL ownership: materials, composition resources, artifacts
 * (metadata / fragments / binary download), outputs and attachments.
 */
class AgentOsArtifactControllerTest {

    private MockMvc mockMvc;
    private ObjectMapper objectMapper;
    private RecordingAgentOsGateway gateway;

    @BeforeEach
    void setUp() {
        objectMapper = new ObjectMapper();
        gateway = new RecordingAgentOsGateway();
        mockMvc = MockMvcBuilders.standaloneSetup(new AgentOsArtifactController(gateway))
                .setControllerAdvice(new AgentOsGatewayExceptionHandler())
                .build();
    }

    @Test
    void materialManifestEndpointsPreserveCompleteContentAndReferences() throws Exception {
        String materialPath = "/ai/agentos/v2/materials";
        gateway.postResponses.put(materialPath, RecordingAgentOsGateway.response(201, Map.of(
                "manifestId", "manifest_001", "sealed", true
        )));

        String material = "完整材料".repeat(2000);
        mockMvc.perform(post("/api/agentos/v2/materials")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "content", material,
                                "mediaType", "text/plain"
                        ))))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.manifestId").value("manifest_001"));

        assertEquals(materialPath, gateway.lastPostPath);
        com.kinlin.ai.dto.agentos.AgentOsMaterialCreateRequest request =
                (com.kinlin.ai.dto.agentos.AgentOsMaterialCreateRequest) gateway.lastPostBody;
        assertEquals(material, request.content());

        String getPath = "/ai/agentos/v2/materials/manifest%20001";
        gateway.getResponses.put(getPath, RecordingAgentOsGateway.response(200, Map.of("manifestId", "manifest 001")));
        mockMvc.perform(get("/api/agentos/v2/materials/{manifestId}", "manifest 001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.manifestId").value("manifest 001"));
        assertEquals(getPath, gateway.lastGetPath);
    }

    @Test
    void compositionResourcesListAndRegisterStraightThroughTheGateway() throws Exception {
        gateway.getResponses.put("/ai/agentos/v2/resources", RecordingAgentOsGateway.response(200, Map.of(
                "items", List.of(), "total", 0
        )));
        mockMvc.perform(get("/api/agentos/v2/resources"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(0));
        assertEquals("/ai/agentos/v2/resources", gateway.lastGetPath);

        gateway.postResponses.put("/ai/agentos/v2/resources/register", RecordingAgentOsGateway.response(201, Map.of(
                "resourceId", "resource_001"
        )));
        mockMvc.perform(post("/api/agentos/v2/resources/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of("name", "判例库"))))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.resourceId").value("resource_001"));
        assertEquals("/ai/agentos/v2/resources/register", gateway.lastPostPath);
    }

    @Test
    void artifactMetadataAndFragmentsKeepUpstreamPagination() throws Exception {
        String fragmentsPath = "/ai/agentos/v2/runs/run%20001/artifacts/manifest%20001/fragments"
                + "?cursor=5&pageSize=10";
        gateway.getResponses.put(fragmentsPath, RecordingAgentOsGateway.response(200, Map.of("items", List.of())));
        mockMvc.perform(get(
                        "/api/agentos/v2/runs/{runId}/artifacts/{manifestId}/fragments",
                        "run 001", "manifest 001"
                ).param("cursor", "5").param("pageSize", "10"))
                .andExpect(status().isOk());
        assertEquals(fragmentsPath, gateway.lastGetPath);

        String listPath = "/ai/agentos/v2/runs/run_001/artifacts";
        gateway.getResponses.put(listPath, RecordingAgentOsGateway.response(200, Map.of(
                "items", List.of(Map.of("manifestId", "manifest_001")))));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/artifacts", "run_001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items[0].manifestId").value("manifest_001"));
        assertEquals(listPath, gateway.lastGetPath);

        String singlePath = "/ai/agentos/v2/runs/run_001/artifacts/manifest_001";
        gateway.getResponses.put(singlePath, RecordingAgentOsGateway.response(200, Map.of(
                "manifestId", "manifest_001", "mediaType", "text/plain")));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/artifacts/{manifestId}", "run_001", "manifest_001"))
                .andExpect(status().isOk());
        assertEquals(singlePath, gateway.lastGetPath);
    }

    @Test
    void artifactDownloadProjectsBinaryHeadersStatusAndBodyUnchanged() throws Exception {
        byte[] payload = "PDF内容".getBytes();
        gateway.nextBinary = new AgentOsClient.BinaryResponse(
                200, payload, "application/pdf", "attachment; filename=\"report.pdf\"");

        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/artifacts/{manifestId}/download", "run_001", "manifest_001"))
                .andExpect(status().isOk())
                .andExpect(header().string("Content-Type", "application/pdf"))
                .andExpect(header().string("Content-Disposition", "attachment; filename=\"report.pdf\""))
                .andExpect(result -> assertArrayEquals(payload, result.getResponse().getContentAsByteArray()));

        assertEquals("/ai/agentos/v2/runs/run_001/artifacts/manifest_001/download", gateway.lastGetPath);
    }

    @Test
    void artifactDownloadFallsBackToOctetStreamOnUnparseableContentType() throws Exception {
        gateway.nextBinary = new AgentOsClient.BinaryResponse(
                200, new byte[]{1}, "not a media type", null);

        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/artifacts/{manifestId}/download", "run_001", "manifest_001"))
                .andExpect(status().isOk())
                .andExpect(header().string("Content-Type", "application/octet-stream"))
                .andExpect(header().doesNotExist("Content-Disposition"));
    }

    @Test
    void artifactDownloadKeepsTheUpstreamErrorStatusAndBody() throws Exception {
        gateway.nextBinary = new AgentOsClient.BinaryResponse(
                404, "artifact gone".getBytes(), "text/plain", null);

        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/artifacts/{manifestId}/download", "run_001", "manifest_001"))
                .andExpect(status().isNotFound())
                .andExpect(result -> assertArrayEquals(
                        "artifact gone".getBytes(), result.getResponse().getContentAsByteArray()));
    }

    @Test
    void outputRefsUseOwnedSubresourcePathsWithIdentityEncoding() throws Exception {
        String outputPath = "/ai/agentos/v2/runs/run_001/outputs/output:run_001:report:hash";
        gateway.getResponses.put(outputPath, RecordingAgentOsGateway.response(200, Map.of("outputRef", "output:run_001:report:hash")));
        mockMvc.perform(get("/api/agentos/v2/runs/run_001/outputs/output:run_001:report:hash"))
                .andExpect(status().isOk());
        assertEquals(outputPath, gateway.lastGetPath);

        String legacyOutputPath = "/ai/agentos/v2/runs/run_001/legacy-outputs";
        gateway.getResponses.put(legacyOutputPath, RecordingAgentOsGateway.response(200, Map.of(
                "runId", "run_001", "items", List.of())));
        mockMvc.perform(get("/api/agentos/v2/runs/run_001/legacy-outputs"))
                .andExpect(status().isOk());
        assertEquals(legacyOutputPath, gateway.lastGetPath);
    }

    @Test
    void attachmentLifecycleUploadsReadsAndDeletes() throws Exception {
        MockMultipartFile file = new MockMultipartFile(
                "file", "证据材料.pdf", MediaType.APPLICATION_PDF_VALUE, "附件内容".getBytes());
        gateway.postResponses.put("/ai/agentos/v2/attachments", RecordingAgentOsGateway.response(201, Map.of(
                "attachmentId", "attachment_001"
        )));

        mockMvc.perform(multipart("/api/agentos/v2/attachments").file(file))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.attachmentId").value("attachment_001"));
        assertEquals("/ai/agentos/v2/attachments", gateway.lastPostPath);
        assertEquals("证据材料.pdf", gateway.lastMultipart.getOriginalFilename());

        String getPath = "/ai/agentos/v2/attachments/attachment%20001";
        gateway.getResponses.put(getPath, RecordingAgentOsGateway.response(200, Map.of("attachmentId", "attachment 001")));
        mockMvc.perform(get("/api/agentos/v2/attachments/{attachmentId}", "attachment 001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.attachmentId").value("attachment 001"));
        assertEquals(getPath, gateway.lastGetPath);

        String deletePath = "/ai/agentos/v2/attachments/attachment%20001";
        gateway.deleteResponses.put(deletePath, RecordingAgentOsGateway.response(200, Map.of("deleted", true)));
        mockMvc.perform(delete("/api/agentos/v2/attachments/{attachmentId}", "attachment 001"))
                .andExpect(status().isOk());
        assertEquals(deletePath, gateway.lastDeletePath);
    }
}
