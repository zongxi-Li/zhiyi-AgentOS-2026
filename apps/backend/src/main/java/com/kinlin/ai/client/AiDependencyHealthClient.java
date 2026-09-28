package com.kinlin.ai.client;

/**
 * Narrow client contract for the Python dependency health probe (J1.2B):
 * {@code DEGRADED} semantics on any failure, no transport types on the surface.
 * Implementation lives in {@code infrastructure.http}.
 */
public interface AiDependencyHealthClient {

    AiDependencyHealth probe();

    record AiDependencyHealth(String status, Object detail, String errorType) {

        public static AiDependencyHealth reachable(Object detail) {
            return new AiDependencyHealth("REACHABLE", detail, null);
        }

        public static AiDependencyHealth degraded(String errorType) {
            return new AiDependencyHealth("DEGRADED", null, errorType);
        }
    }
}
