package com.kinlin.ai.filter;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.Collections;
import java.util.Enumeration;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/** Makes client-supplied identity and service headers invisible to application code. */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class SensitiveIdentityHeaderFilter extends OncePerRequestFilter {

    /**
     * Strips every header that carries inbound identity or service credentials.
     * The X-Authenticated-* family is the Java-to-Python trusted hop namespace
     * ({@link com.kinlin.ai.gateway.AiGatewayHeaders}); it is generated outbound
     * from Spring Security only and must never be accepted from the wire.
     */
    public static final Set<String> SENSITIVE_HEADERS = Set.of(
            "x-user-id",
            "x-user-role",
            "x-tenant-id",
            "x-organization-id",
            "x-workshop-id",
            "x-internal-service-token",
            "x-authenticated-user-id",
            "x-authenticated-user-subject",
            "x-authenticated-user-role",
            "x-authenticated-tenant-id"
    );

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        filterChain.doFilter(new HttpServletRequestWrapper(request) {
            @Override
            public String getHeader(String name) {
                return isSensitive(name) ? null : super.getHeader(name);
            }

            @Override
            public Enumeration<String> getHeaders(String name) {
                return isSensitive(name) ? Collections.emptyEnumeration() : super.getHeaders(name);
            }

            @Override
            public Enumeration<String> getHeaderNames() {
                List<String> safeNames = Collections.list(super.getHeaderNames()).stream()
                        .filter(name -> !isSensitive(name))
                        .toList();
                return Collections.enumeration(safeNames);
            }
        }, response);
    }

    private boolean isSensitive(String name) {
        return name != null && SENSITIVE_HEADERS.contains(name.toLowerCase(Locale.ROOT));
    }
}
