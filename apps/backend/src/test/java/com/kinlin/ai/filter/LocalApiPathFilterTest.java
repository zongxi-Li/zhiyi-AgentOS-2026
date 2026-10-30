package com.kinlin.ai.filter;

import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.junit.jupiter.api.Assertions.assertEquals;

class LocalApiPathFilterTest {

    @ParameterizedTest
    @CsvSource({
            "/api/auth/login,/auth/login",
            "/api/chat/quality,/chat/quality",
            "/api/health/ready,/health/ready",
            "/api/files/upload,/files/upload",
            "/api/agentos/v2/missions,/api/agentos/v2/missions",
            "/api/digital-human/list,/api/digital-human/list",
            "/api/auth-other/login,/api/auth-other/login",
            "/api/unknown,/api/unknown",
            "/api/api/auth/login,/api/api/auth/login",
            "/auth/login,/auth/login"
    })
    void normalizesOnlyKnownLegacyFamilies(String incoming, String expected) throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/local" + incoming);
        request.setContextPath("/local");
        request.setServletPath(incoming);
        request.setQueryString("cursor=a%2Fb");
        request.addHeader("Authorization", "Bearer example");
        request.setContent("payload".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        new LocalApiPathFilter().doFilter(request, new MockHttpServletResponse(), (wrapped, response) -> {
            HttpServletRequest http = (HttpServletRequest) wrapped;
            assertEquals("/local" + expected, http.getRequestURI());
            assertEquals(expected, http.getServletPath());
            assertEquals("http://localhost/local" + expected, http.getRequestURL().toString());
            assertEquals("cursor=a%2Fb", http.getQueryString());
            assertEquals("Bearer example", http.getHeader("Authorization"));
            assertEquals("POST", http.getMethod());
            assertEquals("payload", http.getReader().readLine());
        });
    }
}
