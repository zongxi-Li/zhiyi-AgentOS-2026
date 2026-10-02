package com.kinlin.ai.projection.platform;

import java.util.Map;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.controller.DigitalHumanController;
import com.kinlin.ai.dto.DigitalHumanResponse;
import com.kinlin.ai.projection.digitalhuman.mapper.DigitalHumanProjectionMapper;
import com.kinlin.ai.service.DigitalHumanService;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class DigitalHumanProjectionTest {
    private final ObjectMapper json = new ObjectMapper();
    @Test
    void publicAvatarKeepsItsWireNamesAndDropsInternalPathsAndSettings() throws Exception {
        var response = new DigitalHumanResponse();
        response.setSuccess(true);
        response.setData(Map.of("avatar_id", "a1", "role_id", "r1", "modelUrl", "/models/default.glb",
                "modelPath", "/models/default.glb", "local_image_url", "/ai/digital-human/image/avatar.png",
                "local_image_path", "SECRET", "image_prompt", "SECRET", "display_settings", Map.of("internal", "SECRET"),
                "avatar_config", Map.of("model_type", "humanoid", "render_style", "realistic", "internal", "SECRET"),
                "animations", Map.of("idle", Map.of("duration", 2.0, "loop", true, "internal", "SECRET"))));
        var body = json.valueToTree(DigitalHumanProjectionMapper.query(response));
        assertEquals("a1", body.path("data").path("avatar_id").asText());
        assertEquals("realistic", body.path("data").path("avatar_config").path("render_style").asText());
        assertTrue(body.path("data").path("animations").path("idle").path("loop").asBoolean());
        assertFalse(body.toString().contains("SECRET"));
        var service = mock(DigitalHumanService.class);
        when(service.getDigitalHuman("r1")).thenReturn(response);
        var result = new DigitalHumanController(service).getDigitalHuman("r1");
        assertEquals(200, result.getStatusCode().value());
        assertEquals("a1", result.getBody().data().avatarId());
    }
    @Test
    void notFoundAndFailureKeepTheExistingThreeKeyEnvelope() throws Exception {
        var service = mock(DigitalHumanService.class);
        var failure = new DigitalHumanResponse();
        failure.setSuccess(false);
        failure.setMessage("数字人不存在: missing");
        when(service.getDigitalHuman("missing")).thenReturn(failure);
        var controller = new DigitalHumanController(service);
        var result = controller.getDigitalHuman("missing");
        assertEquals(404, result.getStatusCode().value());
        assertEquals(json.valueToTree(failure), json.valueToTree(result.getBody()));
        when(service.getDigitalHuman("broken")).thenThrow(new IllegalStateException("existing failure"));
        var thrown = controller.getDigitalHuman("broken");
        assertEquals(404, thrown.getStatusCode().value());
        assertEquals("获取数字人失败: existing failure", thrown.getBody().message());
        assertNull(thrown.getBody().data());
    }
}
