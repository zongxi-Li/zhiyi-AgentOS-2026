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
import org.springframework.web.util.ServletRequestPathUtils;
import org.springframework.web.util.UrlPathHelper;

import java.io.IOException;
import java.util.Set;

/**
 * Accepts the renderer's /api aliases when it connects directly to local Java.
 * Normalize before Spring Security so aliases share the canonical authorization
 * and controller mappings. Native /api families (including AgentOS) stay intact.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 1)
public class LocalApiPathFilter extends OncePerRequestFilter {

    private static final Set<String> LEGACY_ROOTS = Set.of(
            "auth", "chat", "conversations", "files", "health", "metrics", "rag",
            "recommendations", "roles", "search", "statistics", "users", "profile", "voice");

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String context = request.getContextPath();
        String uri = request.getRequestURI();
        String path = uri.substring(context.length());
        if (!path.startsWith("/api/")) {
            chain.doFilter(request, response);
            return;
        }
        String canonical = path.substring(4);
        String root = canonical.substring(1).split("/", 2)[0];
        if (!LEGACY_ROOTS.contains(root)) {
            chain.doFilter(request, response);
            return;
        }
        HttpServletRequest normalized = new HttpServletRequestWrapper(request) {
            @Override
            public String getRequestURI() {
                return context + canonical;
            }

            @Override
            public String getServletPath() {
                return canonical;
            }

            @Override
            public StringBuffer getRequestURL() {
                String original = super.getRequestURL().toString();
                return new StringBuffer(original.substring(0, original.length() - uri.length()))
                        .append(context).append(canonical);
            }
        };
        // An upstream servlet path filter may already have cached the original URI.
        // Security's MVC matchers and the controller must see the same canonical path.
        var previousPath = request.getAttribute(ServletRequestPathUtils.PATH_ATTRIBUTE);
        var previousLookup = request.getAttribute(UrlPathHelper.PATH_ATTRIBUTE);
        request.removeAttribute(UrlPathHelper.PATH_ATTRIBUTE);
        ServletRequestPathUtils.parseAndCache(normalized);
        try {
            chain.doFilter(normalized, response);
        } finally {
            if (previousPath == null) request.removeAttribute(ServletRequestPathUtils.PATH_ATTRIBUTE);
            else request.setAttribute(ServletRequestPathUtils.PATH_ATTRIBUTE, previousPath);
            if (previousLookup == null) request.removeAttribute(UrlPathHelper.PATH_ATTRIBUTE);
            else request.setAttribute(UrlPathHelper.PATH_ATTRIBUTE, previousLookup);
        }
    }
}
