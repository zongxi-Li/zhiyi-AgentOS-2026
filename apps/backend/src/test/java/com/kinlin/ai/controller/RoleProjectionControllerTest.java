package com.kinlin.ai.controller;

import com.kinlin.ai.entity.Role;
import com.kinlin.ai.projection.role.dto.RoleContextQuery;
import com.kinlin.ai.projection.role.dto.RoleQuery;
import com.kinlin.ai.service.RoleService;
import com.kinlin.ai.service.RoleSwitchOptimizer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class RoleProjectionControllerTest {
    private RoleService service;
    private RoleSwitchOptimizer cache;
    private RoleController controller;
    private MockMvc mvc;
    private Role role;
    private UUID userId;

    @BeforeEach
    void setUp() {
        service = mock(RoleService.class);
        cache = mock(RoleSwitchOptimizer.class);
        controller = new RoleController(service, cache);
        mvc = MockMvcBuilders.standaloneSetup(controller).build();
        userId = UUID.randomUUID();
        role = new Role();
        role.setId(UUID.randomUUID());
        role.setName("custom");
        role.setRoleType(Role.RoleType.CUSTOM);
        role.setUserId(userId);
        role.setSystemPrompt("public prompt");
        role.setDialogueStyle(Map.of("customKey", "kept"));
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(userId, null, List.of()));
    }

    @AfterEach
    void clearIdentity() { SecurityContextHolder.clearContext(); }

    @Test
    void listsAndCachedDetailReturnProjectionWithoutMovingCacheOwnership() throws Exception {
        when(service.getBuiltinRoles()).thenReturn(List.of(role));
        when(service.getCustomRoles(userId)).thenReturn(List.of(role));
        when(cache.getRoleCached(role.getId())).thenReturn(role);
        assertInstanceOf(RoleQuery.class, controller.getBuiltinRoles().getBody().get(0));
        assertInstanceOf(RoleQuery.class, controller.getCustomRoles().getBody().get(0));
        assertInstanceOf(RoleQuery.class, controller.getRole(role.getId()).getBody());
        for (String path : List.of("/roles/builtin", "/roles/custom")) {
            mvc.perform(get(path)).andExpect(status().isOk())
                    .andExpect(jsonPath("$[0].dialogueStyle.customKey").value("kept"));
        }
        mvc.perform(get("/roles/" + role.getId())).andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(role.getId().toString()))
                .andExpect(jsonPath("$.systemPrompt").value("public prompt"));
        verify(service, never()).getRole(any());
    }

    @Test
    void contextProjectsTheExistingServiceResultAndKeepsItsWireNames() throws Exception {
        when(cache.getRoleContext(role.getId())).thenReturn(Map.of(
                "role_id", role.getId().toString(), "name", "custom", "description", "description",
                "system_prompt", "public prompt", "personality", Map.of("patient", true),
                "dialogue_style", role.getDialogueStyle(), "internalExtra", "ignored"));
        assertInstanceOf(RoleContextQuery.class, controller.getRoleContext(role.getId()).getBody());
        mvc.perform(get("/roles/" + role.getId() + "/context")).andExpect(status().isOk())
                .andExpect(jsonPath("$.role_id").value(role.getId().toString()))
                .andExpect(jsonPath("$.dialogue_style.customKey").value("kept"))
                .andExpect(jsonPath("$.system_prompt").value("public prompt"))
                .andExpect(jsonPath("$.internalExtra").doesNotExist());
        verify(cache, never()).getRoleCached(any());
    }

    @Test
    void commandResponsesAlsoProjectWithoutChangingCreatedOrOk() throws Exception {
        when(service.createRole(any(), eq(userId))).thenReturn(role);
        when(service.updateRole(eq(role.getId()), any(), eq(userId))).thenReturn(Optional.of(role));
        String request = "{\"name\":\"custom\",\"systemPrompt\":\"public prompt\",\"dialogueStyle\":{\"customKey\":\"kept\"}}";
        mvc.perform(post("/roles/custom").contentType(MediaType.APPLICATION_JSON).content(request))
                .andExpect(status().isCreated()).andExpect(jsonPath("$.dialogueStyle.customKey").value("kept"));
        mvc.perform(put("/roles/" + role.getId()).contentType(MediaType.APPLICATION_JSON).content(request))
                .andExpect(status().isOk()).andExpect(jsonPath("$.roleType").value("CUSTOM"));
        var captor = org.mockito.ArgumentCaptor.forClass(com.kinlin.ai.dto.RoleCreateRequest.class);
        verify(service).createRole(captor.capture(), eq(userId));
        assertEquals(Map.of("customKey", "kept"), captor.getValue().getDialogueStyle());
        assertInstanceOf(RoleQuery.class, controller.createRole(captor.getValue()).getBody());
        assertInstanceOf(RoleQuery.class, controller.updateRole(role.getId(), captor.getValue()).getBody());
    }

    @Test
    void existingNotFoundAndValidationResponsesArePreserved() throws Exception {
        when(cache.getRoleCached(role.getId())).thenThrow(new RuntimeException("missing"));
        when(cache.getRoleContext(role.getId())).thenThrow(new RuntimeException("missing"));
        when(service.updateRole(eq(role.getId()), any(), eq(userId))).thenReturn(Optional.empty());
        mvc.perform(get("/roles/" + role.getId())).andExpect(status().isNotFound()).andExpect(content().string(""));
        mvc.perform(get("/roles/" + role.getId() + "/context")).andExpect(status().isNotFound()).andExpect(content().string(""));
        mvc.perform(put("/roles/" + role.getId()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"custom\",\"systemPrompt\":\"prompt\"}"))
                .andExpect(status().isNotFound()).andExpect(content().string(""));
        mvc.perform(post("/roles/custom").contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isBadRequest());
    }
}
