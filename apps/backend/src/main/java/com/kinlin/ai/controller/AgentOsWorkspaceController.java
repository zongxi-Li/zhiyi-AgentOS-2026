package com.kinlin.ai.controller;

import com.kinlin.ai.client.AgentOsClient;
import com.kinlin.ai.gateway.AgentOsPaths;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.Map;

/** Authenticated Gateway transport; Python issues and validates workspace authority. */
@RestController
@RequestMapping("/api/agentos/v2/workspaces")
public class AgentOsWorkspaceController {
    private final AgentOsClient gateway;
    public AgentOsWorkspaceController(AgentOsClient gateway) { this.gateway = gateway; }
    @GetMapping("/current")
    public ResponseEntity<Map<String, Object>> current() {
        return AgentOsControllerSupport.response(gateway.get(AgentOsPaths.UPSTREAM_ROOT + "/workspaces/current"));
    }
    @GetMapping
    public ResponseEntity<Map<String, Object>> list() {
        return AgentOsControllerSupport.response(gateway.get(AgentOsPaths.UPSTREAM_ROOT + "/workspaces"));
    }
    @PostMapping("/select")
    public ResponseEntity<Map<String, Object>> select(@RequestBody Map<String, Object> body) {
        return AgentOsControllerSupport.response(gateway.post(AgentOsPaths.UPSTREAM_ROOT + "/workspaces/select", body));
    }
    @PostMapping("/{workspaceId}/revoke")
    public ResponseEntity<Map<String, Object>> revoke(@PathVariable String workspaceId) {
        return AgentOsControllerSupport.response(gateway.post(AgentOsPaths.UPSTREAM_ROOT + "/workspaces/" + AgentOsPaths.segment(workspaceId) + "/revoke", Map.of()));
    }
}
