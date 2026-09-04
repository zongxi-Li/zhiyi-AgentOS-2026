package com.kinlin.ai.service;

import com.kinlin.ai.dto.RoleCreateRequest;
import com.kinlin.ai.entity.Role;
import com.kinlin.ai.repository.RoleRepository;
import com.kinlin.ai.exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * 角色服务类
 */
@Service
@RequiredArgsConstructor
public class RoleService {

    private final RoleRepository roleRepository;
    private final RoleValidationService validationService;

    /**
     * 获取内置角色列表
     */
    public List<Role> getBuiltinRoles() {
        return roleRepository.findByRoleType(Role.RoleType.BUILTIN);
    }

    /**
     * 获取自定义角色列表
     */
    public List<Role> getCustomRoles(UUID userId) {
        if (userId != null) {
            return roleRepository.findByUserId(userId);
        }
        return List.of();
    }

    /**
     * 获取角色详情
     */
    public Optional<Role> getRole(UUID roleId) {
        return roleRepository.findById(roleId);
    }

    /**
     * 创建自定义角色
     */
    @Transactional
    public Role createRole(RoleCreateRequest request, UUID userId) {
        Role role = new Role();
        role.setName(request.getName());
        role.setDescription(request.getDescription());
        role.setRoleType(Role.RoleType.CUSTOM);
        role.setUserId(userId);
        role.setSystemPrompt(request.getSystemPrompt());
        role.setDialogueStyle(request.getDialogueStyle());
        role.setPersonality(request.getPersonality());
        role.setAvatarConfig(request.getAvatarConfig());
        
        // 验证角色配置
        var validationResult = validationService.validateRole(role);
        if (!validationResult.valid()) {
            throw new BusinessException("VALIDATION_ERROR", 
                String.join("; ", validationResult.errors()));
        }
        
        return roleRepository.save(role);
    }

    /**
     * 更新角色
     */
    @Transactional
    public Optional<Role> updateRole(UUID roleId, RoleCreateRequest request, UUID userId) {
        return roleRepository.findById(roleId)
                .filter(role -> role.getRoleType() == Role.RoleType.CUSTOM)
                .filter(role -> userId == null || role.getUserId().equals(userId))
                .map(role -> {
                    role.setName(request.getName());
                    role.setDescription(request.getDescription());
                    role.setSystemPrompt(request.getSystemPrompt());
                    role.setDialogueStyle(request.getDialogueStyle());
                    role.setPersonality(request.getPersonality());
                    role.setAvatarConfig(request.getAvatarConfig());
                    
                    // 验证角色配置
                    var validationResult = validationService.validateRole(role);
                    if (!validationResult.valid()) {
                        throw new BusinessException("VALIDATION_ERROR", 
                            String.join("; ", validationResult.errors()));
                    }
                    
                    return roleRepository.save(role);
                });
    }

    /**
     * 删除角色
     */
    @Transactional
    public boolean deleteRole(UUID roleId, UUID userId) {
        return roleRepository.findById(roleId)
                .filter(role -> role.getRoleType() == Role.RoleType.CUSTOM)
                .filter(role -> userId == null || role.getUserId().equals(userId))
                .map(role -> {
                    roleRepository.delete(role);
                    return true;
                })
                .orElse(false);
    }
}

