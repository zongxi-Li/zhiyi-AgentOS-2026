package com.kinlin.ai.controller;

import com.kinlin.ai.client.AgentOsClient;
import com.kinlin.ai.dto.agentos.AgentOsMaterialCreateRequest;
import com.kinlin.ai.gateway.AgentOsPaths;
import com.kinlin.ai.projection.artifact.mapper.ArtifactProjectionMapper;
import com.kinlin.ai.projection.common.dto.QueryResponse;
import com.kinlin.ai.projection.output.mapper.OutputProjectionMapper;
import jakarta.validation.Valid;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * ARTIFACT_MATERIAL ownership: everything a mission's content payloads need —
 * material manifests, composition resources, run artifacts (metadata, fragments,
 * binary download), output refs and attachments. Binary download keeps the exact
 * upstream Content-Type / Content-Disposition projection.
 */
@RestController
@RequestMapping("/api/agentos/v2")
public class AgentOsArtifactController {

    private final AgentOsClient gateway;

    public AgentOsArtifactController(AgentOsClient gateway) {
        this.gateway = gateway;
    }

    @PostMapping("/materials")
    public ResponseEntity<Map<String, Object>> createMaterial(
            @Valid @RequestBody AgentOsMaterialCreateRequest body
    ) {
        return AgentOsControllerSupport.response(gateway.post(AgentOsPaths.materials(), body));
    }

    @GetMapping("/materials/{manifestId}")
    public ResponseEntity<Map<String, Object>> getMaterial(@PathVariable String manifestId) {
        return AgentOsControllerSupport.response(gateway.get(AgentOsPaths.material(manifestId)));
    }

    @GetMapping("/resources")
    public ResponseEntity<Map<String, Object>> getResources() {
        return AgentOsControllerSupport.response(gateway.get(AgentOsPaths.resources()));
    }

    @PostMapping("/resources/register")
    public ResponseEntity<Map<String, Object>> registerResource(@RequestBody Map<String, Object> body) {
        return AgentOsControllerSupport.response(
                gateway.post(AgentOsPaths.resources() + "/register", body));
    }

    @GetMapping("/runs/{runId}/artifacts")
    public ResponseEntity<QueryResponse> getArtifacts(@PathVariable String runId) {
        return AgentOsControllerSupport.projectedResponse(
                gateway.get(AgentOsPaths.run(runId) + "/artifacts"), ArtifactProjectionMapper::page);
    }

    @GetMapping("/runs/{runId}/artifacts/{manifestId}")
    public ResponseEntity<QueryResponse> getArtifact(
            @PathVariable String runId,
            @PathVariable String manifestId
    ) {
        return AgentOsControllerSupport.projectedResponse(
                gateway.get(AgentOsPaths.artifact(runId, manifestId)), ArtifactProjectionMapper::detail);
    }

    @GetMapping("/runs/{runId}/artifacts/{manifestId}/fragments")
    public ResponseEntity<QueryResponse> getArtifactFragments(
            @PathVariable String runId,
            @PathVariable String manifestId,
            @RequestParam(required = false) String cursor,
            @RequestParam(defaultValue = "20") int pageSize
    ) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("cursor", cursor);
        params.put("pageSize", String.valueOf(pageSize));
        return AgentOsControllerSupport.projectedResponse(gateway.get(AgentOsPaths.query(
                AgentOsPaths.artifact(runId, manifestId) + "/fragments", params)),
                ArtifactProjectionMapper::fragmentPage);
    }

    @GetMapping("/runs/{runId}/artifacts/{manifestId}/download")
    public ResponseEntity<byte[]> downloadArtifact(
            @PathVariable String runId,
            @PathVariable String manifestId
    ) {
        AgentOsClient.BinaryResponse upstream = gateway.getBinary(
                AgentOsPaths.artifact(runId, manifestId) + "/download"
        );
        HttpHeaders headers = new HttpHeaders();
        try {
            headers.setContentType(MediaType.parseMediaType(upstream.contentType()));
        } catch (IllegalArgumentException ignored) {
            headers.setContentType(MediaType.APPLICATION_OCTET_STREAM);
        }
        if (upstream.contentDisposition() != null && !upstream.contentDisposition().isBlank()) {
            headers.set(HttpHeaders.CONTENT_DISPOSITION, upstream.contentDisposition());
        }
        return ResponseEntity.status(upstream.status()).headers(headers).body(upstream.body());
    }

    @GetMapping("/runs/{runId}/outputs/{outputRef}")
    public ResponseEntity<QueryResponse> getOutput(
            @PathVariable String runId,
            @PathVariable String outputRef
    ) {
        return AgentOsControllerSupport.projectedResponse(
                gateway.get(AgentOsPaths.output(runId, outputRef)), OutputProjectionMapper::output);
    }

    @GetMapping("/runs/{runId}/legacy-outputs")
    public ResponseEntity<QueryResponse> getLegacyOutputs(@PathVariable String runId) {
        return AgentOsControllerSupport.projectedResponse(
                gateway.get(AgentOsPaths.run(runId) + "/legacy-outputs"), OutputProjectionMapper::legacyOutputs);
    }

    @PostMapping(value = "/attachments", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<Map<String, Object>> uploadAttachment(
            @RequestParam("file") MultipartFile file
    ) {
        return AgentOsControllerSupport.response(
                gateway.postMultipart(AgentOsPaths.attachments(), file));
    }

    @GetMapping("/attachments/{attachmentId}")
    public ResponseEntity<Map<String, Object>> getAttachment(@PathVariable String attachmentId) {
        return AgentOsControllerSupport.response(gateway.get(AgentOsPaths.attachment(attachmentId)));
    }

    @DeleteMapping("/attachments/{attachmentId}")
    public ResponseEntity<Map<String, Object>> deleteAttachment(@PathVariable String attachmentId) {
        return AgentOsControllerSupport.response(gateway.delete(AgentOsPaths.attachment(attachmentId)));
    }
}
