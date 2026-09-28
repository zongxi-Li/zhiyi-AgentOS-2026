/**
 * Formal Java-to-Python transport boundary (J1.1).
 *
 * <p>Owns: the canonical Python service root configuration ({@link com.kinlin.ai.infrastructure.http.PythonServiceProperties}),
 * transport construction ({@link com.kinlin.ai.infrastructure.http.PythonClientFactory}),
 * transport error classification ({@link com.kinlin.ai.infrastructure.http.TransportErrorClassifier}),
 * and the health probe client ({@link com.kinlin.ai.infrastructure.http.AiDependencyHealthClient}).</p>
 *
 * <p>Outside this package (and the legacy agent boundary) no class may build an HTTP client,
 * resolve the Python base URL, or read {@code ai.service.*} configuration.</p>
 */
package com.kinlin.ai.infrastructure.http;
