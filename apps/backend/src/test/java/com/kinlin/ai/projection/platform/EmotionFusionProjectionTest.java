package com.kinlin.ai.projection.platform;

import java.util.Map;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.emotion.mapper.EmotionProjectionMapper;
import com.kinlin.ai.projection.rolefusion.mapper.RoleFusionProjectionMapper;
import com.kinlin.ai.controller.EmotionController;
import com.kinlin.ai.controller.RoleFusionController;
import com.kinlin.ai.dto.EmotionAnalyzeRequest;
import com.kinlin.ai.service.EmotionAwareService;
import com.kinlin.ai.service.RoleFusionService;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class EmotionFusionProjectionTest {
    private final ObjectMapper json = new ObjectMapper();
    @Test
    void emotionKeepsFiniteObservationsAndServiceFallback() throws Exception {
        var body = json.valueToTree(EmotionProjectionMapper.response(Map.of("text", "公开正文",
                "emotion", Map.of("emotion", "friendly", "intensity", 0.5),
                "user_emotion", Map.of("emotion", "neutral", "prompt", "SECRET"),
                "animation", Map.of("expression", "smile", "duration", 1.2, "internal", "SECRET"))));
        assertEquals("neutral", body.path("user_emotion").path("emotion").asText());
        assertEquals(1.2, body.path("animation").path("duration").asDouble());
        assertFalse(body.toString().contains("SECRET"));
        assertEquals("existing error", json.valueToTree(EmotionProjectionMapper.response(
                Map.of("error", "existing error"))).path("error").asText());
        assertThrows(IllegalArgumentException.class,
                () -> EmotionProjectionMapper.analyze(Map.of("intensity", Double.NaN)));
        var service = mock(EmotionAwareService.class);
        var request = new EmotionAnalyzeRequest();
        when(service.analyzeEmotion(request)).thenReturn(Map.of("emotion", "neutral", "intensity", 0.5));
        var response = new EmotionController(service).analyzeEmotion(request);
        assertEquals(200, response.getStatusCode().value());
        assertEquals("neutral", response.getBody().emotion());
    }
    @Test
    void fusionAssociationsKeepIdsAndErrorBodyWithoutBags() throws Exception {
        var wire = Map.<String, Object>of("response", "融合正文",
                "style", Map.of("formality", 0.5, "warmth", 0.6, "technical_level", 0.7),
                "weights", Map.of("r1", 1.0), "sources", Map.of("r1", "来源正文"), "internal", "SECRET");
        var body = json.valueToTree(RoleFusionProjectionMapper.query(wire));
        assertEquals("r1", body.path("weights").get(0).path("roleId").asText());
        assertEquals("来源正文", body.path("sources").get(0).path("response").asText());
        assertEquals(0.7, body.path("style").path("technical_level").asDouble());
        assertFalse(body.toString().contains("SECRET"));
        var service = mock(RoleFusionService.class);
        when(service.calculateRoleWeights("q", java.util.List.of())).thenReturn(Map.of("error", "existing error"));
        var response = new RoleFusionController(service).calculateRoleWeights("q", java.util.List.of());
        assertEquals(200, response.getStatusCode().value());
        assertEquals("existing error", response.getBody().error());
        assertThrows(IllegalArgumentException.class, () -> RoleFusionProjectionMapper.query(
                Map.of("weights", Map.of("r1", Double.POSITIVE_INFINITY))));
    }
}
