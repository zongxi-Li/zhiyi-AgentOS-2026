package com.kinlin.ai.architecture;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.JsonSerializable;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.annotation.JsonAnyGetter;
import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.kinlin.ai.controller.RoleController;
import com.kinlin.ai.controller.UserController;
import com.kinlin.ai.entity.Role;
import com.kinlin.ai.entity.User;
import com.kinlin.ai.projection.role.dto.RoleConfigurationQuery;
import com.kinlin.ai.projection.role.dto.RoleContextQuery;
import com.kinlin.ai.projection.role.dto.RoleQuery;
import org.junit.jupiter.api.Test;
import org.springframework.core.annotation.AnnotatedElementUtils;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.lang.reflect.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.*;

/** Shared projection guards. Inputs and not-yet-migrated response domains remain outside the strict output checks. */
class QueryProjectionArchitectureTest {
    private static final Path MAIN = Path.of("src/main/java");

    @Test
    void everyControllerReturnTypeRejectsUserAndRoleIncludingNestedBodies() throws Exception {
        Path directory = MAIN.resolve("com/kinlin/ai/controller");
        assertTrue(Files.isDirectory(directory), "backend source directory must exist; never skip this guard");
        int checked = 0;
        try (Stream<Path> files = Files.list(directory)) {
            for (Path file : files.filter(path -> path.toString().endsWith(".java")).toList()) {
                Class<?> controller = Class.forName("com.kinlin.ai.controller."
                        + file.getFileName().toString().replace(".java", ""));
                if (!AnnotatedElementUtils.hasAnnotation(controller, RestController.class)) { continue; }
                for (Method method : controller.getDeclaredMethods()) {
                    if (!AnnotatedElementUtils.hasAnnotation(method, RequestMapping.class)) { continue; }
                    boolean strictIdentity = controller == UserController.class || controller == RoleController.class;
                    assertSafe(method.getGenericReturnType(), strictIdentity, new HashSet<>(), method.toString());
                    checked++;
                }
            }
        }
        assertTrue(checked > 0, "must inspect actual HTTP handlers");
    }

    @Test
    void everyProjectionDtoHasClosedTypedPublicFields() throws Exception {
        Path directory = MAIN.resolve("com/kinlin/ai/projection");
        assertTrue(Files.isDirectory(directory));
        int checked = 0;
        try (Stream<Path> files = Files.walk(directory)) {
            for (Path file : files.filter(path -> path.toString().endsWith(".java"))
                    .filter(path -> path.getParent().getFileName().toString().equals("dto")).toList()) {
                String name = MAIN.relativize(file).toString().replace('\\', '.').replace('/', '.').replace(".java", "");
                assertSafe(Class.forName(name), true, new HashSet<>(), name);
                checked++;
            }
        }
        assertTrue(checked > 0);
    }

    @Test
    void extensibleConfigurationCannotSpreadToOtherProjectionSlots() throws Exception {
        Path directory = MAIN.resolve("com/kinlin/ai/projection");
        assertTrue(Files.isDirectory(directory));
        try (Stream<Path> files = Files.walk(directory)) {
            for (Path file : files.filter(path -> path.toString().endsWith(".java"))
                    .filter(path -> path.getParent().getFileName().toString().equals("dto")).toList()) {
                String className = MAIN.relativize(file).toString().replace('\\', '.')
                        .replace('/', '.').replace(".java", "");
                assertConfigurationSlots(Class.forName(className));
            }
        }
    }

    @Test
    void allProjectionMappersHaveNoInfrastructureOrMutationDependencies() throws Exception {
        Path directory = MAIN.resolve("com/kinlin/ai/projection");
        assertTrue(Files.isDirectory(directory));
        int checked = 0;
        try (Stream<Path> files = Files.walk(directory)) {
            for (Path file : files.filter(path -> path.toString().endsWith(".java"))
                    .filter(path -> path.getParent().getFileName().toString().equals("mapper")).toList()) {
                String code = Files.readString(file).replaceAll("(?s)/\\*.*?\\*/", "").replaceAll("(?m)//.*$", "");
                for (String dependency : List.of("repository", "service", "gateway", "client", "infrastructure", "runtime")) {
                    assertFalse(code.contains("com.kinlin.ai." + dependency + "."), file + " depends on " + dependency);
                }
                assertFalse(java.util.regex.Pattern.compile(
                        "copyProperties\\s*\\(|convertValue\\s*\\(|@Cache|@Transactional|\\.(?:save|delete|put|remove|set\\w*)\\s*\\(")
                        .matcher(code).find(), file + " must only construct output values");
                checked++;
            }
        }
        assertTrue(checked > 0);
    }

    @Test
    void negativeFixturesDetectWrappedEntitiesDynamicDtosAndConfigurationSpread() throws Exception {
        for (String name : List.of("user", "roles", "nested", "dynamic", "opaque", "json", "raw", "wildcard", "inherited", "getter", "checkpoint")) {
            Type type = BadResponses.class.getDeclaredMethod(name).getGenericReturnType();
            assertThrows(AssertionError.class, () -> assertSafe(type, true, new HashSet<>(), name), name);
        }
        assertThrows(AssertionError.class, () -> assertConfigurationSlots(ConfigurationSpread.class));
        assertThrows(AssertionError.class, () -> assertConfigurationSlots(GetterConfigurationSpread.class));
        assertDoesNotThrow(() -> assertSafe(RoleQuery.class, true, new HashSet<>(), "valid role"));
        assertDoesNotThrow(() -> assertConfigurationSlots(RoleQuery.class));
        assertDoesNotThrow(() -> assertConfigurationSlots(RoleContextQuery.class));
    }

    private static void assertSafe(Type type, boolean strict, Set<Type> visited, String path) {
        if (!visited.add(type)) { return; }
        if (type instanceof ParameterizedType generic) {
            for (Type argument : generic.getActualTypeArguments()) { assertSafe(argument, strict, visited, path); }
            inspectClass((Class<?>) generic.getRawType(), strict, visited, path);
        } else if (type instanceof Class<?> concrete) {
            if (strict) { assertEquals(0, concrete.getTypeParameters().length, path + " contains a raw generic"); }
            inspectClass(concrete, strict, visited, path);
        } else if (type instanceof GenericArrayType array) {
            assertSafe(array.getGenericComponentType(), strict, visited, path);
        } else if (type instanceof WildcardType wildcard) {
            assertFalse(strict, path + " contains a wildcard");
            for (Type bound : wildcard.getUpperBounds()) { assertSafe(bound, false, visited, path); }
            for (Type bound : wildcard.getLowerBounds()) { assertSafe(bound, false, visited, path); }
        } else {
            assertFalse(strict, path + " contains an unresolved generic type: " + type);
        }
    }

    private static void inspectClass(Class<?> type, boolean strict, Set<Type> visited, String path) {
        assertFalse(User.class.isAssignableFrom(type), path + " exposes/inherits User Entity");
        assertFalse(Role.class.isAssignableFrom(type), path + " exposes/inherits Role Entity");
        if (strict) {
            assertNotEquals(Object.class, type, path + " exposes Object");
            assertFalse(Map.class.isAssignableFrom(type), path + " exposes Map");
            assertFalse(JsonNode.class.isAssignableFrom(type), path + " exposes JsonNode");
            assertFalse(type.isAnnotationPresent(JsonSerialize.class), path + " has an unapproved serialization override");
            for (String forbidden : List.of("entity", "repository", "client", "gateway", "infrastructure", "runtime")) {
                assertFalse(type.getName().startsWith("com.kinlin.ai." + forbidden + "."), path + " references internal " + type);
            }
            assertFalse(Set.of("TaskPlan", "ACGBlueprint", "AcgBlueprint", "CompiledACGPackage",
                    "ExecutionState", "ExecutionBinding", "BindingManifest", "GraphPatch").contains(type.getSimpleName()), path);
            if (JsonSerializable.class.isAssignableFrom(type)) {
                assertEquals(RoleConfigurationQuery.class, type, path + " has an unapproved custom JSON serializer");
            }
        }
        if (type.isArray()) { assertSafe(type.getComponentType(), strict, visited, path); return; }
        if (!type.getName().startsWith("com.kinlin.ai.") || type.isEnum()) { return; }
        if (type.isSealed()) {
            for (Class<?> permitted : type.getPermittedSubclasses()) { assertSafe(permitted, strict, visited, path); }
        }
        for (Field field : type.getDeclaredFields()) {
            if (!Modifier.isStatic(field.getModifiers())) {
                if (strict) {
                    assertFalse(field.isAnnotationPresent(JsonSerialize.class), path + " overrides field serialization");
                    assertFalse(Set.of("passwordHash", "executionState", "checkpoint", "checkpointId", "scheduler",
                            "binding", "executionBinding", "bindingManifest", "compiledPackage", "graphPatchRefs",
                            "sourcePatchId", "controlFrames", "resourceBindings").contains(field.getName()), field.toString());
                }
                assertSafe(field.getGenericType(), strict, visited, path + "." + field.getName());
            }
        }
        for (Method method : type.getDeclaredMethods()) {
            if (strict) {
                assertFalse(method.isAnnotationPresent(JsonAnyGetter.class) || method.isAnnotationPresent(JsonAnySetter.class)
                        || method.isAnnotationPresent(JsonSerialize.class), path + " contains an open serialization method");
            }
            if (Modifier.isPublic(method.getModifiers()) && !Modifier.isStatic(method.getModifiers())
                    && method.getParameterCount() == 0 && (method.getName().startsWith("get") || method.getName().startsWith("is"))) {
                assertSafe(method.getGenericReturnType(), strict, visited, path + "." + method.getName());
            }
        }
        Type parent = type.getGenericSuperclass();
        if (parent != null && parent != Object.class) { assertSafe(parent, strict, visited, path); }
    }

    private static void assertConfigurationSlots(Class<?> owner) {
        if (owner == RoleConfigurationQuery.class || owner.getEnclosingClass() == RoleConfigurationQuery.class) { return; }
        for (Field field : owner.getDeclaredFields()) {
            if (Modifier.isStatic(field.getModifiers()) || !containsConfiguration(field.getGenericType())) { continue; }
            Set<String> allowed = owner == RoleQuery.class ? Set.of("dialogueStyle", "personality", "avatarConfig")
                    : owner == RoleContextQuery.class ? Set.of("dialogueStyle", "personality") : Set.of();
            assertTrue(allowed.contains(field.getName()), "configuration spread: " + owner.getName() + "." + field.getName());
            assertEquals(RoleConfigurationQuery.class, field.getType(), "configuration cannot be a generic payload container");
        }
        for (Method method : owner.getDeclaredMethods()) {
            if (Modifier.isPublic(method.getModifiers()) && !Modifier.isStatic(method.getModifiers())
                    && method.getParameterCount() == 0 && (method.getName().startsWith("get") || method.getName().startsWith("is"))) {
                assertFalse(containsConfiguration(method.getGenericReturnType()), "configuration getter spread: " + method);
            }
        }
        for (Class<?> nested : owner.getDeclaredClasses()) { assertConfigurationSlots(nested); }
    }

    private static boolean containsConfiguration(Type type) {
        if (type instanceof Class<?> concrete) {
            return concrete == RoleConfigurationQuery.class || concrete.getEnclosingClass() == RoleConfigurationQuery.class;
        }
        if (type instanceof ParameterizedType generic) {
            return Arrays.stream(generic.getActualTypeArguments()).anyMatch(QueryProjectionArchitectureTest::containsConfiguration);
        }
        if (type instanceof GenericArrayType array) { return containsConfiguration(array.getGenericComponentType()); }
        if (type instanceof WildcardType wildcard) {
            return Stream.concat(Arrays.stream(wildcard.getUpperBounds()), Arrays.stream(wildcard.getLowerBounds()))
                    .anyMatch(QueryProjectionArchitectureTest::containsConfiguration);
        }
        return false;
    }

    private record NestedRole(Role body) { }
    private record RuntimeDto(String checkpoint) { }
    private record DynamicDto(Map<String, String> metadata) { }
    private record ConfigurationSpread(List<RoleConfigurationQuery> payload) { }
    private static class InheritedUser extends User { }
    private static class GetterDto { public Role getRole() { return null; } }
    private static class GetterConfigurationSpread { public RoleConfigurationQuery getMetadata() { return null; } }
    private interface BadResponses {
        ResponseEntity<RuntimeDto> checkpoint();
        ResponseEntity<User> user();
        ResponseEntity<List<Role>> roles();
        ResponseEntity<NestedRole> nested();
        ResponseEntity<DynamicDto> dynamic();
        ResponseEntity<Object> opaque();
        ResponseEntity<JsonNode> json();
        ResponseEntity raw();
        ResponseEntity<? extends RoleQuery> wildcard();
        ResponseEntity<InheritedUser> inherited();
        ResponseEntity<GetterDto> getter();
    }
}
