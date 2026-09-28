/**
 * LEGACY_AI transport scope (J1.1).
 *
 * <p>This package isolates the legacy role-specific chat path (lawyer / teacher /
 * programmer / writer) that still calls Python via {@code RestTemplate}. It is a
 * DEPRECATE candidate scheduled for removal in J1.3 (Legacy AI Cleanup).</p>
 *
 * <p>Rules established in J1.1:
 * <ul>
 *   <li>No new formal (AgentOS / platform-ai) code may depend on this package.</li>
 *   <li>No new {@code RestTemplate} usage may appear outside this package.</li>
 *   <li>Role-specific Python endpoints and their error semantics are frozen
 *       (characterized by {@code LegacyAgentGatewayServiceTest}).</li>
 * </ul>
 */
package com.kinlin.ai.legacy.agent;
