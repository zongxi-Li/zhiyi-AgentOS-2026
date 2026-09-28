package com.kinlin.ai.client;

import com.kinlin.ai.dto.DigitalHumanRequest;
import com.kinlin.ai.dto.DigitalHumanResponse;

/**
 * What the Java platform needs from the Python digital-human capability
 * ({@code /ai/digital-human/**} family). Returns the assembled
 * {@link DigitalHumanResponse}; transport failures surface as
 * {@link PlatformAiClientException} (a missing digital human arrives as
 * {@code type == REJECTED, upstreamStatus == 404}).
 */
public interface DigitalHumanClient {

    DigitalHumanResponse create(DigitalHumanRequest request);

    DigitalHumanResponse updateAnimation(String roleId, byte[] audioData, String text);

    DigitalHumanResponse get(String roleId);

    DigitalHumanResponse switchStyle(String roleId, String newStyle);
}
