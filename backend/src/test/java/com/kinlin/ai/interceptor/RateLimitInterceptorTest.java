package com.kinlin.ai.interceptor;

import com.google.common.cache.CacheBuilder;
import com.google.common.cache.CacheLoader;
import com.google.common.cache.LoadingCache;
import com.kinlin.ai.security.AuthenticatedUserContext;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RateLimitInterceptorTest {

    @AfterEach
    void clearSecurityContext() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void authenticatedUsersBehindTheSameProxyUseIndependentBuckets() throws Exception {
        LoadingCache<String, AtomicInteger> cache = CacheBuilder.newBuilder().build(
                CacheLoader.from(key -> new AtomicInteger())
        );
        RateLimitInterceptor interceptor = new RateLimitInterceptor(cache);
        ReflectionTestUtils.setField(interceptor, "maxRequestsPerMinute", 1);
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/agentos/v2/runs");
        request.setRemoteAddr("172.25.0.3");

        authenticate(UUID.fromString("11111111-1111-1111-1111-111111111111"));
        assertTrue(interceptor.preHandle(request, new MockHttpServletResponse(), new Object()));

        authenticate(UUID.fromString("22222222-2222-2222-2222-222222222222"));
        assertTrue(interceptor.preHandle(request, new MockHttpServletResponse(), new Object()));

        MockHttpServletResponse limited = new MockHttpServletResponse();
        assertFalse(interceptor.preHandle(request, limited, new Object()));
        assertEquals(429, limited.getStatus());
        assertEquals("60", limited.getHeader("Retry-After"));
    }

    private void authenticate(UUID userId) {
        var context = new AuthenticatedUserContext(userId, userId.toString(), "USER", null, null);
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(context, null, List.of())
        );
    }
}
