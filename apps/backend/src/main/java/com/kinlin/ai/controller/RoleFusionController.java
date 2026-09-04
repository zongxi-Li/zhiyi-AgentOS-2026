package com.kinlin.ai.controller;

import com.kinlin.ai.dto.RoleFusionRequest;
import com.kinlin.ai.service.RoleFusionService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 角色融合控制器
 */
@Slf4j
@RestController
@RequestMapping("/api/role-fusion")
@RequiredArgsConstructor
public class RoleFusionController {

    private final RoleFusionService roleFusionService;

    /**
     * 融合多个角色的回答
     */
    @PostMapping("/fuse")
    public ResponseEntity<Map<String, Object>> fuseRoles(
            @Valid @RequestBody RoleFusionRequest request
    ) {
        Map<String, Object> result = roleFusionService.fuseRoles(request);
        return ResponseEntity.ok(result);
    }

    /**
     * 计算角色权重
     */
    @PostMapping("/weights")
    public ResponseEntity<Map<String, Object>> calculateRoleWeights(
            @RequestParam("question") String question,
            @RequestBody List<RoleFusionRequest.RoleInfo> availableRoles
    ) {
        Map<String, Object> result = roleFusionService.calculateRoleWeights(question, availableRoles);
        return ResponseEntity.ok(result);
    }
}

