package com.kinlin.ai.architecture;

import com.kinlin.ai.controller.AgentOsMissionController;
import com.kinlin.ai.projection.common.dto.QueryError;
import com.kinlin.ai.projection.common.dto.QueryResponse;
import com.kinlin.ai.projection.mission.dto.MissionDetailQuery;
import com.kinlin.ai.projection.mission.dto.MissionRunHistoryQuery;
import com.kinlin.ai.projection.mission.dto.MissionSemanticQuery;
import com.kinlin.ai.projection.mission.dto.MissionSemanticCommitsQuery;
import com.kinlin.ai.projection.mission.dto.MissionSemanticReceiptQuery;
import com.kinlin.ai.projection.mission.dto.MissionRunRevisionQuery;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import java.lang.reflect.*;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class MissionProjectionArchitectureTest {
    @Test
    void migratedHandlersAreTypedAndKeepTheExactMappings() throws Exception {
        for (String methodName : List.of("getMission", "getMissionRuns")) {
            Method method = AgentOsMissionController.class.getMethod(methodName, String.class);
            ParameterizedType result = assertInstanceOf(ParameterizedType.class, method.getGenericReturnType());
            assertEquals(ResponseEntity.class, result.getRawType());
            assertArrayEquals(new Type[]{QueryResponse.class}, result.getActualTypeArguments());
            assertArrayEquals(new String[]{methodName.equals("getMission") ? "/missions/{missionId}" : "/missions/{missionId}/runs"},
                    method.getAnnotation(GetMapping.class).value());
        }
        for (Class<?> response : List.of(MissionDetailQuery.class, MissionRunHistoryQuery.class, QueryError.class)) {
            assertTrue(QueryResponse.class.isAssignableFrom(response));
        }
    }

    @Test
    void semanticAndRevisionGetHandlersKeepTypedQueriesAndExactMappings() throws Exception {
        for (String methodName : List.of("getSemantics", "getSemanticCommits", "getSemanticReceipt", "getRunRevision")) {
            boolean scoped = methodName.equals("getSemanticReceipt") || methodName.equals("getRunRevision");
            Method method = AgentOsMissionController.class.getMethod(methodName,
                    scoped ? new Class<?>[]{String.class, String.class} : new Class<?>[]{String.class});
            ParameterizedType result = assertInstanceOf(ParameterizedType.class, method.getGenericReturnType());
            assertEquals(ResponseEntity.class, result.getRawType());
            assertArrayEquals(new Type[]{QueryResponse.class}, result.getActualTypeArguments());
            String route = switch (methodName) {
                case "getSemantics" -> "/missions/{missionId}/semantics";
                case "getSemanticCommits" -> "/missions/{missionId}/semantics/commits";
                case "getSemanticReceipt" -> "/missions/{missionId}/semantics/receipts/{operationId}";
                default -> "/missions/{missionId}/runs/{runId}/revision";
            };
            assertArrayEquals(new String[]{route}, method.getAnnotation(GetMapping.class).value());
        }
        for (Class<?> response : List.of(MissionSemanticQuery.class, MissionSemanticCommitsQuery.class,
                MissionSemanticReceiptQuery.class, MissionRunRevisionQuery.class)) {
            assertTrue(QueryResponse.class.isAssignableFrom(response));
        }
    }
}
