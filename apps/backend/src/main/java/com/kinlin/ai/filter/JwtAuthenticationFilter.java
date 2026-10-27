package com.kinlin.ai.filter;

import com.kinlin.ai.observability.TraceContext;
import com.kinlin.ai.security.AuthenticatedUserContext;
import com.kinlin.ai.service.LoginSessionService;
import com.kinlin.ai.util.JwtUtil;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataAccessException;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.UUID;
import org.slf4j.MDC;

/**
 * JWT认证过滤器
 * 从请求头中提取Token并验证：签名、过期时间、sid 与持久会话状态（INT-2F-4A）。
 *
 * <p>无 sid 的旧式 JWT 一律拒绝；数据库无法确认会话状态时以 503 拒绝访问，
 * 不进入后续过滤链与业务 Controller。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private final JwtUtil jwtUtil;
    private final LoginSessionService loginSessionService;

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {

        // 公开认证端点仅精确放行；/auth/logout 等其余 /auth 路径必须走真实认证。
        String path = request.getRequestURI();
        if (path != null && (
            path.equals("/auth/login") || path.equals("/auth/register") || path.equals("/auth/verify") ||
            path.startsWith("/health") ||
            path.startsWith("/actuator/health") ||
            path.startsWith("/swagger-ui/") ||
            path.startsWith("/v3/api-docs/")
        )) {
            filterChain.doFilter(request, response);
            return;
        }

        String authHeader = request.getHeader("Authorization");

        if (authHeader != null && authHeader.startsWith("Bearer ")) {
            String token = authHeader.substring(7);

            try {
                String username = jwtUtil.getUsernameFromToken(token);
                UUID userId = jwtUtil.getUserIdFromToken(token);
                String role = jwtUtil.getRoleFromToken(token);
                UUID sid = jwtUtil.getSidFromToken(token);

                if (username != null && userId != null && sid != null
                        && SecurityContextHolder.getContext().getAuthentication() == null) {
                    if (jwtUtil.validateToken(token, username)
                            && loginSessionService.isSessionActive(sid, userId)) {
                        // 设置用户上下文（携带 sid）
                        UsernamePasswordAuthenticationToken authentication =
                                new UsernamePasswordAuthenticationToken(
                                        new AuthenticatedUserContext(userId, username, role, sid, null, MDC.get("trace_id")),
                                        null,
                                        java.util.List.of(new SimpleGrantedAuthority("ROLE_" + role))
                                );
                        authentication.setDetails(new WebAuthenticationDetailsSource().buildDetails(request));
                        SecurityContextHolder.getContext().setAuthentication(authentication);

                        // 设置用户ID到请求头（用于后续处理）
                        request.setAttribute("userId", userId);
                    }
                }
            } catch (DataAccessException e) {
                // 数据库无法确认会话状态：拒绝访问（503），不伪装成凭证无效，也不放行
                log.warn("Session state unavailable, rejecting request: {}", e.getClass().getSimpleName());
                SecurityContextHolder.clearContext();
                response.setStatus(HttpServletResponse.SC_SERVICE_UNAVAILABLE);
                response.setContentType(MediaType.APPLICATION_JSON_VALUE);
                String traceId = TraceContext.acceptedOrNew(response.getHeader(TraceContext.HEADER));
                response.setHeader(TraceContext.HEADER, traceId);
                response.getWriter().write("{\"error\":\"auth_state_unavailable\",\"traceId\":\"" + traceId + "\"}");
                return;
            } catch (Exception e) {
                log.debug("JWT validation rejected: {}", e.getClass().getSimpleName());
            }
        }

        filterChain.doFilter(request, response);
    }
}
