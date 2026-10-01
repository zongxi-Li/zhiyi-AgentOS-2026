package com.kinlin.ai.controller;

import com.kinlin.ai.entity.User;
import com.kinlin.ai.projection.user.dto.UserQuery;
import com.kinlin.ai.service.FileService;
import com.kinlin.ai.service.UserService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class UserProjectionControllerTest {
    private UserService service;
    private FileService files;
    private UserController controller;
    private MockMvc mvc;
    private User user;

    @BeforeEach
    void setUp() {
        service = mock(UserService.class);
        files = mock(FileService.class);
        controller = new UserController(service, files);
        mvc = MockMvcBuilders.standaloneSetup(controller).build();
        user = new User();
        user.setId(UUID.randomUUID());
        user.setUsername("alice");
        user.setEmail("alice@example.test");
        user.setPasswordHash("credential-sentinel");
        when(service.getUserById(user.getId())).thenReturn(Optional.of(user));
        when(service.updateUser(user)).thenReturn(user);
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(user.getId(), null, List.of()));
    }

    @AfterEach
    void clearIdentity() { SecurityContextHolder.clearContext(); }

    @Test
    void bothReadsReturnProjectionAndNeverCredentials() throws Exception {
        assertInstanceOf(UserQuery.class, controller.getCurrentUser().getBody());
        assertInstanceOf(UserQuery.class, controller.getUser(user.getId()).getBody());
        for (String path : List.of("/users/me", "/users/" + user.getId())) {
            mvc.perform(get(path)).andExpect(status().isOk())
                    .andExpect(jsonPath("$.username").value("alice"))
                    .andExpect(jsonPath("$.email").value("alice@example.test"))
                    .andExpect(jsonPath("$.passwordHash").doesNotExist());
        }
        verify(service, never()).updateUser(any());
    }

    @Test
    void writesKeepExistingBehaviorButProjectTheirResult() throws Exception {
        mvc.perform(put("/users/" + user.getId()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"renamed\",\"passwordHash\":\"ignored-input\"}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.username").value("renamed"))
                .andExpect(jsonPath("$.passwordHash").doesNotExist());
        assertEquals("credential-sentinel", user.getPasswordHash());
        assertInstanceOf(UserQuery.class, controller.updateUser(user.getId(), new User()).getBody());

        when(files.saveFile(any(), eq("avatars/" + user.getId()))).thenReturn("avatars/new.png");
        MockMultipartFile upload = new MockMultipartFile("file", "avatar.png", "image/png", new byte[]{1});
        mvc.perform(multipart("/users/" + user.getId() + "/avatar").file(upload))
                .andExpect(status().isOk()).andExpect(jsonPath("$.avatar").value("avatars/new.png"))
                .andExpect(jsonPath("$.passwordHash").doesNotExist());
        assertInstanceOf(UserQuery.class, controller.uploadAvatar(user.getId(), upload).getBody());
    }

    @Test
    void missingUsersAndExistingIdentityRejectionsKeepTheirStatus() throws Exception {
        UUID missing = UUID.randomUUID();
        when(service.getUserById(missing)).thenReturn(Optional.empty());
        mvc.perform(get("/users/" + missing)).andExpect(status().isNotFound()).andExpect(content().string(""));
        mvc.perform(put("/users/" + missing).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isBadRequest()).andExpect(content().string(""));
        SecurityContextHolder.clearContext();
        mvc.perform(get("/users/me")).andExpect(status().isBadRequest()).andExpect(content().string(""));
        verify(service, never()).updateUser(any());
    }
}
