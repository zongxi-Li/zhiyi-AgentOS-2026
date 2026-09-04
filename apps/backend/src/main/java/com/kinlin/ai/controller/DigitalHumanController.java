package com.kinlin.ai.controller;

import com.kinlin.ai.dto.DigitalHumanRequest;
import com.kinlin.ai.dto.DigitalHumanResponse;
import com.kinlin.ai.service.DigitalHumanService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

/**
 * 数字人控制器
 */
@Slf4j
@RestController
@RequestMapping("/api/digital-human")
@RequiredArgsConstructor
public class DigitalHumanController {

    private final DigitalHumanService digitalHumanService;

    /**
     * 创建数字人
     */
    @PostMapping("/create")
    public ResponseEntity<DigitalHumanResponse> createDigitalHuman(
            @Valid @RequestBody DigitalHumanRequest request
    ) {
        try {
            log.info("收到创建数字人请求: roleId={}, style={}", request.getRoleId(), request.getStyle());
            DigitalHumanResponse response = digitalHumanService.createDigitalHuman(request);
            
            if (response.getSuccess() != null && !response.getSuccess()) {
                // 如果失败，返回500状态码
                return ResponseEntity.status(500).body(response);
            }
            return ResponseEntity.ok(response);
        } catch (Exception e) {
            log.error("处理创建数字人请求失败", e);
            DigitalHumanResponse errorResponse = new DigitalHumanResponse();
            errorResponse.setSuccess(false);
            errorResponse.setMessage("处理请求失败: " + e.getMessage());
            return ResponseEntity.status(500).body(errorResponse);
        }
    }

    /**
     * 更新数字人动画
     */
    @PostMapping(value = "/animation", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<DigitalHumanResponse> updateAnimation(
            @RequestParam("roleId") String roleId,
            @RequestParam("text") String text,
            @RequestParam("audio") MultipartFile audioFile
    ) {
        try {
            byte[] audioData = audioFile.getBytes();
            DigitalHumanResponse response = digitalHumanService.updateAnimation(roleId, audioData, text);
            return ResponseEntity.ok(response);
        } catch (Exception e) {
            log.error("更新数字人动画失败", e);
            DigitalHumanResponse errorResponse = new DigitalHumanResponse();
            errorResponse.setSuccess(false);
            errorResponse.setMessage("更新数字人动画失败: " + e.getMessage());
            return ResponseEntity.internalServerError().body(errorResponse);
        }
    }

    /**
     * 切换数字人风格
     */
    @PostMapping("/style")
    public ResponseEntity<DigitalHumanResponse> switchStyle(
            @RequestParam("roleId") String roleId,
            @RequestParam("newStyle") String newStyle
    ) {
        DigitalHumanResponse response = digitalHumanService.switchStyle(roleId, newStyle);
        return ResponseEntity.ok(response);
    }

    /**
     * 获取数字人信息（用于加载已创建的数字人）
     */
    @GetMapping("/{roleId}")
    public ResponseEntity<DigitalHumanResponse> getDigitalHuman(
            @PathVariable("roleId") String roleId
    ) {
        try {
            log.info("收到获取数字人请求: roleId={}", roleId);
            DigitalHumanResponse response = digitalHumanService.getDigitalHuman(roleId);
            
            if (response.getSuccess() != null && !response.getSuccess()) {
                // 如果数字人不存在，返回404
                return ResponseEntity.status(404).body(response);
            }
            return ResponseEntity.ok(response);
        } catch (Exception e) {
            log.error("获取数字人失败", e);
            DigitalHumanResponse errorResponse = new DigitalHumanResponse();
            errorResponse.setSuccess(false);
            errorResponse.setMessage("获取数字人失败: " + e.getMessage());
            return ResponseEntity.status(404).body(errorResponse);
        }
    }
}

