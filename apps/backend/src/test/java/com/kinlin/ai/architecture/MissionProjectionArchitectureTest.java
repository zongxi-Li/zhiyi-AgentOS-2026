package com.kinlin.ai.architecture;

import com.kinlin.ai.controller.AgentOsMissionController;
import com.kinlin.ai.projection.common.dto.QueryError;
import com.kinlin.ai.projection.common.dto.QueryResponse;
import com.kinlin.ai.projection.mission.dto.MissionDetailQuery;
import com.kinlin.ai.projection.mission.dto.MissionRunHistoryQuery;
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

}
