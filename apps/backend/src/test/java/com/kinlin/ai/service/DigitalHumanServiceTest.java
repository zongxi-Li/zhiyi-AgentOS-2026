package com.kinlin.ai.service;

import com.kinlin.ai.client.DigitalHumanClient;
import com.kinlin.ai.dto.DigitalHumanRequest;
import com.kinlin.ai.dto.DigitalHumanResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.when;

/**
 * DigitalHumanService单元测试（应用层表征：参数校验与兜底错误响应）
 */
@ExtendWith(MockitoExtension.class)
class DigitalHumanServiceTest {

    @Mock
    private DigitalHumanClient digitalHumanClient;

    private DigitalHumanService digitalHumanService;

    @BeforeEach
    void setUp() {
        digitalHumanService = new DigitalHumanService(digitalHumanClient);
    }

    @Test
    void testCreateDigitalHuman_Success() {
        // Arrange
        DigitalHumanRequest request = new DigitalHumanRequest();
        request.setRoleId("role1");
        request.setStyle("realistic");

        DigitalHumanResponse upstream = new DigitalHumanResponse();
        upstream.setSuccess(true);
        upstream.setData(Map.of("avatar_id", "avatar1"));
        when(digitalHumanClient.create(request)).thenReturn(upstream);

        // Act
        DigitalHumanResponse response = digitalHumanService.createDigitalHuman(request);

        // Assert
        assertNotNull(response);
        assertTrue(response.getSuccess());
        assertNotNull(response.getData());
    }

    @Test
    void testCreateDigitalHuman_UpstreamFailureResponse() {
        // Arrange
        DigitalHumanRequest request = new DigitalHumanRequest();
        request.setRoleId("role1");

        DigitalHumanResponse upstream = new DigitalHumanResponse();
        upstream.setSuccess(false);
        upstream.setMessage("Service error");
        when(digitalHumanClient.create(request)).thenReturn(upstream);

        // Act
        DigitalHumanResponse response = digitalHumanService.createDigitalHuman(request);

        // Assert
        assertNotNull(response);
        assertFalse(response.getSuccess());
        assertNotNull(response.getMessage());
    }

    @Test
    void testCreateDigitalHuman_RejectsBlankRoleId() {
        // Arrange：表征冻结——roleId 缺失时短路返回既有文案
        DigitalHumanRequest request = new DigitalHumanRequest();

        // Act
        DigitalHumanResponse response = digitalHumanService.createDigitalHuman(request);

        // Assert
        assertNotNull(response);
        assertFalse(response.getSuccess());
        assertEquals("角色ID不能为空", response.getMessage());
    }

    @Test
    void testCreateDigitalHuman_UnexpectedFailureKeepsFrozenFallback() {
        // Arrange：表征冻结——client 异常穿透时的既有兜底文案
        when(digitalHumanClient.create(org.mockito.ArgumentMatchers.any(DigitalHumanRequest.class)))
                .thenThrow(new IllegalStateException("boom"));

        DigitalHumanRequest request = new DigitalHumanRequest();
        request.setRoleId("role1");

        // Act
        DigitalHumanResponse response = digitalHumanService.createDigitalHuman(request);

        // Assert
        assertFalse(response.getSuccess());
        assertEquals("boom", response.getMessage());
    }
}
