package com.kinlin.ai.architecture;

import com.fasterxml.jackson.annotation.JsonAnyGetter;
import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.JsonSerializable;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.kinlin.ai.controller.AgentOsMissionController;
import com.kinlin.ai.entity.User;
import com.kinlin.ai.projection.common.dto.QueryError;
import com.kinlin.ai.projection.common.dto.QueryResponse;
import com.kinlin.ai.projection.mission.dto.MissionDetailQuery;
import com.kinlin.ai.projection.mission.dto.MissionRunHistoryQuery;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import java.lang.reflect.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
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
            inspect(response, new HashSet<>());
        }
    }

    @Test
    void allMissionAndCommonDtoSourcesMustBeCheckedIncludingFutureRecords() throws Exception {
        Path main = Path.of("src/main/java");
        for (String domain : List.of("mission", "common")) {
            Path directory = main.resolve("com/kinlin/ai/projection/" + domain + "/dto");
            assertTrue(Files.isDirectory(directory), "source paths must exist; guard cannot skip");
            try (var files = Files.list(directory)) {
                for (Path file : files.filter(path -> path.toString().endsWith(".java")).toList()) {
                    inspect(Class.forName("com.kinlin.ai.projection." + domain + ".dto."
                            + file.getFileName().toString().replace(".java", "")), new HashSet<>());
                }
            }
        }
    }

    @Test
    void mapperHasNoInfrastructureOrStateMutationDependency() throws Exception {
        Path source = Path.of("src/main/java/com/kinlin/ai/projection/mission/mapper/MissionProjectionMapper.java");
        assertTrue(Files.exists(source));
        String code = Files.readString(source).replaceAll("(?s)/\\*.*?\\*/", "").replaceAll("(?m)//.*$", "");
        for (String owner : List.of("repository", "service", "gateway", "client", "infrastructure", "runtime")) {
            assertFalse(code.contains("com.kinlin.ai." + owner + "."), owner);
        }
        assertFalse(java.util.regex.Pattern.compile("copyProperties\\s*\\(|convertValue\\s*\\(|@Cache|@Transactional|\\.(?:save|delete|put|remove|set\\w*)\\s*\\(").matcher(code).find());
    }

    @Test
    void negativeFixturesDetectDynamicContainersNestedEntitiesAndForbiddenFields() {
        for (Class<?> unsafe : List.of(Dynamic.class, EntityWrapper.class, RuntimeWrapper.class, Getter.class)) {
            assertThrows(AssertionError.class, () -> inspect(unsafe, new HashSet<>()));
        }
    }

    private static void inspect(Type type, Set<Type> visited) {
        if (!visited.add(type)) { return; }
        if (type instanceof ParameterizedType generic) {
            inspectClass((Class<?>) generic.getRawType(), visited);
            for (Type argument : generic.getActualTypeArguments()) { inspect(argument, visited); }
        } else if (type instanceof Class<?> concrete) {
            assertEquals(0, concrete.getTypeParameters().length, "raw generic " + type);
            inspectClass(concrete, visited);
        } else if (type instanceof GenericArrayType array) {
            inspect(array.getGenericComponentType(), visited);
        } else { fail("open query type " + type); }
    }

    private static void inspectClass(Class<?> type, Set<Type> visited) {
        assertNotEquals(Object.class, type);
        assertFalse(Map.class.isAssignableFrom(type) || JsonNode.class.isAssignableFrom(type) || JsonSerializable.class.isAssignableFrom(type));
        assertFalse(type.isAnnotationPresent(JsonSerialize.class));
        for (String owner : List.of("entity", "repository", "client", "gateway", "infrastructure", "runtime")) {
            assertFalse(type.getName().startsWith("com.kinlin.ai." + owner + "."), type.toString());
        }
        assertFalse(Set.of("TaskPlan", "ACGBlueprint", "AcgBlueprint", "CompiledACGPackage", "ExecutionState",
                "ExecutionBinding", "BindingManifest", "GraphPatch").contains(type.getSimpleName()));
        if (type.isArray()) { inspect(type.getComponentType(), visited); return; }
        if (!type.getName().startsWith("com.kinlin.ai.") || type.isEnum()) { return; }
        Set<String> forbiddenFields = Set.of("executionState", "checkpoint", "checkpointId", "scheduler", "binding", "metadata",
                "graph", "graphPatchRefs", "sourcePatchId", "controlFrames", "resourceBindings");
        for (Field field : type.getDeclaredFields()) {
            if (!Modifier.isStatic(field.getModifiers())) {
                assertFalse(forbiddenFields.contains(field.getName()), field.toString());
                assertFalse(field.isAnnotationPresent(JsonSerialize.class));
                inspect(field.getGenericType(), visited);
            }
        }
        for (Method method : type.getDeclaredMethods()) {
            assertFalse(method.isAnnotationPresent(JsonAnyGetter.class) || method.isAnnotationPresent(JsonAnySetter.class)
                    || method.isAnnotationPresent(JsonSerialize.class));
            if (Modifier.isPublic(method.getModifiers()) && !Modifier.isStatic(method.getModifiers())
                    && method.getParameterCount() == 0 && (method.getName().startsWith("get") || method.getName().startsWith("is"))) {
                inspect(method.getGenericReturnType(), visited);
            }
        }
        Type parent = type.getGenericSuperclass();
        if (parent != null && parent != Object.class && parent != Record.class) { inspect(parent, visited); }
        for (Class<?> nested : type.getDeclaredClasses()) { inspect(nested, visited); }
    }

    private record Dynamic(List<Map<String, String>> content) { }
    private record EntityWrapper(List<User> users) { }
    private record RuntimeWrapper(String checkpoint) { }
    private static class Getter { public JsonNode getPayload() { return null; } }
}
