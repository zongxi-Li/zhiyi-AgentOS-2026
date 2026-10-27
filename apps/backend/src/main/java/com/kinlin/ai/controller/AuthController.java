package com.kinlin.ai.controller;

import com.kinlin.ai.dto.LoginRequest;
import com.kinlin.ai.dto.LoginResponse;
import com.kinlin.ai.entity.LoginSession;
import com.kinlin.ai.entity.User;
import com.kinlin.ai.security.AuthenticatedUser;
import com.kinlin.ai.service.LoginSessionService;
import com.kinlin.ai.service.UserService;
import com.kinlin.ai.util.JwtUtil;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataAccessException;
import org.springframework.http.ResponseEntity;
import com.kinlin.ai.projection.operational.dto.OperationalQuery;
import com.kinlin.ai.projection.operational.mapper.OperationalProjectionMapper;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/**
 * 认证控制器
 * 处理用户登录、注册、登出等认证相关功能
 *
 * <p>INT-2F-4A：登录/注册统一创建持久会话后再签发含 sid 的 JWT；
 * 会话创建失败（503）不得返回有效 Token。POST /auth/logout 仅撤销当前
 * 登录会话；GET /auth/verify 复用同一会话权威，撤销后的 Token 报 invalid。</p>
 */
@Slf4j
@RestController
@RequestMapping("/auth")
@RequiredArgsConstructor
public class AuthController {

    private final UserService userService;
    private final JwtUtil jwtUtil;
    private final LoginSessionService loginSessionService;

    /**
     * 用户登录
     */
    @PostMapping("/login")
    public ResponseEntity<LoginResponse> login(@Valid @RequestBody LoginRequest request) {
        LoginResponse response = new LoginResponse();

        // 验证用户和密码
        Optional<User> userOpt = userService.validateUser(
                request.getUsername(),
                request.getPassword() != null ? request.getPassword() : ""
        );

        if (userOpt.isEmpty()) {
            response.setMessage("用户名或密码错误");
            return ResponseEntity.status(401).body(response);
        }

        User user = userOpt.get();
        String token = issueSessionToken(user, response, "登录成功");
        if (token == null) {
            return ResponseEntity.status(503).body(response);
        }

        return ResponseEntity.ok(response);
    }

    /**
     * 用户注册
     */
    @PostMapping("/register")
    public ResponseEntity<LoginResponse> register(@Valid @RequestBody LoginRequest request) {
        LoginResponse response = new LoginResponse();

        // 验证必填字段
        if (request.getUsername() == null || request.getUsername().trim().isEmpty()) {
            response.setMessage("用户名不能为空");
            return ResponseEntity.badRequest().body(response);
        }

        if (request.getPassword() == null || request.getPassword().trim().isEmpty()) {
            response.setMessage("密码不能为空");
            return ResponseEntity.badRequest().body(response);
        }

        // 检查用户名是否已存在
        if (userService.getUserByUsername(request.getUsername()).isPresent()) {
            response.setMessage("用户名已存在");
            return ResponseEntity.badRequest().body(response);
        }

        try {
            // 创建新用户（密码会自动加密）
            User user = userService.createUser(
                    request.getUsername(),
                    request.getPassword(),
                    request.getEmail()
            );

            String token = issueSessionToken(user, response, "注册成功");
            if (token == null) {
                return ResponseEntity.status(503).body(response);
            }

            return ResponseEntity.ok(response);
        } catch (IllegalArgumentException e) {
            response.setMessage(e.getMessage());
            return ResponseEntity.badRequest().body(response);
        }
    }

    /**
     * 服务端登出：仅撤销当前登录会话（INT-2F-4A）。
     * 必须经过真实认证（SecurityConfig 不放行 /auth/logout）；
     * 撤销提交后原 JWT 不能再访问受保护接口。
     */
    @PostMapping("/logout")
    public ResponseEntity<Void> logout() {
        Optional<com.kinlin.ai.security.AuthenticatedUserContext> context = AuthenticatedUser.currentContext();
        if (context.isEmpty() || context.get().sid() == null) {
            // 无过滤器产生的完整会话上下文（含兼容 principal 分支）：拒绝
            log.warn("Logout rejected: no authenticated session context");
            return ResponseEntity.status(401).build();
        }

        UUID sid = context.get().sid();
        try {
            loginSessionService.revokeBySid(sid);
            return ResponseEntity.noContent().build();
        } catch (DataAccessException e) {
            log.error("会话撤销持久化失败: sid={}", sid, e);
            return ResponseEntity.status(503).build();
        }
    }

    /**
     * 登录/注册成功后：创建持久会话 → 签发绑定 sid 的 Token。
     * 会话创建失败时返回 null（调用方回 503），绝不返回无会话 Token。
     */
    private String issueSessionToken(User user, LoginResponse response, String successMessage) {
        LoginSession session;
        try {
            session = loginSessionService.createSession(user);
        } catch (DataAccessException e) {
            log.error("登录会话创建失败，不签发Token: user={}", user.getId(), e);
            response.setMessage("登录服务暂不可用，请稍后重试");
            return null;
        }

        String token = jwtUtil.generateToken(user.getId(), user.getUsername(), session.getSid());
        response.setToken(token);
        response.setUserId(user.getId());
        response.setUsername(user.getUsername());
        response.setMessage(successMessage);
        return token;
    }

    /**
     * 验证Token（含持久会话状态；DB 无法确认时 503，不缓存为有效）
     */
    @GetMapping("/verify")
    public ResponseEntity<OperationalQuery.Token> verifyToken(
            @RequestHeader(value = "Authorization", required = false) String authHeader
    ) {
        Map<String, Object> result = new HashMap<>();

        try {
            if (authHeader == null || !authHeader.regionMatches(true, 0, "Bearer ", 0, 7)) {
                result.put("valid", false);
                result.put("message", "Missing or invalid Authorization header");
                return ResponseEntity.ok(OperationalProjectionMapper.token(result));
            }

            String token = authHeader.substring(7).trim();
            if (token.isEmpty()) {
                result.put("valid", false);
                result.put("message", "Token is empty");
                return ResponseEntity.ok(OperationalProjectionMapper.token(result));
            }

            String username = jwtUtil.getUsernameFromToken(token);
            UUID userId = jwtUtil.getUserIdFromToken(token);
            UUID sid = jwtUtil.getSidFromToken(token);

            if (sid == null || userId == null || !jwtUtil.validateToken(token, username)) {
                // 无 sid 的旧式 Token 一律无效（强切换）
                result.put("valid", false);
                result.put("message", "Token无效或已过期");
            } else if (loginSessionService.isSessionActive(sid, userId)) {
                result.put("valid", true);
                result.put("userId", userId);
                result.put("username", username);
            } else {
                result.put("valid", false);
                result.put("message", "会话已撤销或过期");
            }
        } catch (DataAccessException e) {
            // 503 本身即"无法判定"信号：不冒充普通无效 Token，也不缓存为有效
            log.warn("Token验证时会话状态不可用: {}", e.getClass().getSimpleName());
            result.put("valid", false);
            result.put("message", "认证服务暂不可用，请稍后重试");
            return ResponseEntity.status(503).body(OperationalProjectionMapper.token(result));
        } catch (Exception e) {
            result.put("valid", false);
            result.put("message", "Token验证失败: " + e.getMessage());
        }

        return ResponseEntity.ok(OperationalProjectionMapper.token(result));
    }
}
