/**
 * Formal client contracts: what the Java platform needs from the Python side,
 * expressed per stable business capability (chat, speech, RAG, knowledge graph,
 * digital human, emotion, role fusion, AgentOS).
 *
 * <p>Direction rule (enforced by {@code ArchitectureGuardTest}): application services
 * depend on these interfaces; implementations live below in
 * {@code infrastructure.http} / {@code gateway}. Contracts never expose transport
 * types (WebClient / Mono / Flux / ClientResponse / HttpStatusCode) — transport
 * failures surface as {@link com.kinlin.ai.client.PlatformAiClientException} or
 * family-specific result envelopes.</p>
 */
package com.kinlin.ai.client;
