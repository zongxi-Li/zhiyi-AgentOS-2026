package com.kinlin.ai.exception;

import com.kinlin.ai.controller.AgentOsGatewayController;
import com.kinlin.ai.dto.agentos.AgentOsErrorResponse;
import com.kinlin.ai.observability.TraceContext;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** Stable local error envelope for the Java AgentOS northbound boundary. */
@Order(0)
@RestControllerAdvice(assignableTypes = AgentOsGatewayController.class)
public class AgentOsGatewayExceptionHandler {

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<AgentOsErrorResponse> validation(MethodArgumentNotValidException ignored) {
        return response(HttpStatus.UNPROCESSABLE_ENTITY, "AGENTOS_VALIDATION_ERROR",
                "AgentOS request validation failed.");
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<AgentOsErrorResponse> malformed(HttpMessageNotReadableException ignored) {
        return response(HttpStatus.BAD_REQUEST, "AGENTOS_INVALID_REQUEST",
                "AgentOS request body is invalid.");
    }

    private ResponseEntity<AgentOsErrorResponse> response(HttpStatus status, String code, String message) {
        return ResponseEntity.status(status).body(
                new AgentOsErrorResponse(code, message, TraceContext.currentTraceId())
        );
    }
}
