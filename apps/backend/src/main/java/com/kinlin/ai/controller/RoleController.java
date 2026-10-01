package com.kinlin.ai.controller;

import com.kinlin.ai.dto.RoleCreateRequest;
import com.kinlin.ai.entity.Role;
import com.kinlin.ai.projection.role.dto.RoleContextQuery;
import com.kinlin.ai.projection.role.dto.RoleQuery;
import com.kinlin.ai.projection.role.mapper.RoleProjectionMapper;
import com.kinlin.ai.security.AuthenticatedUser;
import com.kinlin.ai.service.RoleService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

/**
 * 角色控制器
 */
@RestController
@RequestMapping("/roles")
@RequiredArgsConstructor
public class RoleController {

    private final RoleService roleService;
    private final com.kinlin.ai.service.RoleSwitchOptimizer roleSwitchOptimizer;

    /**
     * 获取内置角色列表
     */
    @GetMapping("/builtin")
    public ResponseEntity<List<RoleQuery>> getBuiltinRoles() {
        List<Role> roles = roleService.getBuiltinRoles();
        return ResponseEntity.ok(roles.stream().map(RoleProjectionMapper::toQuery).toList());
    }

    /**
     * 获取自定义角色列表
     */
    @GetMapping("/custom")
    public ResponseEntity<List<RoleQuery>> getCustomRoles() {
        UUID userId = resolveUserId();
        List<Role> roles = roleService.getCustomRoles(userId);
        return ResponseEntity.ok(roles.stream().map(RoleProjectionMapper::toQuery).toList());
    }

    /**
     * 获取角色详情（使用缓存优化）
     */
    @GetMapping("/{roleId}")
    public ResponseEntity<RoleQuery> getRole(@PathVariable UUID roleId) {
        try {
            Role role = roleSwitchOptimizer.getRoleCached(roleId);
            return ResponseEntity.ok(RoleProjectionMapper.toQuery(role));
        } catch (RuntimeException e) {
            return ResponseEntity.notFound().build();
        }
    }
    
    /**
     * 获取角色上下文（快速访问）
     */
    @GetMapping("/{roleId}/context")
    public ResponseEntity<RoleContextQuery> getRoleContext(@PathVariable UUID roleId) {
        try {
            return ResponseEntity.ok(RoleProjectionMapper.toContext(roleSwitchOptimizer.getRoleContext(roleId)));
        } catch (RuntimeException e) {
            return ResponseEntity.notFound().build();
        }
    }

    /**
     * 创建自定义角色
     */
    @PostMapping("/custom")
    public ResponseEntity<RoleQuery> createRole(
            @Valid @RequestBody RoleCreateRequest request
    ) {
        UUID userId = resolveUserId();
        Role role = roleService.createRole(request, userId);
        return ResponseEntity.status(HttpStatus.CREATED).body(RoleProjectionMapper.toQuery(role));
    }

    /**
     * 更新角色
     */
    @PutMapping("/{roleId}")
    public ResponseEntity<RoleQuery> updateRole(
            @PathVariable UUID roleId,
            @Valid @RequestBody RoleCreateRequest request
    ) {
        UUID userId = resolveUserId();
        return roleService.updateRole(roleId, request, userId)
                .map(RoleProjectionMapper::toQuery)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    /**
     * 删除角色
     */
    @DeleteMapping("/{roleId}")
    public ResponseEntity<Void> deleteRole(
            @PathVariable UUID roleId
    ) {
        UUID userId = resolveUserId();
        if (roleService.deleteRole(roleId, userId)) {
            return ResponseEntity.ok().build();
        }
        return ResponseEntity.notFound().build();
    }

    /**
     * X-User-Id 请求头已被 SensitiveIdentityHeaderFilter 剥离，一律以认证身份为准。
     */
    private UUID resolveUserId() {
        return AuthenticatedUser.currentUserId().orElse(null);
    }
}
