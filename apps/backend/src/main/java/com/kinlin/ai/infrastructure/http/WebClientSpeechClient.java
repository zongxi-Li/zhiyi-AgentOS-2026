package com.kinlin.ai.infrastructure.http;

import com.kinlin.ai.client.SpeechClient;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.Map;

/** WebClient implementation of the speech synthesis capability ({@code /ai/tts}). */
@Component
public class WebClientSpeechClient implements SpeechClient {

    private final PlatformAiTransport transport;

    public WebClientSpeechClient(PlatformAiTransport transport) {
        this.transport = transport;
    }

    @Override
    public byte[] textToSpeech(String text, String voice, Double speed, Double pitch) {
        Map<String, Object> requestBody = new HashMap<>();
        requestBody.put("text", text);
        requestBody.put("voice", voice);
        if (speed != null) {
            requestBody.put("speed", speed);
        }
        if (pitch != null) {
            requestBody.put("pitch", pitch);
        }

        return transport.postJson("/ai/tts", requestBody, byte[].class);
    }
}
