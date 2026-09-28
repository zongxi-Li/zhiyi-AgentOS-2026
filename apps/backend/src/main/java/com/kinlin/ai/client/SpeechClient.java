package com.kinlin.ai.client;

/**
 * What the Java platform needs from the Python speech synthesis capability
 * (the {@code /ai/tts} endpoint). Returns raw audio bytes.
 */
public interface SpeechClient {

    byte[] textToSpeech(String text, String voice, Double speed, Double pitch);
}
