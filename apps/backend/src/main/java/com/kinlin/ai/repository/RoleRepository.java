package com.kinlin.ai.repository;

import com.kinlin.ai.entity.Role;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

/**
 * 角色数据访问接口
 */
@Repository
public interface RoleRepository extends JpaRepository<Role, UUID> {

    List<Role> findByRoleType(Role.RoleType roleType);

    List<Role> findByUserId(UUID userId);

    List<Role> findByRoleTypeAndUserId(Role.RoleType roleType, UUID userId);
}

